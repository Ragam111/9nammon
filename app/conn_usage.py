"""conn_usage.py — นับการใช้งานต่อ "สมอง" (connection): requests + tokens + ค่าใช้จ่ายประมาณการ

โจทย์ (ตามที่ user สั่ง): อยากได้ Observability แบบ TokenMe — เห็นว่าแต่ละ connection ถูกใช้
กี่ครั้ง กิน token เท่าไร คิดเป็นเงินประมาณเท่าไร. ต่างจาก usage_store เดิม (นับ "request ต่อ
API key" ไว้คิดบิลของ LCA เอง) — อันนี้นับ "token ต่อสมองภายนอก" ซึ่งเป็นคนละมิติ.

ซื่อตรง (9arm): token ที่นับเป็น **ค่าประมาณ** (heuristic ~chars/4) ไม่ใช่ตัวเลขที่ provider
เรียกเก็บจริง — เพราะ backend ปัจจุบันคืนแค่ข้อความ (ทิ้ง field usage ของ API) และ stream
ส่วนใหญ่ไม่ส่ง usage กลับ. ใช้เทียบปริมาณ/ประมาณค่าใช้จ่ายได้ ไม่ใช่บิลจริง. ถ้าวันหลัง
backend คืน usage แท้ ก็ส่งเข้า record_usage() ตรง ๆ แทน estimate ได้.

stdlib ล้วน (sqlite3), per-project store (conn_usage.db — เข้า .gitignore ผ่าน *.db),
connection ต่อ call (ปลอดภัยกับ ThreadingHTTPServer), degrade ไม่ล้มโปรแกรมหลัก.

Interface:
    estimate_tokens(text) -> int
    estimate_messages_tokens(messages) -> int
    record_usage(project_root, conn_id, conn_name, input_tokens, output_tokens, endpoint="chat") -> None
    summary(project_root) -> dict   # ต่อ connection + รวมทั้งหมด
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DB_NAME = "conn_usage.db"
# ราคาประมาณการต่อ 1,000 token (USD) — ค่าตั้งต้นหยาบ ๆ ไว้โชว์คอลัมน์ cost แบบ TokenMe
# ไม่ใช่ราคาจริงของ provider (แต่ละเจ้า/โมเดลต่างกัน) — ดู docs/CONSOLE_PLATFORM.md
PRICE_PER_1K_TOKENS = 0.002
_CHARS_PER_TOKEN = 4   # heuristic มาตรฐานคร่าว ๆ (อังกฤษ ~4 ตัวอักษร/token)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(project_root) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(project_root) / DB_NAME), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS conn_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            used_at TEXT NOT NULL,
            conn_id TEXT,
            conn_name TEXT,
            endpoint TEXT,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0
        )"""
    )
    return conn


def estimate_tokens(text: str) -> int:
    """ประมาณจำนวน token จากความยาวข้อความ (~chars/4). ว่าง → 0, มีเนื้อ → อย่างน้อย 1"""
    if not text:
        return 0
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


def estimate_messages_tokens(messages) -> int:
    """ประมาณ token รวมของ messages (รวม content ทุก role)"""
    total = 0
    for m in (messages or []):
        if isinstance(m, dict):
            total += estimate_tokens(str(m.get("content", "")))
    return total


def record_usage(project_root, conn_id: str, conn_name: str, input_tokens: int,
                 output_tokens: int, endpoint: str = "chat") -> None:
    """บันทึก 1 ครั้งการใช้งานของ connection. degrade: error ใด ๆ ไม่ล้ม chat (แค่ไม่นับ)"""
    try:
        conn = _connect(project_root)
        with conn:
            conn.execute(
                "INSERT INTO conn_usage (used_at, conn_id, conn_name, endpoint, input_tokens, output_tokens)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (_now(), conn_id or "", conn_name or "", endpoint,
                 int(input_tokens or 0), int(output_tokens or 0)),
            )
        conn.close()
    except sqlite3.Error as e:   # pragma: no cover - metering ต้องไม่ทำ chat พัง
        print(f"[conn_usage][warn] บันทึก usage ไม่ได้: {e}")


def _cost(tokens: int) -> float:
    return round(tokens / 1000.0 * PRICE_PER_1K_TOKENS, 6)


def summary(project_root) -> dict:
    """สรุปต่อ connection + รวมทั้งหมด (requests/input/output/total tokens + cost ประมาณการ)"""
    try:
        conn = _connect(project_root)
        rows = conn.execute(
            """SELECT conn_id, conn_name, COUNT(*) AS requests,
                      COALESCE(SUM(input_tokens),0) AS input_tokens,
                      COALESCE(SUM(output_tokens),0) AS output_tokens
               FROM conn_usage GROUP BY conn_id ORDER BY requests DESC"""
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:   # pragma: no cover
        print(f"[conn_usage][warn] อ่าน summary ไม่ได้: {e}")
        return {"connections": [], "totals": {"requests": 0, "input_tokens": 0,
                                              "output_tokens": 0, "total_tokens": 0, "est_cost": 0.0}}
    per = []
    t_req = t_in = t_out = 0
    for r in rows:
        tin, tout = int(r["input_tokens"]), int(r["output_tokens"])
        total = tin + tout
        per.append({
            "conn_id": r["conn_id"], "conn_name": r["conn_name"],
            "requests": int(r["requests"]), "input_tokens": tin, "output_tokens": tout,
            "total_tokens": total, "est_cost": _cost(total),
        })
        t_req += int(r["requests"]); t_in += tin; t_out += tout
    return {
        "connections": per,
        "totals": {"requests": t_req, "input_tokens": t_in, "output_tokens": t_out,
                   "total_tokens": t_in + t_out, "est_cost": _cost(t_in + t_out)},
        "price_per_1k_tokens": PRICE_PER_1K_TOKENS,
    }
