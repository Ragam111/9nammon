"""Error types and their mapping to HTTP status and a Thai message the user can act on."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

ERROR_TYPES = ("auth", "quota", "rate_limit", "timeout", "validation", "upstream", "unknown")

# type -> (http status, user message, retryable)
_CATALOG: dict[str, tuple[int, str, bool]] = {
    "auth": (401, "ต้องเข้าสู่ระบบก่อน หรือ session หมดอายุ — เข้าสู่ระบบใหม่", False),
    "quota": (429, "ใช้ token ครบโควตาของวันนี้แล้ว — รอวันใหม่หรือติดต่อผู้ดูแลเพื่อเพิ่มโควตา", False),
    "rate_limit": (429, "ส่งคำขอถี่เกินไป — รอสักครู่แล้วลองใหม่", True),
    "timeout": (504, "โมเดลตอบช้าเกินเวลาที่กำหนด — ลองใหม่ หรือย่อข้อความให้สั้นลง", True),
    "validation": (422, "ข้อมูลที่ส่งมาไม่ถูกต้อง — ตรวจสอบแล้วลองใหม่", False),
    "upstream": (502, "บริการโมเดลมีปัญหาชั่วคราว — ลองใหม่อีกครั้ง", True),
    "unknown": (500, "เกิดข้อผิดพลาดที่ไม่คาดคิด — ลองใหม่ ถ้ายังเกิดซ้ำให้แจ้งผู้ดูแลพร้อม request id", False),
}


@dataclass
class AppError(Exception):
    """An error with a known type. `message` overrides the default user message when given."""

    type: str
    message: str = ""
    retry_after_s: int | None = None
    http_status: int | None = None  # e.g. 403 for a logged-in user who lacks a role, 404 for a missing row

    def __post_init__(self) -> None:
        if self.type not in _CATALOG:
            raise ValueError(f"unknown error type {self.type!r}")

    @property
    def status(self) -> int:
        return self.http_status or _CATALOG[self.type][0]

    @property
    def retryable(self) -> bool:
        return _CATALOG[self.type][2]

    @property
    def user_message(self) -> str:
        return self.message or _CATALOG[self.type][1]

    def to_dict(self, request_id: str = "") -> dict[str, object]:
        body: dict[str, object] = {"type": self.type, "message": self.user_message, "retryable": self.retryable}
        if request_id:
            body["request_id"] = request_id
        if self.retry_after_s is not None:
            body["retry_after_s"] = self.retry_after_s
        return body


MODEL_KEY_INVALID = "API key ของโมเดลไม่ถูกต้องหรือหมดอายุ — ตั้งค่า key ใหม่ในหน้า Settings"


def _retry_after(value: str | None) -> int | None:
    try:
        return max(1, int(float(value))) if value else None
    except ValueError:
        return None


def from_upstream_status(status: int, retry_after: str | None = None) -> AppError:
    """Map an HTTP status returned by the model provider to an AppError."""
    if status in (401, 403):
        return AppError("upstream", MODEL_KEY_INVALID)
    if status == 429:
        return AppError("rate_limit", "บริการโมเดลจำกัดความถี่อยู่ — รอสักครู่แล้วลองใหม่",
                        retry_after_s=_retry_after(retry_after))
    if status in (400, 404, 413, 422):
        return AppError("validation", f"บริการโมเดลไม่รับคำขอนี้ (HTTP {status})")
    if status >= 500:
        return AppError("upstream")
    return AppError("unknown")


def is_retryable_upstream_status(status: int) -> bool:
    """Only throttling and server errors are worth retrying; client errors are not."""
    return status == 429 or status >= 500


def from_exception(exc: BaseException) -> AppError:
    """Map any exception raised while calling the model to an AppError."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return AppError("timeout")
    if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)):
        return AppError("upstream", "เชื่อมต่อบริการโมเดลไม่ได้ — ตรวจว่าเซิร์ฟเวอร์โมเดลทำงานอยู่ แล้วลองใหม่")
    if isinstance(exc, httpx.HTTPStatusError):
        return from_upstream_status(exc.response.status_code, exc.response.headers.get("retry-after"))
    return AppError("unknown")


# Safe to retry: open_stream only retries before any byte has reached the browser.
_RETRYABLE_NETWORK = (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError,
                      httpx.ReadError, httpx.WriteError)


def is_retryable_exception(exc: BaseException) -> bool:
    """Network-level failures and retryable statuses are retried; everything else is not."""
    if isinstance(exc, _RETRYABLE_NETWORK):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return is_retryable_upstream_status(exc.response.status_code)
    return False
