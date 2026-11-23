// Typed client for the chat API. Same cookie and error rules as api.ts; provider keys never reach the browser.
import { api, ApiError, json, send, type ErrorType } from "./api";

export type Provider = "claude" | "gemini" | "gpt" | "ollama";
export type ChatModel = { id: string; provider: Provider; label: string; configured: boolean };
export type ConversationSummary = { id: string; title: string; model: string; updated_at: string };
export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "complete" | "partial";
  created_at: string;
};
export type ConversationDetail = { id: string; title: string; model: string; messages: ChatMessage[] };

const BASE = "/api/chat";
const convPath = (id: string): string => `${BASE}/conversations/${encodeURIComponent(id)}`;

export async function listChatModels(): Promise<ChatModel[]> {
  return (await api<{ models: ChatModel[] }>(`${BASE}/models`)).models;
}

export async function listConversations(): Promise<ConversationSummary[]> {
  return (await api<{ conversations: ConversationSummary[] }>(`${BASE}/conversations`)).conversations;
}

export function createConversation(model: string): Promise<ConversationSummary> {
  return api<ConversationSummary>(`${BASE}/conversations`, json("POST", { model }));
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return api<ConversationDetail>(convPath(id));
}

export function renameConversation(id: string, title: string): Promise<{ id: string; title: string }> {
  return api<{ id: string; title: string }>(convPath(id), json("PATCH", { title }));
}

export async function deleteConversation(id: string): Promise<void> {
  await send(convPath(id), json("DELETE"));
}

// ---------- streaming send ----------

export type ChatDone = { messageId: string; tokensIn: number; tokensOut: number };
export type ChatStreamHandlers = {
  signal?: AbortSignal;
  onStart: (messageId: string) => void;
  onDelta: (text: string) => void;
};

type SseEvent = { event: string; data: Record<string, unknown> };
type StreamState = { gotText: boolean };

const SERVER_ERROR_TYPES: readonly ErrorType[] = [
  "auth", "quota", "rate_limit", "timeout", "validation", "upstream", "unknown",
];
const RETRYABLE: readonly ErrorType[] = ["rate_limit", "timeout", "upstream", "network"];

/** Parses one SSE block (lines up to a blank line). Returns null for comments or bad JSON. */
function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) as Record<string, unknown> };
  } catch {
    return null;
  }
}

function streamError(d: Record<string, unknown>): ApiError {
  const raw = typeof d.code === "string" ? d.code : "";
  const code = (SERVER_ERROR_TYPES as readonly string[]).includes(raw) ? (raw as ErrorType) : "unknown";
  return new ApiError(code, String(d.message ?? "เกิดข้อผิดพลาด"), RETRYABLE.includes(code), undefined, undefined, Boolean(d.partial));
}

/** Routes one event. Returns the final result on "done", throws on "error". */
function dispatch(ev: SseEvent, h: ChatStreamHandlers, state: StreamState): ChatDone | null {
  const d = ev.data;
  if (ev.event === "start") h.onStart(String(d.message_id));
  else if (ev.event === "delta") {
    state.gotText = true;
    h.onDelta(String(d.text ?? ""));
  } else if (ev.event === "done") {
    return { messageId: String(d.message_id), tokensIn: Number(d.tokens_in ?? 0), tokensOut: Number(d.tokens_out ?? 0) };
  } else if (ev.event === "error") throw streamError(d);
  return null;
}

/** POST a user message and read the SSE reply. Throws ApiError; `partial` is true when some text arrived. */
export async function streamChatMessage(
  conversationId: string,
  content: string,
  model: string | null,
  h: ChatStreamHandlers,
): Promise<ChatDone> {
  const res = await send(`${convPath(conversationId)}/messages`, { ...json("POST", { content, model }), signal: h.signal });
  const reader = res.body?.getReader();
  if (!reader) throw new ApiError("unknown", "browser นี้อ่านคำตอบแบบ streaming ไม่ได้", false);
  const decoder = new TextDecoder();
  const state: StreamState = { gotText: false };
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
      let cut = buffer.indexOf("\n\n");
      while (cut >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const finished = parseSseBlock(block);
        const result = finished ? dispatch(finished, h, state) : null;
        if (result) return result;
        cut = buffer.indexOf("\n\n");
      }
    }
    const tail = parseSseBlock(buffer + decoder.decode());
    const last = tail ? dispatch(tail, h, state) : null;
    if (last) return last;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("cancelled", "หยุดแล้ว — ข้อความที่ได้มาแล้วยังอยู่", true, undefined, undefined, state.gotText);
    }
    throw new ApiError("network", "การเชื่อมต่อหลุดระหว่างรับคำตอบ — ลองใหม่ได้", true, undefined, undefined, state.gotText);
  }
  throw new ApiError("network", "คำตอบจบไม่ครบ — ลองใหม่ได้", true, undefined, undefined, state.gotText);
}
