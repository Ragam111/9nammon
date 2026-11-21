"""Per-user token quota stored in SQLite.

A quota window is a fixed block of WINDOW_HOURS that starts at 00:00 Bangkok time
(00:00, 05:00, 10:00, 15:00, 20:00). The usage table keeps the window key in its `day` column;
daily keys from before this change ("2026-11-21") simply never match a window key.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .db import Database
from .errors import AppError

BANGKOK = timezone(timedelta(hours=7))  # Thailand has no DST, so a fixed offset is exact
WINDOW_HOURS = 5


def _local(now: datetime | None) -> datetime:
    return (now or datetime.now(BANGKOK)).astimezone(BANGKOK)


def window_start(now: datetime | None = None) -> datetime:
    """The first moment of the window that contains `now` (Bangkok time)."""
    local = _local(now)
    return local.replace(hour=local.hour - local.hour % WINDOW_HOURS, minute=0, second=0, microsecond=0)


def current_window(now: datetime | None = None) -> str:
    """Key for the current window, e.g. '2026-11-21T05'."""
    return window_start(now).strftime("%Y-%m-%dT%H")


def window_resets_at(now: datetime | None = None) -> str:
    """ISO time (with +07:00) when the current window ends.

    5-hour blocks do not divide a day evenly, so the last block (20:00) ends at midnight after 4 hours.
    """
    start = window_start(now)
    midnight = start.replace(hour=0) + timedelta(days=1)
    return min(start + timedelta(hours=WINDOW_HOURS), midnight).isoformat()


def used(db: Database, user_id: int, window: str | None = None) -> int:
    """Tokens the user has used in `window` (default: the current window)."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT tokens FROM usage WHERE user_id = ? AND day = ?", (user_id, window or current_window())
        ).fetchone()
    return int(row["tokens"]) if row else 0


def remaining(db: Database, user_id: int, limit: int, window: str | None = None) -> int:
    return max(0, limit - used(db, user_id, window))


def check(db: Database, user_id: int, limit: int, window: str | None = None, need: int = 1) -> None:
    """Raise AppError('quota') when fewer than `need` tokens are left in the window.

    Callers pass the prompt estimate plus the output cap, so one request cannot run far past the limit.
    Concurrent requests from the same user can still overshoot by at most one request each.
    """
    left = remaining(db, user_id, limit, window)
    if left <= 0:
        raise AppError("quota")
    if left < need:
        raise AppError(
            "quota", f"โควตารอบ {WINDOW_HOURS} ชั่วโมงนี้เหลือ {left} token ไม่พอสำหรับคำขอนี้ — ย่อข้อความหรือรอรอบถัดไป"
        )


def record(db: Database, user_id: int, tokens: int, window: str | None = None) -> None:
    """Add tokens to the user's usage for `window`. Negative values are ignored."""
    if tokens <= 0:
        return
    with db.session() as conn:
        conn.execute(
            "INSERT INTO usage (user_id, day, tokens) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, day) DO UPDATE SET tokens = tokens + excluded.tokens",
            (user_id, window or current_window(), tokens),
        )
