"""
finance_ledger.py — บันทึกการเงิน (record-only) ลง SQLite (stdlib sqlite3)

ทำไมต้องมี (Item I): องค์กร LCA ต้องมีร่องรอยเงินเข้า/ออก — แต่ตามเคสจริงของ user
ระบบ "บันทึกเท่านั้น ไม่โอนจริง" (ไม่เชื่อม bank API — นอกขอบเขต ดู docs/AGENT_ORG.md)
เช่น "เบิก 1500 รอหัวหน้าโอน" = 1 record direction=in status=pending → เปลี่ยนเป็น
received เมื่อได้เงินจริง (นอกระบบ) แล้ว notifier ค่อยยิงแจ้งเตือน

สไตล์เดิม: stdlib เท่านั้น, per-project store (finance.db), เปิด connection ต่อ call
(ปลอดภัยกับ ThreadingHTTPServer), SQL parametrised, validate input, ไม่ crash โปรแกรมหลัก

โมเดล:
    direction : in  (เงินเข้า เช่น เบิก/รับชำระ) | out (เงินออก เช่น จ่ายค่าบริการ)
    status    : pending (รอ) -> received (รับเข้าแล้ว, เฉพาะ in)
                             -> paid (จ่ายออกแล้ว, เฉพาะ out)
                             -> cancelled (ยกเลิก, ได้ทั้งสอง)

Interface:
    record_entry(project_root, amount, direction, note="", category="", status="pending") -> dict
    list_entries(project_root, status=None, direction=None, limit=100) -> list[dict]  # ใหม่สุดก่อน
    get_entry(project_root, entry_id) -> dict | None
    set_status(project_root, entry_id, status) -> dict | None  # คืน record ที่อัปเดต
    delete_entry(project_root, entry_id) -> bool
    summary(project_root) -> dict  # ยอดรวมแยก direction/status + balance
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

FINANCE_DB_NAME = "finance.db"
VALID_DIRECTIONS = {"in", "out"}
VALID_STATUSES = {"pending", "received", "paid", "cancelled"}
# status ปลายทางที่อนุญาตต่อ direction (นอกจาก cancelled ที่ได้ทั้งคู่)
_SETTLED_BY_DIRECTION = {"in": "received", "out": "paid"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(project_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(project_root / FINANCE_DB_NAME), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            amount REAL NOT NULL,
            direction TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            category TEXT,
            note TEXT
        )"""
    )
    return conn


def _coerce_amount(amount) -> float:
    try:
        value = float(amount)
    except (TypeError, ValueError) as e:
        raise ValueError(f"amount ต้องเป็นตัวเลข: {amount!r}") from e
    if value <= 0:
        raise ValueError("amount ต้องมากกว่า 0 (บันทึกทิศทางเข้า/ออกด้วย direction ไม่ใช่ค่าติดลบ)")
    return value


def record_entry(
    project_root: Path,
    amount,
    direction: str,
    note: str = "",
    category: str = "",
    status: str = "pending",
) -> dict:
    """บันทึกรายการเงิน 1 รายการ — raise ValueError ถ้า input ผิด"""
    value = _coerce_amount(amount)
    direction = (direction or "").strip().lower()
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction ไม่ถูกต้อง: {direction} (ต้องเป็น {sorted(VALID_DIRECTIONS)})")
    status = (status or "pending").strip().lower()
    _validate_status_for_direction(status, direction)
    now = _now()
    with _connect(project_root) as conn:
        cur = conn.execute(
            "INSERT INTO ledger (created_at, updated_at, amount, direction, status, category, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, now, value, direction, status,
             (category or "").strip() or None, (note or "").strip() or None),
        )
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def _validate_status_for_direction(status: str, direction: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"status ไม่ถูกต้อง: {status} (ต้องเป็น {sorted(VALID_STATUSES)})")
    settled = _SETTLED_BY_DIRECTION[direction]
    # เงินเข้าห้าม paid, เงินออกห้าม received — กันบันทึกสถานะที่ขัดทิศทาง
    wrong = {"received", "paid"} - {settled}
    if status in wrong:
        raise ValueError(
            f"status '{status}' ใช้กับ direction '{direction}' ไม่ได้ "
            f"(direction={direction} ใช้ได้: pending/{settled}/cancelled)"
        )


