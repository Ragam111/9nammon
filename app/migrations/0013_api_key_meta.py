"""Migration 0013_api_key_meta — name + created_by on org_api_keys (LCA Console)"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

VERSION = 13
NAME = "0013_api_key_meta"


def _now_ms() -> int:
    return int(time.time() * 1000)


def apply(conn, project_root, sql_path) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version > VERSION:
        from app.db import MigrationError
        raise MigrationError(f"user_version {version} ใหม่กว่า migration {VERSION}")
    if version >= VERSION:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        sql = Path(sql_path).read_text(encoding="utf-8")
        from app.db import split_sql
        cols = {r[1] for r in conn.execute("PRAGMA table_info(org_api_keys)")}
        for statement in split_sql(sql):
            # idempotent: skip a column that already exists (partial earlier run)
            col = statement.split("ADD COLUMN", 1)[-1].split()[0] if "ADD COLUMN" in statement else ""
            if col and col in cols:
                continue
            conn.execute(statement)
        digest = hashlib.sha256(Path(sql_path).read_bytes()).hexdigest()
        conn.execute(
            "INSERT INTO schema_version(version, name, applied_at, checksum) VALUES (?,?,?,?)",
            (VERSION, NAME, _now_ms(), digest),
        )
        conn.execute(f"PRAGMA user_version={VERSION}")
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
