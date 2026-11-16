"""Migration 0010_chat_hub.

Applies ``0010_chat_hub.sql``, seeds personas from chat skills, and (only when
``CHAT_IMPORT_SAMPLES`` is explicitly set) copies dataset samples into
conversations. Sources are read, never modified.

A fresh database has user_version 0 because migrations 0001–0009 are not in
this repo. That is allowed. user_version greater than 10 is refused.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

VERSION = 10
NAME = "0010_chat_hub"
SKILL_NS = uuid.NAMESPACE_URL


class MigrationError(RuntimeError):
    pass


def _now() -> int:
    return int(time.time() * 1000)


def _has_user_tables(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
    ).fetchone()
    return row is not None


def _backup(conn, project_root: Path) -> None:
    dest_dir = project_root / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "pre-v10.db"
    out = sqlite3.connect(str(dest))
    try:
        conn.backup(out)
    finally:
        out.close()


def _provider_for_connection(project_root: Path, connection_id: str | None):
    if not connection_id:
        return None
    try:
        from app import connections
        rec = connections.get(project_root, connection_id)
    except Exception:
        return None
    if not rec:
        return None
    kind = (rec.get("kind") or "").lower()
    if kind == "ollama":
        return "ollama"
    if kind == "openai":
        return "openai_compat"
    return None


def _seed_personas(conn, project_root: Path) -> None:
    """Chat skills become personas. ``INSERT OR IGNORE`` on a stable uid."""
    try:
        from app import skills_store
        skills = skills_store.list_skills(project_root)
    except Exception:
        skills = []
    now = _now()
    for skill in skills:
        if (skill.get("mode") or "chat") != "chat":
            continue
        skill_id = skill.get("id") or ""
        uid = str(uuid.uuid5(SKILL_NS, f"lca:skill:{skill_id}"))
        params = None
        if skill.get("temperature") is not None:
            params = json.dumps({"temperature": skill.get("temperature")}, ensure_ascii=False)
        conn.execute(
            """INSERT OR IGNORE INTO personas
               (uid, name, system_prompt, provider, model, params, source_skill_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                uid,
                skill.get("name") or "skill",
                skill.get("system_prompt") or "",
                _provider_for_connection(project_root, skill.get("connection_id")),
                (skill.get("model") or None) or None,
                params,
                skill_id,
                now,
                now,
            ),
        )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('imported_from', 'skills@v10')"
    )


def _opted_in(project_root: Path) -> bool:
    try:
        from app import config_manager
        value = config_manager.get_key(project_root, "CHAT_IMPORT_SAMPLES")
    except Exception:
        return False
    return str(value or "").strip().lower() in ("1", "true", "yes")


def _import_samples(conn, project_root: Path) -> None:
    """Copy dataset.db samples. Default off. Marker prevents a second copy."""
    already = conn.execute(
        "SELECT value FROM schema_meta WHERE key='imported_samples'"
    ).fetchone()
    if already:
        return
    dataset = project_root / "dataset.db"
    if not _opted_in(project_root) or not dataset.exists():
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('imported_samples', 'samples@v10-skipped')"
        )
        return
    src = sqlite3.connect(str(dataset))
    src.row_factory = sqlite3.Row
    try:
        rows = src.execute(
            "SELECT id, prompt, response, model FROM samples ORDER BY id"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        src.close()
    now = _now()
    folder_uid = str(uuid.uuid5(SKILL_NS, "lca:folder:dataset-import"))
    conn.execute(
        """INSERT OR IGNORE INTO folders(uid, kind, name, created_at, updated_at)
           VALUES (?,?,?,?,?)""",
        (folder_uid, "project", "นำเข้าจาก dataset", now, now),
    )
    folder_id = conn.execute("SELECT id FROM folders WHERE uid=?", (folder_uid,)).fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO tags(name) VALUES ('dataset')")
    tag_id = conn.execute("SELECT id FROM tags WHERE name='dataset'").fetchone()[0]
    for sample in rows:
        cuid = str(uuid.uuid5(SKILL_NS, f"lca:sample:{sample['id']}"))
        title = (sample["prompt"] or "").strip().replace("\n", " ")[:80]
        conn.execute(
            """INSERT OR IGNORE INTO conversations(uid, folder_id, title, created_at, updated_at)
               VALUES (?,?,?,?,?)""",
            (cuid, folder_id, title, now, now),
        )
        conv_id = conn.execute("SELECT id FROM conversations WHERE uid=?", (cuid,)).fetchone()[0]
        existing = conn.execute(
            "SELECT count(*) FROM messages WHERE conversation_id=?", (conv_id,)
        ).fetchone()[0]
        if existing:
            continue
        user_uid = str(uuid.uuid5(SKILL_NS, f"lca:sample:{sample['id']}:user"))
        asst_uid = str(uuid.uuid5(SKILL_NS, f"lca:sample:{sample['id']}:assistant"))
        user_id = conn.execute(
            """INSERT INTO messages(uid, conversation_id, parent_id, role, origin, content, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (user_uid, conv_id, None, "user", "import", sample["prompt"] or "", now),
        ).lastrowid
        asst_id = conn.execute(
            """INSERT INTO messages(uid, conversation_id, parent_id, role, origin, content, model, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (asst_uid, conv_id, user_id, "assistant", "import", sample["response"] or "", sample["model"], now),
        ).lastrowid
        conn.execute(
            "UPDATE conversations SET active_leaf_id=?, updated_at=? WHERE id=?",
            (asst_id, now, conv_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO conversation_tags(conversation_id, tag_id) VALUES (?,?)",
            (conv_id, tag_id),
        )
        for mid, text, role in (
            (user_id, sample["prompt"] or "", "user"),
            (asst_id, sample["response"] or "", "assistant"),
        ):
            if text:
                conn.execute(
                    "INSERT INTO msg_fts(rowid, body) VALUES (?, lca_seg(?))",
                    (mid, text),
                )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('imported_samples', 'samples@v10')"
    )


def apply(conn, project_root, sql_path) -> None:
    project_root = Path(project_root)
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version > VERSION:
        raise MigrationError(f"user_version {version} ใหม่กว่า migration {VERSION}")
    if version >= VERSION:
        return
    if version > 0 or _has_user_tables(conn):
        _backup(conn, project_root)
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='sessions'"
        ).fetchone()
        if existing and existing[0] == "table":
            count = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
            if count:
                raise MigrationError(
                    "ตาราง sessions มีข้อมูล — ไม่แทนที่ด้วย VIEW (export ก่อน แล้วค่อยย้ายมือ)"
                )
            conn.execute("DROP TABLE sessions")
        sql = Path(sql_path).read_text(encoding="utf-8")
        from app.db import split_sql
        for statement in split_sql(sql):
            conn.execute(statement)
        _seed_personas(conn, project_root)
        _import_samples(conn, project_root)
        digest = hashlib.sha256(Path(sql_path).read_bytes()).hexdigest()
        conn.execute(
            "INSERT INTO schema_version(version, name, applied_at, checksum) VALUES (?,?,?,?)",
            (VERSION, NAME, _now(), digest),
        )
        conn.execute(f"PRAGMA user_version={VERSION}")
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
