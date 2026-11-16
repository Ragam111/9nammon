"""
dataset_store.py — เก็บตัวอย่างบทสนทนาไว้ทำ dataset สำหรับ fine-tune ทีหลัง (SQLite, stdlib)

ทำไมต้องมี: เครื่อง 8GB + iGPU "เทรน" โมเดลเองไม่ได้ — แต่ "เก็บข้อมูล" ได้.
เก็บคู่ (prompt, response) ที่ดี ๆ ไว้บนเครื่อง แล้วค่อย export เป็น JSONL ไป fine-tune
บน cloud GPU เช่าชั่วโมงทีหลัง (ดู docs/DATA_AND_TRAINING.md). นี่คือเฟส 1 ของ collect→train

สไตล์เดิม: stdlib เท่านั้น, per-project store (dataset.db), connection ต่อ call,
SQL parametrised, validate input, ไม่ crash โปรแกรมหลัก

⚠️ ความเป็นส่วนตัว: การเก็บบทสนทนาผู้ใช้ไปเทรนต้อง "ขอความยินยอม" ก่อน — การเก็บ
อัตโนมัติจึงปิดเป็นค่าเริ่มต้น (เปิดผ่าน config COLLECT_TRAINING_DATA) ดู server.py

Interface:
    add_sample(project_root, prompt, response, model=None, rating=None, source="manual") -> dict
    list_samples(project_root, limit=100, min_rating=None) -> list[dict]   # ใหม่สุดก่อน
    count(project_root) -> int
    delete_sample(project_root, sample_id) -> bool
    export_jsonl(project_root, fmt="messages", min_rating=None) -> str     # JSONL พร้อม fine-tune
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DATASET_DB_NAME = "dataset.db"
VALID_FORMATS = {"messages", "alpaca"}
_MAX_LEN = 20000


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(project_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(project_root / DATASET_DB_NAME), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            model TEXT,
            prompt TEXT NOT NULL,
            response TEXT NOT NULL,
            rating INTEGER,
            source TEXT
        )"""
    )
    return conn


def add_sample(project_root: Path, prompt: str, response: str,
               model: Optional[str] = None, rating=None, source: str = "manual") -> dict:
    """เก็บ 1 ตัวอย่าง — raise ValueError ถ้า prompt/response ว่างหรือยาวเกิน/rating ผิด"""
    prompt = (prompt or "").strip()
    response = (response or "").strip()
    if not prompt:
        raise ValueError("ต้องระบุ prompt")
    if not response:
        raise ValueError("ต้องระบุ response")
    if len(prompt) > _MAX_LEN or len(response) > _MAX_LEN:
        raise ValueError(f"prompt/response ยาวเกิน {_MAX_LEN} ตัวอักษร")
    if rating is not None:
        try:
            rating = int(rating)
        except (TypeError, ValueError) as e:
            raise ValueError("rating ต้องเป็นจำนวนเต็ม 1-5") from e
        if not 1 <= rating <= 5:
            raise ValueError("rating ต้องอยู่ระหว่าง 1-5")
    now = _now()
    with _connect(project_root) as conn:
        cur = conn.execute(
            "INSERT INTO samples (created_at, model, prompt, response, rating, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now, (model or "").strip() or None, prompt, response, rating,
             (source or "").strip() or None),
        )
        row = conn.execute("SELECT * FROM samples WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_samples(project_root: Path, limit: int = 100, min_rating=None) -> list:
    """คืนตัวอย่างล่าสุดก่อน กรอง rating ขั้นต่ำได้"""
    where, params = [], []
    if min_rating is not None:
        where.append("rating >= ?")
        params.append(int(min_rating))
    sql = "SELECT * FROM samples"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with _connect(project_root) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def count(project_root: Path) -> int:
    with _connect(project_root) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0])


def delete_sample(project_root: Path, sample_id: int) -> bool:
    with _connect(project_root) as conn:
        cur = conn.execute("DELETE FROM samples WHERE id = ?", (int(sample_id),))
        return cur.rowcount > 0


def export_jsonl(project_root: Path, fmt: str = "messages", min_rating=None) -> str:
    """export เป็น JSONL พร้อมป้อน fine-tune
    fmt 'messages' = {"messages":[{role:user},{role:assistant}]} (รูปแบบ chat ทั่วไป)
    fmt 'alpaca'   = {"instruction":..., "input":"", "output":...}
    เรียงเก่า→ใหม่ (ลำดับการเก็บ) เพื่อ reproducible"""
    fmt = (fmt or "messages").strip().lower()
    if fmt not in VALID_FORMATS:
        raise ValueError(f"fmt ไม่ถูกต้อง: {fmt} (ต้องเป็น {sorted(VALID_FORMATS)})")
    where, params = [], []
    if min_rating is not None:
        where.append("rating >= ?")
        params.append(int(min_rating))
    sql = "SELECT prompt, response FROM samples"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC"
    with _connect(project_root) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    lines = []
    for r in rows:
        if fmt == "messages":
            obj = {"messages": [
                {"role": "user", "content": r["prompt"]},
                {"role": "assistant", "content": r["response"]},
            ]}
        else:  # alpaca
            obj = {"instruction": r["prompt"], "input": "", "output": r["response"]}
        lines.append(json.dumps(obj, ensure_ascii=False))
    return "\n".join(lines)
