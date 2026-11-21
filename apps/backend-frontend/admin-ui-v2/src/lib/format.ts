// Pure helpers: time display in Asia/Bangkok, Thai labels, and the query string for the users list.

export const BANGKOK_TZ = "Asia/Bangkok";

/**
 * The backend stores times in two shapes: SQLite datetime('now') gives "2026-11-21 10:00:00" in UTC
 * with no zone, and the run timestamps already end in "Z". Normalize both to an ISO UTC string.
 */
export function parseServerTime(value: string): Date {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(value);
  const iso = hasZone ? value.replace(" ", "T") : `${value.replace(" ", "T")}Z`;
  return new Date(iso);
}

export function formatBangkok(value: string | null): string {
  if (!value) return "ยังไม่มี";
  const date = parseServerTime(value);
  if (Number.isNaN(date.getTime())) return "ไม่ทราบเวลา";
  return new Intl.DateTimeFormat("th-TH", {
    timeZone: BANGKOK_TZ,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function roleLabel(role: string): string {
  return role === "admin" ? "ผู้ดูแลระบบ" : "ผู้ใช้";
}

export function providerLabel(provider: string): string {
  const labels: Record<string, string> = { google: "Google", github: "GitHub" };
  return labels[provider] ?? provider;
}

export type UsersQuery = {
  q: string;
  role: "" | "user" | "admin";
  sort: "created_at" | "username" | "run_count" | "last_run_at";
  order: "asc" | "desc";
  offset: number;
  limit: number;
};

/** Build the query string, leaving out anything that is at its default so URLs stay short. */
export function buildUsersQuery(query: UsersQuery): string {
  const params = new URLSearchParams();
  const q = query.q.trim();
  if (q) params.set("q", q);
  if (query.role) params.set("role", query.role);
  if (query.sort !== "created_at") params.set("sort", query.sort);
  if (query.order !== "desc") params.set("order", query.order);
  if (query.offset > 0) params.set("offset", String(query.offset));
  if (query.limit !== 20) params.set("limit", String(query.limit));
  const text = params.toString();
  return text ? `?${text}` : "";
}
