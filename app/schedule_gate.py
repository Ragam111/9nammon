"""schedule_gate.py — เวลาเปิด-ปิดเซิร์ฟเวอร์ตามเวลาไทย (UTC+7)

โจทย์ (ตามที่ user สั่ง): ปิดเซิร์ฟเวอร์ประมาณ 20:00-06:00 ไทย เปิด 06:00-20:00 (14 ชั่วโมง/วัน)
— ประหยัดค่าไฟ/ค่า cloud เวลาไม่มีคนใช้ และกันพัฒนาตอนลูกค้าออนไลน์

วิธี: คำนวณชั่วโมงไทย (UTC+7) จาก now (UTC) → เปรียบเทียบกับ [open_hour, close_hour).
window ปกติไม่ข้ามเที่ยงคืน (6..20). ถ้ามีคนตั้งข้ามเที่ยงคืน (22..6) ก็รองรับได้.

config: SCHEDULE_ENABLED (default False — เปิดเมื่อ user สั่ง), SCHEDULE_OPEN_HOUR (6),
SCHEDULE_CLOSE_HOUR (20). timezone คง UTC+7 (ไทย) ตามโจทย์ ไม่ configurable (keep it simple).

ไม่พึ่ง zoneinfo (python 3.9+ มีแต่ Windows ไม่มี tzdata เสมอ) — ใช้ offset ตรงๆ กัน flake
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import config_manager

TH_OFFSET_HOURS = 7
TH_TZ = timezone(timedelta(hours=TH_OFFSET_HOURS))

DEFAULT_OPEN_HOUR = 6     # 06:00 ไทย
DEFAULT_CLOSE_HOUR = 20   # 20:00 ไทย
# ชื่อ key ใน config.json
CFG_ENABLED = "SCHEDULE_ENABLED"
CFG_OPEN = "SCHEDULE_OPEN_HOUR"
CFG_CLOSE = "SCHEDULE_CLOSE_HOUR"


def _th_now(now_utc: datetime | None = None) -> datetime:
    """คืนเวลาไทยปัจจุบัน (aware datetime). ไม่ส่ง → ใช้ now() จริง"""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(TH_TZ)


def _clamp_hour(value, default: int) -> int:
    """รับค่าชั่วโมงจาก config → int 0..23 (ค่าไม่ถูกต้อง → default)"""
    try:
        h = int(value)
    except (TypeError, ValueError):
        return default
    if h < 0 or h > 23:
        return default
    return h


def window_hours(project_root) -> tuple[int, int]:
    """อ่าน open_hour, close_hour จาก config → ค่าปัจจุบัน"""
    open_h = _clamp_hour(
        config_manager.get_key(project_root, CFG_OPEN), DEFAULT_OPEN_HOUR)
    close_h = _clamp_hour(
        config_manager.get_key(project_root, CFG_CLOSE), DEFAULT_CLOSE_HOUR)
    return open_h, close_h


def enabled(project_root) -> bool:
    """อ่าน SCHEDULE_ENABLED จาก config → True/False (default: False)
    ค่าถือเป็น True ถ้าเป็น "1", "true", "yes", "on" (case-insensitive)"""
    v = config_manager.get_key(project_root, CFG_ENABLED)
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def is_open(now_utc: datetime | None = None,
            open_hour: int = DEFAULT_OPEN_HOUR,
            close_hour: int = DEFAULT_CLOSE_HOUR) -> bool:
    """เซิร์ฟเวอร์เปิดอยู่ไหมที่เวลา now_utc (default now).

    window = [open_hour, close_hour) ตามเวลาไทย.
    - open_hour < close_hour: window ภายในวันเดียว (เช่น 6..20 → 06:00-20:00)
    - open_hour > close_hour: window ข้ามเที่ยงคืน (เช่น 22..6 → 22:00-06:00 รุ่งเช้า)
    - open_hour == close_hour: ถือว่าปิดตลอด (always closed) — degrade กรณี config สับสน"""
    if open_hour == close_hour:
        return False
    th = _th_now(now_utc)
    hour = th.hour
    if open_hour < close_hour:
        return open_hour <= hour < close_hour
    # ข้ามเที่ยงคืน: เปิดถ้าชั่วโมง >= open_hour หรือ < close_hour
    return hour >= open_hour or hour < close_hour


def next_window(now_utc: datetime | None = None,
                open_hour: int = DEFAULT_OPEN_HOUR,
                close_hour: int = DEFAULT_CLOSE_HOUR) -> dict:
    """คืนสถานะปัจจุบัน + เวลาถัดไปที่จะเปลี่ยนสถานะ
    {
        state: "open" | "closed",
        open_hour: int, close_hour: int,
        next_change_at_th: ISO 8601 string (เวลาไทย),
        seconds_until_change: int (วินาทีจาก now ถึงเวลาเปลี่ยนสถานะ)
    }"""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    th = now_utc.astimezone(TH_TZ)
    state = "open" if is_open(now_utc, open_hour, close_hour) else "closed"
    target_hour = close_hour if state == "open" else open_hour

    # หาเวลาเปลี่ยนสถานะถัดไป (วันนี้หรือพรุ่งนี้)
    candidate = th.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if candidate <= th:
        candidate = candidate + timedelta(days=1)

    seconds = int((candidate - th).total_seconds())
    return {
        "state": state,
        "open_hour": open_hour,
        "close_hour": close_hour,
        "next_change_at_th": candidate.isoformat(),
        "seconds_until_change": seconds,
    }


def status(project_root, now_utc: datetime | None = None) -> dict:
    """สถานะโดยอ่าน config จริง — ใช้ใน endpoint /api/status
    ถ้า SCHEDULE_ENABLED=False → state="open" เสมอ (เซิร์ฟเวอร์ไม่ถูกจำกัดด้วย schedule)"""
    if not enabled(project_root):
        return {"enabled": False, "state": "open", "message": "schedule gate ปิดอยู่"}
    open_h, close_h = window_hours(project_root)
    info = next_window(now_utc, open_h, close_h)
    info["enabled"] = True
    if info["state"] == "closed":
        hrs = info["seconds_until_change"] // 3600
        mins = (info["seconds_until_change"] % 3600) // 60
        info["message"] = (f"เซิร์ฟเวอร์ปิดตามตารางเวลา (เวลาเปิด {open_h:02d}:00-"
                           f"{close_h:02d}:00 เวลาไทย) — จะเปิดอีกใน {hrs} ชม. {mins} นาที")
    else:
        info["message"] = (f"เซิร์ฟเวอร์เปิดอยู่ (เวลาเปิด {open_h:02d}:00-"
                           f"{close_h:02d}:00 เวลาไทย)")
    return info
