import { ALLOWED_ORIGINS, AUTH_PATH } from "./config.js";

export function isAllowedOrigin(origin) {
  return ALLOWED_ORIGINS.indexOf(origin) !== -1;
}

/** redirect URI ต่อจาก origin ของหน้านี้ + พาธ callback ที่ตกลงไว้ */
export function redirectUriFor(origin) {
  return String(origin || "") + AUTH_PATH;
}

export function originBlockedMessage(origin) {
  const shown = origin ? String(origin) : "(ว่าง)";
  return (
    "หน้านี้ถูกเปิดจาก origin ที่ Google ไม่ได้อนุญาต: " + shown +
    ". เปิดจาก http://localhost:8421 หรือ http://127.0.0.1:8421 เท่านั้น " +
    "ไม่งั้น Google ตอบ 400 origin_mismatch"
  );
}
