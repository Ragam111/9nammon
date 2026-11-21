"""Per-user token quota stored in SQLite.

A quota window is a fixed block of WINDOW_HOURS that starts at 00:00 Bangkok time
(00:00, 05:00, 10:00, 15:00, 20:00). The usage table keeps the window key in its `day` column;
daily keys from before this change ("2026-11-21") simply never match a window key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Settings
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


# ---- Buckets: every run counts against each bucket that applies to its model ----
# five_hour: all models, 5-hour blocks.  weekly: all models, resets Wednesday 15:00 Bangkok.
# heavy_weekly: only models listed in HEAVY_MODELS, same weekly reset.
WEEK_RESET_WEEKDAY = 2  # Monday = 0, so 2 is Wednesday
WEEK_RESET_HOUR = 15
_LABELS = {
    "five_hour": "โควตา 5 ชั่วโมง",
    "weekly": "โควตารายสัปดาห์",
    "heavy_weekly": "โควตาโมเดลหนักรายสัปดาห์",
}


@dataclass(frozen=True)
class Bucket:
    """One limit a run counts against: its name, storage key, token limit and reset time."""

    name: str
    key: str
    limit: int
    resets_at: str


def week_start(now: datetime | None = None) -> datetime:
    """The most recent Wednesday 15:00 (Bangkok time) at or before `now`."""
    local = _local(now)
    back = (local.weekday() - WEEK_RESET_WEEKDAY) % 7
    anchor = (local - timedelta(days=back)).replace(hour=WEEK_RESET_HOUR, minute=0, second=0, microsecond=0)
    return anchor if anchor <= local else anchor - timedelta(days=7)


def plan(settings: Settings, heavy: bool, now: datetime | None = None) -> list[Bucket]:
    """The buckets that apply to one run. `heavy` is True when the run uses a model in HEAVY_MODELS."""
    week = week_start(now)
    week_key = week.strftime("%Y-%m-%dT%H")
    week_ends = (week + timedelta(days=7)).isoformat()
    buckets = [
        Bucket("five_hour", f"5h|{current_window(now)}", settings.quota_tokens_per_window, window_resets_at(now)),
        Bucket("weekly", f"wk|{week_key}", settings.quota_tokens_weekly, week_ends),
    ]
    if heavy:
        buckets.append(Bucket("heavy_weekly", f"hwk|{week_key}", settings.quota_tokens_heavy_weekly, week_ends))
    return buckets


def check_all(db: Database, user_id: int, buckets: list[Bucket], need: int) -> None:
    """Refuse the run when any bucket is used up or has fewer than `need` tokens left."""
    for bucket in buckets:
        left = max(0, bucket.limit - used(db, user_id, bucket.key))
        label = _LABELS[bucket.name]
        if left <= 0:
            raise AppError("quota", f"{label}หมดแล้ว — รีเซ็ตเวลา {_thai_time(bucket.resets_at)}")
        if left < need:
            raise AppError("quota", f"{label}เหลือ {left} token ไม่พอสำหรับคำขอนี้ — ย่อข้อความหรือรอรีเซ็ต")


def record_all(db: Database, user_id: int, buckets: list[Bucket], tokens: int) -> None:
    """Add the run's tokens to every bucket that applies to it."""
    for bucket in buckets:
        record(db, user_id, tokens, window=bucket.key)


def _thai_time(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b %H:%M")