def list_entries(
    project_root: Path,
    status: Optional[str] = None,
    direction: Optional[str] = None,
    limit: int = 100,
) -> list:
    """คืนรายการล่าสุดก่อน กรองตาม status / direction ได้"""
    where, params = [], []
    if status is not None:
        status = status.strip().lower()
        if status not in VALID_STATUSES:
            raise ValueError(f"status ไม่ถูกต้อง: {status}")
        where.append("status = ?")
        params.append(status)
    if direction is not None:
        direction = direction.strip().lower()
        if direction not in VALID_DIRECTIONS:
            raise ValueError(f"direction ไม่ถูกต้อง: {direction}")
        where.append("direction = ?")
        params.append(direction)
    sql = "SELECT * FROM ledger"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with _connect(project_root) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def get_entry(project_root: Path, entry_id: int) -> Optional[dict]:
    with _connect(project_root) as conn:
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (int(entry_id),)).fetchone()
    return dict(row) if row else None


def set_status(project_root: Path, entry_id: int, status: str) -> Optional[dict]:
    """เปลี่ยนสถานะรายการ — คืน record ที่อัปเดต หรือ None ถ้าไม่เจอ id
    validate status ให้สอดคล้อง direction ของรายการนั้น (เงินเข้าเป็น received ไม่ใช่ paid)"""
    status = (status or "").strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"status ไม่ถูกต้อง: {status} (ต้องเป็น {sorted(VALID_STATUSES)})")
    with _connect(project_root) as conn:
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (int(entry_id),)).fetchone()
        if row is None:
            return None
        _validate_status_for_direction(status, row["direction"])
        conn.execute(
            "UPDATE ledger SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), int(entry_id)),
        )
        updated = conn.execute("SELECT * FROM ledger WHERE id = ?", (int(entry_id),)).fetchone()
    return dict(updated)


def delete_entry(project_root: Path, entry_id: int) -> bool:
    with _connect(project_root) as conn:
        cur = conn.execute("DELETE FROM ledger WHERE id = ?", (int(entry_id),))
        return cur.rowcount > 0


def summary(project_root: Path) -> dict:
    """สรุปยอด: เงินเข้าที่รับแล้ว (received) - เงินออกที่จ่ายแล้ว (paid) = balance
    พร้อมยอดที่ยังค้าง (pending) แยกทิศทาง เพื่อให้ dashboard แสดงได้ทันที"""
    with _connect(project_root) as conn:
        rows = conn.execute(
            "SELECT direction, status, COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total "
            "FROM ledger GROUP BY direction, status"
        ).fetchall()
    agg = {
        "received_in": 0.0, "paid_out": 0.0,
        "pending_in": 0.0, "pending_out": 0.0,
        "cancelled": 0.0, "count": 0,
    }
    for r in rows:
        agg["count"] += r["n"]
        total = float(r["total"])
        key = None
        if r["status"] == "received" and r["direction"] == "in":
            key = "received_in"
        elif r["status"] == "paid" and r["direction"] == "out":
            key = "paid_out"
        elif r["status"] == "pending" and r["direction"] == "in":
            key = "pending_in"
        elif r["status"] == "pending" and r["direction"] == "out":
            key = "pending_out"
        elif r["status"] == "cancelled":
            key = "cancelled"
        if key:
            agg[key] += total
    agg["balance"] = round(agg["received_in"] - agg["paid_out"], 2)
    for k in ("received_in", "paid_out", "pending_in", "pending_out", "cancelled"):
        agg[k] = round(agg[k], 2)
    return agg
