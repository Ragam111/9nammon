"""
usage_store.py — บันทึกการใช้งาน API ต่อ key ลง SQLite เพื่อ metering/สรุปค่าใช้จ่าย (stdlib)

ทำไมต้องมี (Item H): org_store เก็บแค่ตัวนับรายวัน (used_today/usage_date) ที่ "รีเซ็ตทุกวัน"
— ดูย้อนหลังไม่ได้ว่าใครใช้ไปเท่าไรเดือนนี้ หรือ tier paid สร้างค่าใช้จ่ายรวมเท่าไร
โมดูลนี้บันทึกทุก event การใช้งานที่สำเร็จ (append-only) ลง usage.db จึง query ย้อนหลัง
+ สรุปต่อ key / ต่อ tier ได้ ซึ่งเป็นฐานของการคิดเงิน

ขอบเขต (ตาม backlog H): **บันทึก + สรุปเท่านั้น ไม่เชื่อม payment gateway จริง**
ราคา/หน่วย (TIER_UNIT_PRICE) เป็นค่า "ตั้งต้นสำหรับประมาณการ" ใน docs/USAGE_BILLING.md
ไม่ใช่การเรียกเก็บเงินจริง

สไตล์เดิม: stdlib เท่านั้น, per-project store (usage.db), connection ต่อ call
(ปลอดภัยกับ ThreadingHTTPServer), SQL parametrised, ไม่ crash โปรแกรมหลัก

Interface:
    record_usage(project_root, key_id, owner, tier, endpoint="chat", units=1) -> dict
    list_usage(project_root, key_id=None, limit=100) -> list[dict]   # ใหม่สุดก่อน
    summary(project_root) -> dict   # รวม units+cost ต่อ tier/ต่อ key
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

USAGE_DB_NAME = "usage.db"

# ราคาต่อ 1 หน่วยการใช้งาน (เช่น 1 request) แยกตาม tier — หน่วยเป็น "บาท" (ประมาณการ)
# หมายเหตุ: เป็นค่าตั้งต้นสำหรับประมาณการเท่านั้น ไม่ใช่การเรียกเก็บเงินจริง
TIER_UNIT_PRICE = {
    "free": 0.0,
    "paid": 0.10,
}
_DEFAULT_PRICE = 0.0  # tier ที่ไม่รู้จัก = ไม่คิดเงิน (ปลอดภัยไว้ก่อน)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(project_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(project_root / USAGE_DB_NAME), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            used_at TEXT NOT NULL,
            key_id TEXT,
            owner TEXT,
            tier TEXT,
            endpoint TEXT,
            units INTEGER NOT NULL DEFAULT 1
        )"""
    )
    return conn


def _unit_price(tier: Optional[str]) -> float:
    return TIER_UNIT_PRICE.get(tier or "", _DEFAULT_PRICE)


def record_usage(
    project_root: Path,
    key_id: Optional[str],
    owner: Optional[str],
    tier: Optional[str],
    endpoint: str = "chat",
    units: int = 1,
) -> dict:
    """บันทึก 1 event การใช้งาน (append-only) — raise ValueError ถ้า units ไม่ใช่จำนวนบวก"""
    try:
        units = int(units)
    except (TypeError, ValueError) as e:
        raise ValueError(f"units ต้องเป็นจำนวนเต็ม: {units!r}") from e
    if units <= 0:
        raise ValueError("units ต้องมากกว่า 0")
    now = _now()
    with _connect(project_root) as conn:
        cur = conn.execute(
            "INSERT INTO usage (used_at, key_id, owner, tier, endpoint, units) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now, key_id, owner, (tier or None), (endpoint or "").strip() or None, units),
        )
        row = conn.execute("SELECT * FROM usage WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_usage(project_root: Path, key_id: Optional[str] = None, limit: int = 100) -> list:
    """คืน event ล่าสุดก่อน กรองตาม key_id ได้"""
    with _connect(project_root) as conn:
        if key_id:
            rows = conn.execute(
                "SELECT * FROM usage WHERE key_id = ? ORDER BY id DESC LIMIT ?",
                (key_id, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM usage ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
    return [dict(r) for r in rows]


def summary(project_root: Path) -> dict:
    """สรุปรวมการใช้งาน: units+cost รวม, แยกตาม tier, และแยกต่อ key
    cost = units * TIER_UNIT_PRICE[tier] (ประมาณการ ไม่ใช่เรียกเก็บจริง)"""
    with _connect(project_root) as conn:
        by_tier_rows = conn.execute(
            "SELECT tier, COALESCE(SUM(units), 0) AS units, COUNT(*) AS events "
            "FROM usage GROUP BY tier"
        ).fetchall()
        by_key_rows = conn.execute(
            "SELECT key_id, owner, tier, COALESCE(SUM(units), 0) AS units, COUNT(*) AS events "
            "FROM usage GROUP BY key_id, owner, tier ORDER BY units DESC"
        ).fetchall()

    by_tier, total_units, total_cost = {}, 0, 0.0
    for r in by_tier_rows:
        tier = r["tier"] or "unknown"
        units = int(r["units"])
        cost = round(units * _unit_price(r["tier"]), 2)
        by_tier[tier] = {"units": units, "events": int(r["events"]),
                         "unit_price": _unit_price(r["tier"]), "cost": cost}
        total_units += units
        total_cost += cost

    by_key = []
    for r in by_key_rows:
        units = int(r["units"])
        by_key.append({
            "key_id": r["key_id"],
            "owner": r["owner"],
            "tier": r["tier"],
            "units": units,
            "events": int(r["events"]),
            "cost": round(units * _unit_price(r["tier"]), 2),
        })

    return {
        "total_units": total_units,
        "total_cost": round(total_cost, 2),
        "currency": "THB (ประมาณการ — ไม่ใช่การเรียกเก็บจริง)",
        "by_tier": by_tier,
        "by_key": by_key,
    }
