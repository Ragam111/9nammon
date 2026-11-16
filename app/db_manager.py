"""
db_manager.py — high-level DB admin API สำหรับ central lca.db

get_db_status(project_root) → dict  (เรียกจาก GET /api/admin/db/status)
log_event(project_root, ...)        → None  (silent — ไม่ raise)
"""

from __future__ import annotations

import time
from pathlib import Path

from app.db import (
    db_path,
    code_version,
    ensure_migrated,
    list_migrations,
    read_txn,
    write_txn,
)


def get_db_status(project_root) -> dict:
    """snapshot สถานะ central DB: version, size, tables, migrations"""
    try:
        ensure_migrated(project_root)
    except Exception as exc:
        return {"status": "migration_error", "error": str(exc)}
    try:
        path = db_path(project_root)
        size_bytes = path.stat().st_size if path.exists() else 0
        with read_txn(project_root) as conn:
            db_ver = int(conn.execute("PRAGMA user_version").fetchone()[0])
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            applied = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        migs = list_migrations()
        cv = code_version()
        pending = sum(1 for n, *_ in migs if n > db_ver)
        return {
            "status": "ok" if pending == 0 else "pending",
            "db_version": db_ver,
            "code_version": cv,
            "db_size_bytes": size_bytes,
            "tables": tables,
            "migrations_applied": applied,
            "migrations_pending": pending,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def log_event(
    project_root,
    kind: str,
    message: str,
    level: str = "info",
    source: str | None = None,
    extra: str | None = None,
) -> None:
    """บันทึก 1 event ใน server_events — ล้มเหลว silent"""
    try:
        with write_txn(project_root) as conn:
            conn.execute(
                "INSERT INTO server_events(kind, level, source, message, extra, ts) "
                "VALUES (?,?,?,?,?,?)",
                (kind, level, source, message, extra, int(time.time())),
            )
    except Exception:
        pass
