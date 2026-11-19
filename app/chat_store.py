"""Conversation tree stored in ``data/lca.db``.

Messages are immutable once they leave ``streaming``. Edit, regenerate, branch,
and compare insert a new sibling. ``conversations.active_leaf_id`` is the tip
of the branch on screen. ``messages.last_child_id`` remembers which child was
open at a fork (NULL means the newest child).

Full-text rows are written by the application, not by triggers, and only for
final user/assistant messages.
"""

from __future__ import annotations

import json
import os
import time
import uuid

from app import db
from app.chat_search import fts_query, is_single_thai_char, like_pattern, snippet


class ChatStoreError(ValueError):
    """Bad id, bad tree, or a conversation the caller asked for is missing."""


def now_ms() -> int:
    return int(time.time() * 1000)


def new_uid() -> str:
    """Time-ordered UUID (version 7 layout) so exports sort by creation."""
    unix_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    raw = bytearray(unix_ms.to_bytes(6, "big"))
    raw += os.urandom(10)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    hexed = raw.hex()
    return f"{hexed[:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:]}"


def _row(row):
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _as_int(value, name: str):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ChatStoreError(f"{name} ต้องเป็นตัวเลข")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ChatStoreError(f"{name} ต้องเป็นตัวเลข") from exc


def write_txn(project_root):
    return db.write_txn(project_root)


def read_txn(project_root):
    return db.read_txn(project_root)


# --- folders, personas, conversations ---------------------------------------

