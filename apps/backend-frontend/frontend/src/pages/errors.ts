import type { ApiError, ErrorType } from "../api";

const TITLES: Record<ErrorType, string> = {
  auth: "ต้องเข้าสู่ระบบใหม่",
  quota: "โควตารอบ 5 ชั่วโมงเต็มแล้ว",
  rate_limit: "ส่งคำขอถี่เกินไป",
  timeout: "หมดเวลารอคำตอบ",
  validation: "ข้อมูลไม่ถูกต้อง",
  upstream: "บริการโมเดลมีปัญหา",
  unknown: "เกิดข้อผิดพลาด",
  network: "การเชื่อมต่อหลุด",
  cancelled: "หยุดแล้ว",
};

export const errorTitle = (err: ApiError): string => TITLES[err.type] ?? TITLES.unknown;

/** The model key on the server is wrong or missing: the fix is on the Settings page, not a retry. */
export const isKeyProblem = (err: ApiError): boolean => err.type === "upstream" && err.message.includes("API key");

export function errorDetail(err: ApiError): string {
  const wait = err.retryAfterS ? ` (รอประมาณ ${err.retryAfterS} วินาที)` : "";
  const ref = err.requestId ? ` · request id: ${err.requestId}` : "";
  return `${err.message}${wait}${ref}`;
}
