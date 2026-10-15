"""
job_queue.py — คิวงานฝั่ง server เก็บด้วย SQLite (stdlib sqlite3)

ทำไม SQLite ไม่ใช่ JSON ไฟล์แบบ todo_store/org_store:
    คิวงานมี concurrency จริง (หลาย request แย่งกัน claim งาน) + ต้อง query ตาม
    status/ลำดับ — sqlite มี transaction (BEGIN IMMEDIATE) ให้ claim งานแบบ atomic
    ได้ ไม่ race เหมือน read-modify-write บนไฟล์ JSON

สไตล์เดิมของโปรเจกต์: stdlib เท่านั้น, per-project store (jobs.db ที่ project_root),
error handling ระบุ exception type, ไม่ crash โปรแกรมหลัก

Status flow: pending -> running -> done | failed

Interface:
    enqueue(project_root, name, payload=None) -> dict
    list_jobs(project_root, status=None, limit=100) -> list[dict]
    get_job(project_root, job_id) -> dict | None
    set_status(project_root, job_id, status) -> bool
    claim_next(project_root) -> dict | None     # pending -> running (atomic)
    delete_job(project_root, job_id) -> bool
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

JOBS_DB_NAME = "jobs.db"
VALID_STATUS = {"pending", "running", "done", "failed"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(project_root: Path) -> sqlite3.Connection:
    """เปิด connection ใหม่ต่อ call (สั้น ๆ) — ปลอดภัยกับ ThreadingHTTPServer
    ที่เรียกจากหลาย thread; สร้างตารางถ้ายังไม่มี"""
    conn = sqlite3.connect(str(project_root / JOBS_DB_NAME), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            payload TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.get("payload")
    if raw is not None:
        try:
            d["payload"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass  # เก็บเป็นสตริงดิบถ้า decode ไม่ได้ (ไม่ควรเกิด แต่กันพัง)
    return d


def enqueue(project_root: Path, name: str, payload: Optional[Any] = None) -> dict:
    """เพิ่มงานใหม่สถานะ pending — raise ValueError ถ้า name ว่าง/payload ไม่เป็น JSON"""
    name = (name or "").strip()
    if not name:
        raise ValueError("ต้องระบุ name ของงาน")
    try:
        payload_text = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    except (TypeError, ValueError) as e:
        raise ValueError(f"payload ต้อง serialise เป็น JSON ได้: {e}") from e

    now = _now()
    with _connect(project_root) as conn:
        cur = conn.execute(
            "INSERT INTO jobs (name, payload, status, created_at, updated_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (name, payload_text, now, now),
        )
        job_id = cur.lastrowid
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row)


def list_jobs(project_root: Path, status: Optional[str] = None, limit: int = 100) -> list:
    """คืนรายการงาน เรียงตาม id (เก่า→ใหม่) กรองตาม status ได้"""
    if status is not None and status not in VALID_STATUS:
        raise ValueError(f"status ไม่ถูกต้อง: {status}")
    with _connect(project_root) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY id LIMIT ?",
                (status, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY id LIMIT ?", (int(limit),)
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_job(project_root: Path, job_id: int) -> Optional[dict]:
    with _connect(project_root) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
    return _row_to_dict(row) if row else None


def set_status(project_root: Path, job_id: int, status: str) -> bool:
    """เปลี่ยน status ของงาน — คืน True ถ้าเจอ id, raise ValueError ถ้า status ผิด"""
    if status not in VALID_STATUS:
        raise ValueError(f"status ไม่ถูกต้อง: {status} (ต้องเป็น {sorted(VALID_STATUS)})")
    with _connect(project_root) as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), int(job_id)),
        )
        return cur.rowcount > 0


def claim_next(project_root: Path) -> Optional[dict]:
    """ดึงงาน pending ที่เก่าสุด 1 งาน เปลี่ยนเป็น running แบบ atomic (กัน worker แย่งกัน)
    คืน record ของงานที่ claim ได้ หรือ None ถ้าไม่มีงาน pending"""
    with _connect(project_root) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'pending' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
                (_now(), row["id"]),
            )
            conn.execute("COMMIT")
        except sqlite3.Error as e:
            conn.execute("ROLLBACK")
            print(f"[jobs][error] claim_next ไม่สำเร็จ: {e}")
            return None
        claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
    return _row_to_dict(claimed)


def delete_job(project_root: Path, job_id: int) -> bool:
    with _connect(project_root) as conn:
        cur = conn.execute("DELETE FROM jobs WHERE id = ?", (int(job_id),))
        return cur.rowcount > 0