def create_persona(conn, *, name: str, system_prompt: str = "", provider=None, model=None, params=None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ChatStoreError("ต้องระบุชื่อ persona")
    now = now_ms()
    if isinstance(params, dict):
        params = json.dumps(params, ensure_ascii=False)
    cur = conn.execute(
        """INSERT INTO personas(uid, name, system_prompt, provider, model, params, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (new_uid(), name, system_prompt or "", provider, model, params, now, now),
    )
    return _row(conn.execute("SELECT * FROM personas WHERE id=?", (cur.lastrowid,)).fetchone())


def list_personas(conn) -> list:
    return [_row(r) for r in conn.execute(
        "SELECT * FROM personas WHERE archived=0 ORDER BY name"
    )]


def create_folder(conn, *, name: str, kind: str = "folder", parent_id=None, instructions=None, persona_id=None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ChatStoreError("ต้องระบุชื่อโฟลเดอร์")
    if kind not in ("folder", "project"):
        raise ChatStoreError("kind ต้องเป็น folder หรือ project")
    parent_id = _as_int(parent_id, "parent_id")
    persona_id = _as_int(persona_id, "persona_id")
    now = now_ms()
    cur = conn.execute(
        """INSERT INTO folders(uid, parent_id, kind, name, instructions, persona_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (new_uid(), parent_id, kind, name, instructions, persona_id, now, now),
    )
    return _row(conn.execute("SELECT * FROM folders WHERE id=?", (cur.lastrowid,)).fetchone())


def folder_tree(conn) -> list:
    rows = conn.execute(
        """WITH RECURSIVE tree(id, name, kind, depth, path, parent_id) AS (
             SELECT id, name, kind, 0, printf('%08d', sort), parent_id FROM folders WHERE parent_id IS NULL
             UNION ALL
             SELECT f.id, f.name, f.kind, t.depth + 1, t.path || '/' || printf('%08d', f.sort), f.parent_id
             FROM folders f JOIN tree t ON f.parent_id = t.id)
           SELECT t.id, t.name, t.kind, t.depth, t.parent_id,
                  (SELECT count(*) FROM conversations c
                   WHERE c.folder_id = t.id AND c.archived = 0) AS n
           FROM tree t ORDER BY t.path"""
    )
    return [_row(r) for r in rows]


def create_conversation(conn, *, title: str = "", folder_id=None, persona_id=None,
                        system_prompt=None, owner=None) -> dict:
    now = now_ms()
    cur = conn.execute(
        """INSERT INTO conversations(uid, folder_id, persona_id, owner, title, system_prompt, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            new_uid(),
            _as_int(folder_id, "folder_id"),
            _as_int(persona_id, "persona_id"),
            owner,
            (title or "").strip(),
            system_prompt,
            now,
            now,
        ),
    )
    return get_conversation(conn, cur.lastrowid)


def get_conversation(conn, key) -> dict:
    row = _resolve_conversation(conn, key)
    return _row(row)


def _resolve_conversation(conn, key):
    if key is None or key == "":
        raise ChatStoreError("ต้องระบุการสนทนา")
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (int(key),)).fetchone()
        if row:
            return row
    if isinstance(key, str):
        row = conn.execute("SELECT * FROM conversations WHERE uid=?", (key,)).fetchone()
        if row:
            return row
    raise ChatStoreError("ไม่พบการสนทนา")


def list_conversations(conn, *, folder_id="all", limit: int = 50) -> list:
    limit = max(1, min(int(limit or 50), 50))
    if folder_id == "all" or folder_id is None:
        rows = conn.execute(
            """SELECT id, uid, title, folder_id, pinned, archived, updated_at, active_leaf_id, owner
               FROM conversations WHERE archived=0
               ORDER BY pinned DESC, updated_at DESC LIMIT ?""",
            (limit,),
        )
    else:
        fid = None if folder_id in ("", "root") else _as_int(folder_id, "folder_id")
        rows = conn.execute(
            """SELECT id, uid, title, folder_id, pinned, archived, updated_at, active_leaf_id, owner
               FROM conversations
               WHERE folder_id IS ? AND archived=0
               ORDER BY pinned DESC, updated_at DESC LIMIT ?""",
            (fid, limit),
        )
    return [_row(r) for r in rows]


def update_conversation(conn, key, **fields) -> dict:
    row = _resolve_conversation(conn, key)
    allowed = {}
    if "title" in fields and fields["title"] is not None:
        allowed["title"] = str(fields["title"]).strip()
    if "system_prompt" in fields:
        allowed["system_prompt"] = fields["system_prompt"]
    if "folder_id" in fields:
        allowed["folder_id"] = _as_int(fields["folder_id"], "folder_id")
    if "persona_id" in fields:
        allowed["persona_id"] = _as_int(fields["persona_id"], "persona_id")
    if "pinned" in fields:
        allowed["pinned"] = 1 if fields["pinned"] else 0
    if "archived" in fields:
        allowed["archived"] = 1 if fields["archived"] else 0
    if not allowed:
        return _row(row)
    allowed["updated_at"] = now_ms()
    sets = ", ".join(f"{col}=?" for col in allowed)
    conn.execute(f"UPDATE conversations SET {sets} WHERE id=?", (*allowed.values(), row["id"]))
    return get_conversation(conn, row["id"])


def effective_system(conn, conversation_id: int) -> str:
    row = conn.execute(
        """SELECT COALESCE(c.system_prompt, pc.system_prompt, pf.system_prompt, '')
                  || CASE WHEN f.instructions IS NOT NULL AND f.instructions != ''
                          THEN char(10) || f.instructions ELSE '' END AS system_prompt
           FROM conversations c
           LEFT JOIN folders f ON f.id = c.folder_id
           LEFT JOIN personas pc ON pc.id = c.persona_id
           LEFT JOIN personas pf ON pf.id = f.persona_id
           WHERE c.id=?""",
        (conversation_id,),
    ).fetchone()
    if row is None:
        raise ChatStoreError("ไม่พบการสนทนา")
    return row["system_prompt"] or ""


# --- messages ---------------------------------------------------------------

def _index_message(conn, message_id: int, role: str, status: str, content: str) -> None:
    if role in ("user", "assistant") and status != "streaming" and content:
        conn.execute(
            "INSERT INTO msg_fts(rowid, body) VALUES (?, lca_seg(?))",
            (message_id, content),
        )


def insert_message(conn, conversation_id: int, *, role: str, content: str = "", parent_id=None,
                   origin=None, source_id=None, provider=None, model=None, connection_id=None,
                   status: str = "ok", compare_id=None, extra=None, tokens_in=None, tokens_out=None,
                   tokens_est: int = 0, latency_ms=None, created_at=None) -> dict:
    if role not in ("system", "user", "assistant", "tool"):
        raise ChatStoreError("role ไม่ถูกต้อง")
    if status not in ("ok", "streaming", "error", "stopped"):
        raise ChatStoreError("status ไม่ถูกต้อง")
    if origin is not None and origin not in ("edit", "regen", "branch", "compare", "import"):
        raise ChatStoreError("origin ไม่ถูกต้อง")
    conversation = conn.execute(
        "SELECT id FROM conversations WHERE id=?", (conversation_id,)
    ).fetchone()
    if conversation is None:
        raise ChatStoreError("ไม่พบการสนทนา")
    parent_id = _as_int(parent_id, "parent_id")
    if parent_id is not None:
        parent = conn.execute(
            "SELECT conversation_id FROM messages WHERE id=?", (parent_id,)
        ).fetchone()
        if parent is None or parent["conversation_id"] != conversation_id:
            raise ChatStoreError("parent ไม่อยู่ในการสนทนานี้")
    now = created_at or now_ms()
    if extra is not None and not isinstance(extra, str):
        extra = json.dumps(extra, ensure_ascii=False)
    cur = conn.execute(
        """INSERT INTO messages(
             uid, conversation_id, parent_id, role, origin, source_id, compare_id, content,
             provider, model, connection_id, status, tokens_in, tokens_out, tokens_est,
             latency_ms, extra, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            new_uid(), conversation_id, parent_id, role, origin,
            _as_int(source_id, "source_id"), _as_int(compare_id, "compare_id"),
            content or "", provider, model, connection_id, status,
            tokens_in, tokens_out, int(tokens_est or 0), latency_ms, extra, now,
        ),
    )
    message_id = cur.lastrowid
    if parent_id is not None:
        conn.execute("UPDATE messages SET last_child_id=? WHERE id=?", (message_id, parent_id))
    if role == "user" and (content or "").strip():
        title = " ".join((content or "").strip().split())[:80]
        conn.execute(
            """UPDATE conversations
               SET active_leaf_id=?, updated_at=?,
                   title=CASE WHEN title IS NULL OR title='' THEN ? ELSE title END
               WHERE id=?""",
            (message_id, now, title, conversation_id),
        )
    else:
        conn.execute(
            "UPDATE conversations SET active_leaf_id=?, updated_at=? WHERE id=?",
            (message_id, now, conversation_id),
        )
    _index_message(conn, message_id, role, status, content or "")
    return get_message(conn, message_id)


def get_message(conn, message_id: int) -> dict:
    row = conn.execute("SELECT * FROM messages WHERE id=?", (int(message_id),)).fetchone()
    if row is None:
        raise ChatStoreError("ไม่พบข้อความ")
    return _row(row)


def touch_stream(conn, message_id: int, content: str) -> None:
    conn.execute(
        "UPDATE messages SET content=? WHERE id=? AND status='streaming'",
        (content or "", int(message_id)),
    )


def finalize_message(conn, message_id: int, *, content: str, status: str, tokens_in=None,
                     tokens_out=None, tokens_est: int = 0, latency_ms=None, extra=None,
                     provider=None, model=None) -> dict:
    if status not in ("ok", "error", "stopped"):
        raise ChatStoreError("สถานะปิดข้อความไม่ถูกต้อง")
    row = conn.execute("SELECT * FROM messages WHERE id=?", (int(message_id),)).fetchone()
    if row is None:
        raise ChatStoreError("ไม่พบข้อความ")
    if row["status"] != "streaming":
        raise ChatStoreError("ข้อความนี้ปิดไปแล้ว")
    if extra is not None and not isinstance(extra, str):
        extra = json.dumps(extra, ensure_ascii=False)
    conn.execute(
        """UPDATE messages
           SET content=?, status=?, tokens_in=?, tokens_out=?, tokens_est=?, latency_ms=?,
               extra=?, provider=COALESCE(?, provider), model=COALESCE(?, model)
           WHERE id=?""",
        (
            content or "", status, tokens_in, tokens_out, int(tokens_est or 0), latency_ms,
            extra, provider, model, int(message_id),
        ),
    )
    _index_message(conn, int(message_id), row["role"], status, content or "")
    conn.execute(
        "UPDATE conversations SET updated_at=? WHERE id=?",
        (now_ms(), row["conversation_id"]),
    )
    return get_message(conn, message_id)


def active_path(conn, conversation_id: int) -> list:
    rows = conn.execute(
        """WITH RECURSIVE path(id, depth) AS (
             SELECT active_leaf_id, 0 FROM conversations WHERE id=?
             UNION ALL
             SELECT m.parent_id, p.depth + 1 FROM messages m
             JOIN path p ON m.id = p.id WHERE m.parent_id IS NOT NULL)
           SELECT m.*,
             (SELECT count(*) FROM messages s
              WHERE s.parent_id IS m.parent_id AND s.conversation_id = m.conversation_id
                AND s.id <= m.id) AS ver,
             (SELECT count(*) FROM messages s
              WHERE s.parent_id IS m.parent_id AND s.conversation_id = m.conversation_id) AS n_ver
           FROM path JOIN messages m ON m.id = path.id
           ORDER BY path.depth DESC""",
        (int(conversation_id),),
    ).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["siblings"] = siblings(conn, item["id"])
        if item.get("compare_id"):
            item["compare"] = compare_set(conn, item["compare_id"])
        out.append(item)
    return out


def siblings(conn, message_id: int) -> list:
    rows = conn.execute(
        """SELECT s.id, s.origin, s.provider, s.model, s.compare_id, s.status
           FROM messages s, messages m
           WHERE m.id=? AND s.conversation_id=m.conversation_id AND s.parent_id IS m.parent_id
           ORDER BY s.id""",
        (int(message_id),),
    )
    return [_row(r) for r in rows]


def compare_set(conn, compare_id: int) -> list:
    rows = conn.execute(
        """SELECT id, provider, model, status, content, origin
           FROM messages WHERE compare_id=? ORDER BY id""",
        (int(compare_id),),
    )
    return [_row(r) for r in rows]


def switch_branch(conn, conversation_id: int, message_id: int) -> int:
    """Remember this sibling at the fork, then walk down to a leaf."""
    message = get_message(conn, message_id)
    if message["conversation_id"] != int(conversation_id):
        raise ChatStoreError("ข้อความไม่อยู่ในการสนทนานี้")
    conn.execute(
        "UPDATE messages SET last_child_id=? WHERE id=(SELECT parent_id FROM messages WHERE id=?)",
        (int(message_id), int(message_id)),
    )
    leaf = conn.execute(
        """WITH RECURSIVE d(id, depth) AS (
             SELECT ?, 0
             UNION ALL
             SELECT COALESCE(
                      (SELECT c.id FROM messages c WHERE c.id = m.last_child_id AND c.parent_id = m.id),
                      (SELECT max(c.id) FROM messages c WHERE c.parent_id = m.id)
                    ), d.depth + 1
             FROM d JOIN messages m ON m.id = d.id
             WHERE EXISTS (SELECT 1 FROM messages c WHERE c.parent_id = m.id))
           SELECT id FROM d ORDER BY depth DESC LIMIT 1""",
        (int(message_id),),
    ).fetchone()
    leaf_id = int(leaf[0])
    conn.execute(
        "UPDATE conversations SET active_leaf_id=?, updated_at=? WHERE id=?",
        (leaf_id, now_ms(), int(conversation_id)),
    )
    return leaf_id


def ancestors(conn, message_id: int, *, include_start: bool = True) -> list:
    """Root → message, as role/content dicts (no system row)."""
    if message_id is None:
        return []
    rows = conn.execute(
        """WITH RECURSIVE path(id, depth) AS (
             SELECT ?, 0
             UNION ALL
             SELECT m.parent_id, p.depth + 1 FROM messages m
             JOIN path p ON m.id = p.id WHERE m.parent_id IS NOT NULL)
           SELECT m.role, m.content, m.id FROM path
           JOIN messages m ON m.id = path.id
           ORDER BY path.depth DESC""",
        (int(message_id),),
    ).fetchall()
    out = []
    for row in rows:
        if not include_start and row["id"] == int(message_id):
            continue
        if row["role"] in ("user", "assistant", "system"):
            out.append({"role": row["role"], "content": row["content"] or ""})
    return out


def transcript(conn, conversation_id: int, *, up_to=None, fallback_system: str = "") -> list:
    """Messages for a provider: effective system prompt, then the active path."""
    system = effective_system(conn, int(conversation_id)) or (fallback_system or "")
    if up_to is None:
        conv = _resolve_conversation(conn, conversation_id)
        up_to = conv["active_leaf_id"]
    body = ancestors(conn, up_to, include_start=True) if up_to else []
    body = [m for m in body if m["role"] != "system"]
    if system:
        return [{"role": "system", "content": system}] + body
    return body


def delete_conversation(conn, key) -> None:
    row = _resolve_conversation(conn, key)
    conn.execute(
        """INSERT INTO msg_fts(msg_fts, rowid, body)
           SELECT 'delete', id, lca_seg(content) FROM messages
           WHERE conversation_id=? AND role IN ('user','assistant')
             AND status!='streaming' AND content != ''""",
        (row["id"],),
    )
    conn.execute("DELETE FROM conversations WHERE id=?", (row["id"],))


def search(conn, query: str, limit: int = 50) -> dict:
    query = (query or "").strip()
    limit = max(1, min(int(limit or 50), 50))
    if not query:
        return {"messages": [], "conversations": []}
    pattern = like_pattern(query)
    titles = [
        _row(r) for r in conn.execute(
            """SELECT id, uid, title, updated_at, owner FROM conversations
               WHERE archived=0 AND title LIKE ? ESCAPE '\\'
               ORDER BY updated_at DESC LIMIT ?""",
            (pattern, limit),
        )
    ]
    messages = []
    built = fts_query(query)
    if built is None and is_single_thai_char(query):
        rows = conn.execute(
            """SELECT m.id, m.conversation_id, c.title, c.owner, m.role, m.model, m.content
               FROM messages m JOIN conversations c ON c.id = m.conversation_id
               WHERE c.archived=0 AND m.content LIKE ? ESCAPE '\\'
                 AND m.conversation_id IN (
                   SELECT id FROM conversations WHERE archived=0
                   ORDER BY updated_at DESC LIMIT 500)
               ORDER BY m.id DESC LIMIT ?""",
            (pattern, limit),
        )
        for row in rows:
            item = _row(row)
            item["snippet"] = snippet(item["content"], query)
            messages.append(item)
    elif built:
        rows = conn.execute(
            """SELECT m.id, m.conversation_id, c.title, c.owner, m.role, m.model, m.content, f.rank
               FROM (SELECT rowid, rank FROM msg_fts WHERE msg_fts MATCH ? ORDER BY rank LIMIT ?) f
               JOIN messages m ON m.id = f.rowid
               JOIN conversations c ON c.id = m.conversation_id
               WHERE c.archived=0
               ORDER BY f.rank""",
            (built, limit),
        )
        for row in rows:
            item = _row(row)
            item["snippet"] = snippet(item["content"], query)
            messages.append(item)
    return {"messages": messages, "conversations": titles}


def usage_by_model(conn, since: int = 0) -> list:
    rows = conn.execute(
        """SELECT provider, model, count(*) AS replies,
                  sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out,
                  sum(tokens_est) AS n_estimated
           FROM messages
           WHERE role='assistant' AND created_at >= ?
           GROUP BY provider, model
           ORDER BY tokens_out DESC""",
        (int(since or 0),),
    )
    return [_row(r) for r in rows]


# --- export / import (one conversation, JSON; zip container is not required) -

def export_conversation(conn, key) -> dict:
    conv = _resolve_conversation(conn, key)
    messages = conn.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conv["id"],)
    ).fetchall()
    by_id = {m["id"]: m for m in messages}
    folder = None
    if conv["folder_id"]:
        folder = conn.execute("SELECT * FROM folders WHERE id=?", (conv["folder_id"],)).fetchone()
    persona_ids = set()
    if conv["persona_id"]:
        persona_ids.add(conv["persona_id"])
    if folder and folder["persona_id"]:
        persona_ids.add(folder["persona_id"])
    personas = []
    if persona_ids:
        marks = ",".join("?" for _ in persona_ids)
        personas = [
            _public_persona(r) for r in conn.execute(
                f"SELECT * FROM personas WHERE id IN ({marks})", tuple(persona_ids)
            )
        ]
    folders = [_public_folder(folder, conn)] if folder else []
    msg_out = []
    for message in messages:
        parent_uid = by_id[message["parent_id"]]["uid"] if message["parent_id"] in by_id else None
        source_uid = by_id[message["source_id"]]["uid"] if message["source_id"] in by_id else None
        compare_uid = by_id[message["compare_id"]]["uid"] if message["compare_id"] in by_id else None
        msg_out.append({
            "uid": message["uid"],
            "parent_uid": parent_uid,
            "role": message["role"],
            "origin": message["origin"],
            "source_uid": source_uid,
            "compare_uid": compare_uid,
            "content": message["content"],
            "provider": message["provider"],
            "model": message["model"],
            "status": message["status"],
            "usage": {
                "in": message["tokens_in"],
                "out": message["tokens_out"],
                "estimated": message["tokens_est"],
            },
            "latency_ms": message["latency_ms"],
            "created_at": message["created_at"],
        })
    leaf_uid = by_id[conv["active_leaf_id"]]["uid"] if conv["active_leaf_id"] in by_id else None
    return {
        "format": "lca-chat-export",
        "version": 1,
        "schema_version": 10,
        "personas": personas,
        "folders": folders,
        "conversation": {
            "uid": conv["uid"],
            "title": conv["title"],
            "folder_uid": folder["uid"] if folder else None,
            "persona_uid": next((p["uid"] for p in personas if conv["persona_id"] and p.get("_id") == conv["persona_id"]), None),
            "system_prompt": conv["system_prompt"],
            "owner": conv["owner"],
            "pinned": conv["pinned"],
            "archived": conv["archived"],
            "active_leaf_uid": leaf_uid,
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "messages": msg_out,
        },
    }


