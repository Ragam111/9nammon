"""
stats_store.py — บันทึกสถิติ request/response ต่อ endpoint (SQLite, stdlib only)

record() เรียกทุกครั้งที่ _send_json ตอบ — ไม่ block request จริง (try/except ทั้งหมด)
get_stats() เรียกจาก GET /api/admin/stats (ADMIN+) — คืน snapshot ล่าสุด
"""

import sqlite3
from pathlib import Path

_DB_NAME = "stats.db"


def _connect(project_root: Path) -> sqlite3.Connection:
    db = project_root / _DB_NAME
    conn = sqlite3.connect(str(db), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS request_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT    NOT NULL,
            status   INTEGER NOT NULL,
            ts       INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ep ON request_log(endpoint)")
    conn.commit()
    return conn


def record(project_root: Path, endpoint: str, status: int) -> None:
    """บันทึก 1 request — ล้มเหลว silent (ห้าม raise ออกไปหยุด request จริง)"""
    try:
        conn = _connect(project_root)
        conn.execute(
            "INSERT INTO request_log(endpoint, status) VALUES (?, ?)",
            (endpoint, int(status)),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_stats(project_root: Path) -> dict:
    """snapshot สถิติ: total, errors, error_rate, last_24h, by_endpoint (top 20)"""
    try:
        conn = _connect(project_root)
        total = conn.execute("SELECT COUNT(*) FROM request_log").fetchone()[0]
        errors = conn.execute(
            "SELECT COUNT(*) FROM request_log WHERE status >= 400"
        ).fetchone()[0]
        by_endpoint = [
            {
                "endpoint": row["endpoint"],
                "count": row["cnt"],
                "errors": row["err"],
            }
            for row in conn.execute("""
                SELECT endpoint,
                       COUNT(*) AS cnt,
                       SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS err
                FROM request_log
                GROUP BY endpoint
                ORDER BY cnt DESC
                LIMIT 20
            """).fetchall()
        ]
        last_24h = conn.execute(
            "SELECT COUNT(*) FROM request_log "
            "WHERE ts >= CAST(strftime('%s','now') AS INTEGER) - 86400"
        ).fetchone()[0]
        conn.close()
        return {
            "total_requests": total,
            "total_errors": errors,
            "error_rate": round(errors / total, 4) if total else 0.0,
            "last_24h": last_24h,
            "by_endpoint": by_endpoint,
        }
    except Exception as exc:
        return {"error": str(exc)}
