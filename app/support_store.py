"""
support_store.py — ระบบรับเรื่อง support/บั๊กจากลูกค้า เก็บลง SQLite (stdlib)

ทำไมต้องมี (ตามที่ user สั่ง): เปิดให้คนใช้จริง → ลูกค้าต้องแจ้งปัญหา/ขอฟีเจอร์ได้
แล้วเรารู้ทันที (ยิง Discord/email ผ่าน notifier) → ไล่แก้ → ปิดเรื่อง. นี่คือ "ฐาน"
ของ loop ซัปพอร์ต: รับเรื่อง → แจ้งเตือน → ตามสถานะ → ปิด

สไตล์เดิม: stdlib เท่านั้น, per-project store (support.db), connection ต่อ call
(ปลอดภัยกับ ThreadingHTTPServer), SQL parametrised, validate input, ไม่ crash โปรแกรมหลัก

โมเดล:
    channel : web | api | email | discord   (เรื่องเข้ามาทางไหน)
    kind    : bug | feature | question | other
    status  : open -> in_progress -> resolved -> closed

Interface:
    create_ticket(project_root, reporter, subject, body, kind="bug", channel="web") -> dict
    list_tickets(project_root, status=None, kind=None, limit=100) -> list[dict]  # ใหม่สุดก่อน
    get_ticket(project_root, ticket_id) -> dict | None
    set_status(project_root, ticket_id, status) -> dict | None
    counts_by_status(project_root) -> dict   # สรุปจำนวนต่อสถานะ (ไว้โชว์ dashboard)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

SUPPORT_DB_NAME = "support.db"
VALID_KINDS = {"bug", "feature", "question", "other"}
VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}
VALID_CHANNELS = {"web", "api", "email", "discord"}
_MAX_SUBJECT = 200
_MAX_BODY = 5000


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(project_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(project_root / SUPPORT_DB_NAME), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            channel TEXT NOT NULL,
            reporter TEXT,
            kind TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
        )"""
    )
    return conn


def create_ticket(project_root: Path, reporter: str, subject: str, body: str,
                  kind: str = "bug", channel: str = "web") -> dict:
    """สร้าง ticket ใหม่สถานะ open — raise ValueError ถ้า input ผิด"""
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject:
        raise ValueError("ต้องระบุ subject")
    if not body:
        raise ValueError("ต้องระบุ body (รายละเอียดปัญหา)")
    if len(subject) > _MAX_SUBJECT:
        raise ValueError(f"subject ยาวเกิน {_MAX_SUBJECT} ตัวอักษร")
    if len(body) > _MAX_BODY:
        raise ValueError(f"body ยาวเกิน {_MAX_BODY} ตัวอักษร")
    kind = (kind or "bug").strip().lower()
    if kind not in VALID_KINDS:
        raise ValueError(f"kind ไม่ถูกต้อง: {kind} (ต้องเป็น {sorted(VALID_KINDS)})")
    channel = (channel or "web").strip().lower()
    if channel not in VALID_CHANNELS:
        raise ValueError(f"channel ไม่ถูกต้อง: {channel} (ต้องเป็น {sorted(VALID_CHANNELS)})")

    now = _now()
    with _connect(project_root) as conn:
        cur = conn.execute(
            "INSERT INTO tickets (created_at, updated_at, channel, reporter, kind, subject, body, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open')",
            (now, now, channel, (reporter or "").strip() or None, kind, subject, body),
        )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_tickets(project_root: Path, status: Optional[str] = None,
                 kind: Optional[str] = None, limit: int = 100) -> list:
    """คืน ticket ล่าสุดก่อน กรองตาม status / kind ได้"""
    where, params = [], []
    if status is not None:
        status = status.strip().lower()
        if status not in VALID_STATUSES:
            raise ValueError(f"status ไม่ถูกต้อง: {status}")
        where.append("status = ?")
        params.append(status)
    if kind is not None:
        kind = kind.strip().lower()
        if kind not in VALID_KINDS:
            raise ValueError(f"kind ไม่ถูกต้อง: {kind}")
        where.append("kind = ?")
        params.append(kind)
    sql = "SELECT * FROM tickets"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with _connect(project_root) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def get_ticket(project_root: Path, ticket_id: int) -> Optional[dict]:
    with _connect(project_root) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (int(ticket_id),)).fetchone()
    return dict(row) if row else None


def set_status(project_root: Path, ticket_id: int, status: str) -> Optional[dict]:
    """เปลี่ยนสถานะ ticket — คืน record ที่อัปเดต หรือ None ถ้าไม่เจอ id"""
    status = (status or "").strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"status ไม่ถูกต้อง: {status} (ต้องเป็น {sorted(VALID_STATUSES)})")
    with _connect(project_root) as conn:
        cur = conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), int(ticket_id)),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (int(ticket_id),)).fetchone()
    return dict(row)


def counts_by_status(project_root: Path) -> dict:
    """สรุปจำนวน ticket ต่อสถานะ (ทุกสถานะเริ่มที่ 0 เพื่อให้ dashboard แสดงครบ)"""
    out = {s: 0 for s in VALID_STATUSES}
    with _connect(project_root) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM tickets GROUP BY status"
        ).fetchall()
    for r in rows:
        if r["status"] in out:
            out[r["status"]] = int(r["n"])
    out["total"] = sum(out[s] for s in VALID_STATUSES)
    return out
