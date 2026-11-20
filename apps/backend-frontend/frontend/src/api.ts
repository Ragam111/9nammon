// Typed client for the backend. Cookies carry the session; the model key never reaches the browser.

export type ErrorType =
  | "auth" | "quota" | "rate_limit" | "timeout" | "validation" | "upstream" | "unknown" | "network" | "cancelled";

export class ApiError extends Error {
  constructor(
    public type: ErrorType,
    message: string,
    public retryable: boolean,
    public requestId?: string,
    public retryAfterS?: number,
    public partial = false,
  ) {
    super(message);
  }
}

export type User = { username: string; role: "user" | "admin" };
export type KeyStatus = { configured: boolean; last4: string; source: "env" | "stored" | "none" };
export type RunStatus = "ok" | "partial" | "error";

export type SettingsView = {
  user: User;
  model: string;
  key: KeyStatus;
  quota: { day: string; used: number; limit: number; remaining: number };
  rate_limit: { user_per_min: number; ip_per_min: number; user_remaining: number };
  limits: { max_input_chars: number; max_output_tokens: number };
};

export type RunSummary = {
  id: string; model: string; prompt_preview: string; status: RunStatus; error_type: string | null;
  tokens_in: number; tokens_out: number; latency_ms: number; created_at: string;
};
export type RunDetail = Omit<RunSummary, "prompt_preview"> & { prompt: string; output: string };
export type HistoryPage = { items: RunSummary[]; total: number };
export type Health = { status: string; model: string; model_key_configured: boolean };

const NETWORK_MSG = "เชื่อมต่อ server ไม่ได้ — ตรวจอินเทอร์เน็ตหรือว่า server เปิดอยู่ แล้วลองใหม่";

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { type: ErrorType; message: string; retryable: boolean; request_id?: string; retry_after_s?: number } };
    const e = body.error;
    if (e?.type) return new ApiError(e.type, e.message, e.retryable, e.request_id, e.retry_after_s);
  } catch {
    // not JSON: fall through to a generic message
  }
  return new ApiError("unknown", `เกิดข้อผิดพลาด (HTTP ${res.status})`, false);
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const headers: Record<string, string> = init.body ? { "Content-Type": "application/json" } : {};
  let res: Response;
  try {
    res = await fetch(path, { ...init, credentials: "same-origin", headers: { ...headers, ...(init.headers as Record<string, string>) } });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError("cancelled", "ยกเลิกแล้ว", true);
    throw new ApiError("network", NETWORK_MSG, true);
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await send(path, init);
  return (await res.json()) as T;
}

export const json = (method: string, body?: unknown): RequestInit =>
  ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

// ---------- streaming run ----------

export type RunHandlers = { onStart?: (runId: string) => void; onDelta: (text: string) => void; signal?: AbortSignal };
export type RunDone = { runId: string; tokens_in: number; tokens_out: number; latency_ms: number };

type SseEvent = { event: string; data: Record<string, unknown> };

function parseBlock(block: string): SseEvent | null {
  let event = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7);
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!event) return null;
  try {
    return { event, data: JSON.parse(data) as Record<string, unknown> };
  } catch {
    return null;
  }
}

function handleEvent(ev: SseEvent, h: RunHandlers, state: { runId: string; gotText: boolean }): RunDone | null {
  const d = ev.data;
  if (ev.event === "start") { state.runId = String(d.run_id); h.onStart?.(state.runId); }
  if (ev.event === "delta") { state.gotText = true; h.onDelta(String(d.text)); }
  if (ev.event === "error") {
    throw new ApiError(d.type as ErrorType, String(d.message), Boolean(d.retryable), d.request_id as string | undefined, undefined, Boolean(d.partial));
  }
  if (ev.event === "done") {
    return { runId: state.runId, tokens_in: Number(d.tokens_in), tokens_out: Number(d.tokens_out), latency_ms: Number(d.latency_ms) };
  }
  return null;
}

/** POST /api/run and read the SSE stream. Throws ApiError; `partial` is true when some text arrived. */
export async function streamRun(prompt: string, h: RunHandlers): Promise<RunDone> {
  const res = await send("/api/run", { ...json("POST", { prompt }), signal: h.signal });
  const reader = res.body?.getReader();
  if (!reader) throw new ApiError("unknown", "browser นี้อ่านคำตอบแบบ streaming ไม่ได้", false);
  const decoder = new TextDecoder();
  const state = { runId: "", gotText: false };
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let cut: number;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const ev = parseBlock(buffer.slice(0, cut));
        buffer = buffer.slice(cut + 2);
        const finished = ev ? handleEvent(ev, h, state) : null;
        if (finished) return finished;
      }
    }
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError("cancelled", "หยุดแล้ว — ผลที่ได้มาแล้วยังอยู่", true, undefined, undefined, state.gotText);
    throw new ApiError("network", "การเชื่อมต่อหลุดระหว่างรับคำตอบ — ผลที่ได้มาแล้วยังอยู่ ลองใหม่ได้", true, undefined, undefined, state.gotText);
  }
  throw new ApiError("network", "คำตอบจบไม่ครบ — ผลที่ได้มาแล้วยังอยู่ ลองใหม่ได้", true, undefined, undefined, state.gotText);
}
