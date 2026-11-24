// Thin fetch wrapper for the backend. Calls go to /api on the same origin, so the httpOnly session cookie is sent.

export class ApiError extends Error {
  readonly status: number;
  readonly type: string;
  readonly retryable: boolean;

  constructor(status: number, type: string, message: string, retryable = false) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = type;
    this.retryable = retryable;
  }
}

type ErrorBody = { error?: { type?: string; message?: string; retryable?: boolean } };

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "network", "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ ลองใหม่อีกครั้ง", true);
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as ErrorBody;
    const type = body.error?.type ?? (res.status === 401 ? "auth" : "unknown");
    const message = body.error?.message || fallbackMessage(res.status);
    throw new ApiError(res.status, type, message, body.error?.retryable ?? res.status >= 500);
  }
  return (await res.json()) as T;
}

export function fallbackMessage(status: number): string {
  if (status === 401) return "ต้องเข้าสู่ระบบก่อน";
  if (status === 403) return "บัญชีนี้ไม่มีสิทธิ์เข้าหน้านี้";
  if (status === 404) return "ไม่พบข้อมูลที่ต้องการ";
  if (status >= 500) return "เซิร์ฟเวอร์มีปัญหา ลองใหม่อีกครั้ง";
  return "เกิดข้อผิดพลาด ลองใหม่อีกครั้ง";
}

export function jsonBody(method: "POST" | "PUT" | "DELETE", body: unknown): RequestInit {
  return { method, body: JSON.stringify(body) };
}

export type Me = { user: { username: string; role: string } };
export type AdminUser = {
  id: number;
  username: string;
  role: "user" | "admin";
  created_at: string;
  providers: string[];
  run_count: number;
  last_run_at: string | null;
};
export type UserPage = { items: AdminUser[]; total: number; limit: number; offset: number };
export type UserDetail = {
  user: AdminUser;
  usage_this_window: { window: string; tokens: number };
};
export type Stats = {
  users: { total: number; admins: number; with_sign_in_provider: number };
  runs_24h: { ok: number; partial: number; error: number };
  active_users_24h: number;
  window: string;
  tokens_this_window: number;
  generated_at: string;
};
