"""Per-user daily token quota stored in SQLite. Days are UTC dates."""

from __future__ import annotations

from datetime import UTC, datetime

from .db import Database
from .errors import AppError


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def used(db: Database, user_id: int, day: str | None = None) -> int:
    """Tokens the user has used on `day` (default: today)."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT tokens FROM usage WHERE user_id = ? AND day = ?", (user_id, day or today())
        ).fetchone()
    return int(row["tokens"]) if row else 0


def remaining(db: Database, user_id: int, limit: int, day: str | None = None) -> int:
    return max(0, limit - used(db, user_id, day))


def check(db: Database, user_id: int, limit: int, day: str | None = None, need: int = 1) -> None:
    """Raise AppError('quota') when fewer than `need` tokens are left today.

    Callers pass the prompt estimate plus the output cap, so one request cannot run far past the limit.
    Concurrent requests from the same user can still overshoot by at most one request each.
    """
    left = remaining(db, user_id, limit, day)
    if left <= 0:
        raise AppError("quota")
    if left < need:
        raise AppError("quota", f"โควตาวันนี้เหลือ {left} token ไม่พอสำหรับคำขอนี้ — ย่อข้อความหรือรอวันใหม่")


def record(db: Database, user_id: int, tokens: int, day: str | None = None) -> None:
    """Add tokens to the user's usage for `day`. Negative values are ignored."""
    if tokens <= 0:
        return
    with db.session() as conn:
        conn.execute(
            "INSERT INTO usage (user_id, day, tokens) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, day) DO UPDATE SET tokens = tokens + excluded.tokens",
            (user_id, day or today(), tokens),
        )
