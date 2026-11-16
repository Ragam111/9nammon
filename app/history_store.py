"""
history_store.py — เก็บประวัติ monitor snapshot + error log ลง SQLite (stdlib sqlite3)

ทำไมต้องมี (Item E): monitor snapshot เดี่ยว ๆ บอกแค่ "ตอนนี้" — เก็บลง db ทำให้
query ย้อนหลังได้ (เช่น RAM พุ่งตอนไหน, error เกิดช่วงไหน) ซึ่งเป็นฐานของ dashboard
แนวโน้ม + การวิเคราะห์คอขวดข้ามเวลา

สไตล์เดิม: stdlib เท่านั้น, per-project store (history.db), เปิด connection ต่อ call
(ปลอดภัยกับ ThreadingHTTPServer), SQL แบบ parametrised, ไม่ crash โปรแกรมหลัก

Interface:
    record_snapshot(project_root, report) -> dict          # report = dict จาก analyzer (_report_to_dict)
    list_snapshots(project_root, limit=50) -> list[dict]    # ใหม่สุดก่อน
    log_error(project_root, level, source, message) -> dict
    list_errors(project_root, level=None, limit=100) -> list[dict]   # ใหม่สุดก่อน
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

HISTORY_DB_NAME = "history.db"
VALID_LEVELS = {"debug", "info", "warning", "error", "critical"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(project_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(project_root / HISTORY_DB_NAME), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            verdict TEXT,
            worst_severity TEXT,
            cpu_percent REAL,
            mem_percent REAL,
            raw TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at TEXT NOT NULL,
            level TEXT NOT NULL,
            source TEXT,
            message TEXT NOT NULL
        )"""
    )
    return conn


# ---------- snapshots ----------

def record_snapshot(project_root: Path, report: dict) -> dict:
    """เก็บ monitor report (dict จาก analyzer) ลง db — ดึง cpu/mem มาเป็นคอลัมน์ query ง่าย
    เก็บ raw ทั้ง report ไว้ด้วย; defensive กับ dict รูปแบบไม่ครบ"""
    if not isinstance(report, dict):
        raise ValueError("report ต้องเป็น dict")
    snap = report.get("snapshot") or {}
    cpu = (snap.get("cpu") or {}).get("percent")
    mem = (snap.get("memory") or {}).get("percent")
    now = _now()
    with _connect(project_root) as conn:
        cur = conn.execute(
            "INSERT INTO snapshots (recorded_at, verdict, worst_severity, cpu_percent, mem_percent, raw) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now, report.get("verdict"), report.get("worst_severity"),
             cpu, mem, json.dumps(report, ensure_ascii=False)),
        )
        row = conn.execute("SELECT * FROM snapshots WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _snap_row(row)


def list_snapshots(project_root: Path, limit: int = 50) -> list:
    """คืน snapshot ล่าสุดก่อน (ไม่รวม raw json เพื่อไม่ให้ payload ใหญ่)"""
    with _connect(project_root) as conn:
        rows = conn.execute(
            "SELECT id, recorded_at, verdict, worst_severity, cpu_percent, mem_percent "
            "FROM snapshots ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def _snap_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("raw"):
        try:
            d["raw"] = json.loads(d["raw"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


# ---------- error log ----------

def log_error(project_root: Path, level: str, source: str, message: str) -> dict:
    """บันทึก 1 error entry — raise ValueError ถ้า level ผิด/message ว่าง"""
    level = (level or "").strip().lower()
    if level not in VALID_LEVELS:
        raise ValueError(f"level ไม่ถูกต้อง: {level} (ต้องเป็น {sorted(VALID_LEVELS)})")
    message = (message or "").strip()
    if not message:
        raise ValueError("ต้องระบุ message")
    now = _now()
    with _connect(project_root) as conn:
        cur = conn.execute(
            "INSERT INTO error_log (logged_at, level, source, message) VALUES (?, ?, ?, ?)",
            (now, level, (source or "").strip() or None, message),
        )
        row = conn.execute("SELECT * FROM error_log WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_errors(project_root: Path, level: Optional[str] = None, limit: int = 100) -> list:
    """คืน error ล่าสุดก่อน กรองตาม level ได้"""
    if level is not None:
        level = level.strip().lower()
        if level not in VALID_LEVELS:
            raise ValueError(f"level ไม่ถูกต้อง: {level}")
    with _connect(project_root) as conn:
        if level:
            rows = conn.execute(
                "SELECT * FROM error_log WHERE level = ? ORDER BY id DESC LIMIT ?",
                (level, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM error_log ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
    return [dict(r) for r in rows]