def _public_persona(row) -> dict:
    return {
        "_id": row["id"],
        "uid": row["uid"],
        "name": row["name"],
        "system_prompt": row["system_prompt"],
        "provider": row["provider"],
        "model": row["model"],
        "params": row["params"],
        "source_skill_id": row["source_skill_id"],
        "archived": row["archived"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _public_folder(row, conn) -> dict:
    parent_uid = None
    if row["parent_id"]:
        parent = conn.execute("SELECT uid FROM folders WHERE id=?", (row["parent_id"],)).fetchone()
        parent_uid = parent["uid"] if parent else None
    persona_uid = None
    if row["persona_id"]:
        persona = conn.execute("SELECT uid FROM personas WHERE id=?", (row["persona_id"],)).fetchone()
        persona_uid = persona["uid"] if persona else None
    return {
        "uid": row["uid"],
        "parent_uid": parent_uid,
        "kind": row["kind"],
        "name": row["name"],
        "instructions": row["instructions"],
        "persona_uid": persona_uid,
        "sort": row["sort"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def export_public(conn, key) -> dict:
    doc = export_conversation(conn, key)
    # Fix persona_uid using _id before stripping.
    conv = get_conversation(conn, key)
    persona_uid = None
    if conv["persona_id"]:
        for persona in doc["personas"]:
            if persona.get("_id") == conv["persona_id"]:
                persona_uid = persona["uid"]
    doc["conversation"]["persona_uid"] = persona_uid
    for persona in doc["personas"]:
        persona.pop("_id", None)
    return doc


def import_document(conn, doc: dict, *, as_copy: bool = False) -> dict:
    """Insert one exported conversation. Importing the same file twice changes nothing."""
    if not isinstance(doc, dict) or doc.get("format") != "lca-chat-export":
        raise ChatStoreError("ไฟล์นำเข้าไม่ใช่ lca-chat-export")
    if int(doc.get("version") or 0) > 1:
        raise ChatStoreError("ไฟล์นำเข้าใหม่กว่าที่โปรแกรมรองรับ")
    conv = doc.get("conversation") or {}
    if not conv.get("uid") or not isinstance(conv.get("messages"), list):
        raise ChatStoreError("ไฟล์นำเข้าไม่มีบทสนทนา")
    uid_map = {}

    def map_uid(value):
        if value is None:
            return None
        if as_copy:
            mapped = uid_map.get(value)
            if mapped is None:
                mapped = new_uid()
                uid_map[value] = mapped
            return mapped
        return value

    if as_copy:
        for persona in doc.get("personas") or []:
            map_uid(persona.get("uid"))
        for folder in doc.get("folders") or []:
            map_uid(folder.get("uid"))
        map_uid(conv.get("uid"))
        for message in conv.get("messages") or []:
            map_uid(message.get("uid"))

    for persona in doc.get("personas") or []:
        _import_persona(conn, persona, map_uid)
    for folder in doc.get("folders") or []:
        _import_folder(conn, folder, map_uid)
    return _import_conversation(conn, conv, map_uid, as_copy=as_copy)


def _import_persona(conn, persona: dict, map_uid) -> None:
    uid = map_uid(persona.get("uid"))
    if not uid:
        return
    existing = conn.execute("SELECT * FROM personas WHERE uid=?", (uid,)).fetchone()
    now_updated = int(persona.get("updated_at") or 0)
    if existing:
        if now_updated > int(existing["updated_at"] or 0):
            conn.execute(
                """UPDATE personas SET name=?, system_prompt=?, provider=?, model=?, params=?, updated_at=?
                   WHERE uid=?""",
                (
                    persona.get("name") or existing["name"],
                    persona.get("system_prompt") or "",
                    persona.get("provider"),
                    persona.get("model"),
                    persona.get("params"),
                    now_updated,
                    uid,
                ),
            )
        return
    name = persona.get("name") or "persona"
    clash = conn.execute("SELECT 1 FROM personas WHERE name=?", (name,)).fetchone()
    if clash and not name.endswith(" (นำเข้า)"):
        name = name + " (นำเข้า)"
    conn.execute(
        """INSERT INTO personas(uid, name, system_prompt, provider, model, params, source_skill_id,
                                archived, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            uid, name, persona.get("system_prompt") or "", persona.get("provider"), persona.get("model"),
            persona.get("params"), persona.get("source_skill_id"), int(persona.get("archived") or 0),
            int(persona.get("created_at") or now_ms()), int(persona.get("updated_at") or now_ms()),
        ),
    )


def _import_folder(conn, folder: dict, map_uid) -> None:
    uid = map_uid(folder.get("uid"))
    if not uid:
        return
    parent_uid = map_uid(folder.get("parent_uid"))
    parent_id = None
    if parent_uid:
        parent = conn.execute("SELECT id FROM folders WHERE uid=?", (parent_uid,)).fetchone()
        parent_id = parent["id"] if parent else None
    persona_uid = map_uid(folder.get("persona_uid"))
    persona_id = None
    if persona_uid:
        persona = conn.execute("SELECT id FROM personas WHERE uid=?", (persona_uid,)).fetchone()
        persona_id = persona["id"] if persona else None
    existing = conn.execute("SELECT * FROM folders WHERE uid=?", (uid,)).fetchone()
    if existing:
        if int(folder.get("updated_at") or 0) > int(existing["updated_at"] or 0):
            conn.execute(
                """UPDATE folders SET name=?, instructions=?, persona_id=?, parent_id=?, updated_at=?
                   WHERE uid=?""",
                (
                    folder.get("name") or existing["name"], folder.get("instructions"), persona_id,
                    parent_id, int(folder.get("updated_at") or now_ms()), uid,
                ),
            )
        return
    name = folder.get("name") or "folder"
    clash = conn.execute("SELECT 1 FROM folders WHERE name=? AND uid<>?", (name, uid)).fetchone()
    if clash and not name.endswith(" (นำเข้า)"):
        name = name + " (นำเข้า)"
    conn.execute(
        """INSERT INTO folders(uid, parent_id, kind, name, instructions, persona_id, sort, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            uid, parent_id, folder.get("kind") or "folder", name, folder.get("instructions"),
            persona_id, int(folder.get("sort") or 0),
            int(folder.get("created_at") or now_ms()), int(folder.get("updated_at") or now_ms()),
        ),
    )


def _import_conversation(conn, conv: dict, map_uid, *, as_copy: bool) -> dict:
    uid = map_uid(conv.get("uid"))
    folder_uid = map_uid(conv.get("folder_uid"))
    persona_uid = map_uid(conv.get("persona_uid"))
    folder_id = None
    if folder_uid:
        folder = conn.execute("SELECT id FROM folders WHERE uid=?", (folder_uid,)).fetchone()
        folder_id = folder["id"] if folder else None
    persona_id = None
    if persona_uid:
        persona = conn.execute("SELECT id FROM personas WHERE uid=?", (persona_uid,)).fetchone()
        persona_id = persona["id"] if persona else None
    existing = conn.execute("SELECT * FROM conversations WHERE uid=?", (uid,)).fetchone()
    incoming_updated = int(conv.get("updated_at") or 0)
    if existing is None:
        cur = conn.execute(
            """INSERT INTO conversations(
                 uid, folder_id, persona_id, owner, title, system_prompt, pinned, archived, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                uid, folder_id, persona_id, conv.get("owner"), conv.get("title") or "",
                conv.get("system_prompt"), int(conv.get("pinned") or 0), int(conv.get("archived") or 0),
                int(conv.get("created_at") or now_ms()), incoming_updated or now_ms(),
            ),
        )
        conv_id = cur.lastrowid
        take_leaf = True
    else:
        conv_id = existing["id"]
        take_leaf = incoming_updated > int(existing["updated_at"] or 0)
        if take_leaf:
            conn.execute(
                """UPDATE conversations
                   SET title=?, folder_id=?, persona_id=?, system_prompt=?, pinned=?, archived=?, updated_at=?
                   WHERE id=?""",
                (
                    conv.get("title") or existing["title"], folder_id, persona_id, conv.get("system_prompt"),
                    int(conv.get("pinned") or 0), int(conv.get("archived") or 0),
                    incoming_updated, conv_id,
                ),
            )
    local_by_uid = {}
    for message in conv.get("messages") or []:
        muid = map_uid(message.get("uid"))
        if not muid:
            raise ChatStoreError("ข้อความในไฟล์นำเข้าไม่มี uid")
        found = conn.execute(
            "SELECT id FROM messages WHERE uid=? AND conversation_id=?", (muid, conv_id)
        ).fetchone()
        if found:
            local_by_uid[muid] = found["id"]
            continue
        parent_uid = map_uid(message.get("parent_uid"))
        parent_id = None
        if parent_uid:
            parent_id = local_by_uid.get(parent_uid)
            if parent_id is None:
                parent = conn.execute(
                    "SELECT id FROM messages WHERE uid=? AND conversation_id=?",
                    (parent_uid, conv_id),
                ).fetchone()
                parent_id = parent["id"] if parent else None
            if parent_id is None:
                raise ChatStoreError("ไฟล์นำเข้าขาด parent ของข้อความ — ไม่เก็บต้นไม้ที่ขาด")
        usage = message.get("usage") or {}
        cur = conn.execute(
            """INSERT INTO messages(
                 uid, conversation_id, parent_id, role, origin, content, provider, model, status,
                 tokens_in, tokens_out, tokens_est, latency_ms, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                muid, conv_id, parent_id, message.get("role") or "user", message.get("origin"),
                message.get("content") or "", message.get("provider"), message.get("model"),
                message.get("status") or "ok", usage.get("in"), usage.get("out"),
                int(usage.get("estimated") or 0), message.get("latency_ms"),
                int(message.get("created_at") or now_ms()),
            ),
        )
        local_by_uid[muid] = cur.lastrowid
        _index_message(
            conn, cur.lastrowid, message.get("role") or "user",
            message.get("status") or "ok", message.get("content") or "",
        )
    for message in conv.get("messages") or []:
        muid = map_uid(message.get("uid"))
        mid = local_by_uid.get(muid)
        if mid is None:
            continue
        source_uid = map_uid(message.get("source_uid"))
        compare_uid = map_uid(message.get("compare_uid"))
        source_id = local_by_uid.get(source_uid) if source_uid else None
        compare_id = local_by_uid.get(compare_uid) if compare_uid else None
        if source_id or compare_id:
            conn.execute(
                "UPDATE messages SET source_id=COALESCE(?, source_id), compare_id=COALESCE(?, compare_id) WHERE id=?",
                (source_id, compare_id, mid),
            )
    leaf_uid = map_uid(conv.get("active_leaf_uid"))
    if take_leaf and leaf_uid and leaf_uid in local_by_uid:
        conn.execute(
            "UPDATE conversations SET active_leaf_id=? WHERE id=?",
            (local_by_uid[leaf_uid], conv_id),
        )
    elif conn.execute("SELECT active_leaf_id FROM conversations WHERE id=?", (conv_id,)).fetchone()[0] is None:
        last = conn.execute(
            "SELECT max(id) FROM messages WHERE conversation_id=?", (conv_id,)
        ).fetchone()[0]
        if last:
            conn.execute(
                "UPDATE conversations SET active_leaf_id=? WHERE id=?", (last, conv_id)
            )
    return get_conversation(conn, conv_id)
