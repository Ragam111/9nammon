"""Chat hub schema, Thai bigram search, and the branch/regen/compare queries.

Adapted from the attached schema checks (FTS samples, active path, switch,
compare set, persona, usage). No network.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import chat_search, chat_store, config_manager, db, skills_store  # noqa: E402
from app import dataset_store  # noqa: E402


SAMPLES = [
    ("user", "สวัสดีครับ ช่วยออกแบบฐานข้อมูล SQLite ให้หน่อย"),
    ("assistant", "ได้ครับ ตาราง messages ควรมี parent_id เพื่อเก็บเป็น tree"),
    ("user", "วันนี้ไปกินข้าวที่ร้านอาหารไทยกับเพื่อน"),
    ("assistant", "Python 3.12 ships SQLite 3.45 with FTS5 enabled; ภาษาไทยไม่มีการเว้นวรรคระหว่างคำ"),
    ("user", "การค้นหาข้อความภาษาไทยปน English ต้องทำงานได้ดี"),
    ("assistant", "Café résumé naïve — accents test; ประเทศไทย"),
]


def _root():
    tmp = tempfile.TemporaryDirectory()
    return tmp, Path(tmp.name)


class MigrationTest(unittest.TestCase):
    def test_migration_number_is_next_free(self):
        files = sorted(p.name for p in (Path(__file__).resolve().parent.parent / "app" / "migrations").glob("*.sql"))
        self.assertIn("0010_chat_hub.sql", files)
        self.assertIn("0011_server_events.sql", files)
        self.assertGreaterEqual(db.code_version(), 11)

    def test_fresh_db_pragmas_and_idempotent(self):
        tmp, root = _root()
        self.addCleanup(tmp.cleanup)
        db.ensure_migrated(root)
        db.ensure_migrated(root)
        conn = db.connect_raw(db.db_path(root))
        try:
            self.assertGreaterEqual(conn.execute("PRAGMA user_version").fetchone()[0], 11)
            self.assertEqual(conn.execute("PRAGMA page_size").fetchone()[0], 4096)
            self.assertEqual(conn.execute("PRAGMA auto_vacuum").fetchone()[0], 2)
            self.assertEqual(str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(), "wal")
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertGreaterEqual(conn.execute("SELECT count(*) FROM schema_version").fetchone()[0], 2)
            names = [r[0] for r in conn.execute("SELECT name FROM schema_version ORDER BY version")]
            self.assertIn("0010_chat_hub", names)
            self.assertIn("0011_server_events", names)
            self.assertIn("msg_fts", [r[0] for r in conn.execute("SELECT name FROM sqlite_master")])
            self.assertEqual(conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)
        finally:
            conn.close()

    def test_empty_sessions_table_becomes_a_view(self):
        tmp, root = _root()
        self.addCleanup(tmp.cleanup)
        path = db.db_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE sessions (id INTEGER)")
        conn.commit()
        conn.close()
        db.ensure_migrated(root)
        conn = db.connect_raw(path)
        try:
            kind = conn.execute("SELECT type FROM sqlite_master WHERE name='sessions'").fetchone()[0]
            self.assertEqual(kind, "view")
        finally:
            conn.close()

    def test_sessions_with_rows_are_refused(self):
        tmp, root = _root()
        self.addCleanup(tmp.cleanup)
        path = db.db_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE sessions (id INTEGER)")
        conn.execute("INSERT INTO sessions(id) VALUES (1)")
        conn.commit()
        conn.close()
        with self.assertRaises(Exception):
            db.ensure_migrated(root)
        conn = sqlite3.connect(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
        finally:
            conn.close()

    def test_skills_seeded_once(self):
        tmp, root = _root()
        self.addCleanup(tmp.cleanup)
        skills_store.add(root, "Coder", "คุณคือผู้ช่วยเขียนโค้ด", model="qwen", mode="chat")
        skills_store.add(root, "Agent", "ไม่เอา", mode="agent")
        db.ensure_migrated(root)
        db.ensure_migrated(root)
        with chat_store.read_txn(root) as conn:
            rows = conn.execute("SELECT name, source_skill_id FROM personas ORDER BY name").fetchall()
            self.assertEqual([r["name"] for r in rows], ["Coder"])
            marker = conn.execute("SELECT value FROM schema_meta WHERE key='imported_from'").fetchone()[0]
            self.assertEqual(marker, "skills@v10")
            uid = conn.execute("SELECT uid FROM personas").fetchone()[0]
        skill = skills_store.list_skills(root)[0]
        # list order is not guaranteed; find the chat skill
        chat = next(s for s in skills_store.list_skills(root) if s["mode"] == "chat")
        self.assertEqual(uid, str(uuid.uuid5(uuid.NAMESPACE_URL, f"lca:skill:{chat['id']}")))

    def test_samples_import_off_by_default(self):
        tmp, root = _root()
        self.addCleanup(tmp.cleanup)
        dataset_store.add_sample(root, "ภาษาไทยในตัวอย่าง", "คำตอบ", model="qwen")
        db.ensure_migrated(root)
        with chat_store.read_txn(root) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM conversations").fetchone()[0], 0)
            marker = conn.execute("SELECT value FROM schema_meta WHERE key='imported_samples'").fetchone()[0]
            self.assertTrue(marker.startswith("samples@v10"))

    def test_samples_import_when_opted_in(self):
        tmp, root = _root()
        self.addCleanup(tmp.cleanup)
        dataset_store.add_sample(root, "นำเข้าภาษาไทย", "ตอบกลับ", model="qwen")
        config_manager.set_key(root, "CHAT_IMPORT_SAMPLES", "1")
        db.ensure_migrated(root)
        with chat_store.read_txn(root) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM conversations").fetchone()[0], 1)
            self.assertEqual(conn.execute(
                "SELECT origin FROM messages WHERE role='assistant'"
            ).fetchone()[0], "import")
            hits = chat_store.search(conn, "ภาษาไทย")["messages"]
            self.assertTrue(hits)


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.root = _root()
        with chat_store.write_txn(self.root) as conn:
            conv = chat_store.create_conversation(conn, title="ทดสอบ")
            parent = None
            self.ids = []
            for role, content in SAMPLES:
                row = chat_store.insert_message(conn, conv["id"], role=role, content=content, parent_id=parent)
                parent = row["id"]
                self.ids.append(row["id"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_bigram_matches_truth_and_two_char_thai(self):
        truth = lambda q: [i + 1 for i, (_, c) in enumerate(SAMPLES) if q.lower() in c.lower()]
        with chat_store.read_txn(self.root) as conn:
            for query in ("ภาษาไทย", "ไทย", "ไป", "กินข้าว", "ข้อมูล", "sqlite", "SQLITE", "pyth", "English", "cafe", "ภาษาไทย English", "ไม่มีอยู่", "ทย"):
                got = [m["id"] for m in chat_store.search(conn, query)["messages"]]
                if query == "cafe":
                    expected = [6]  # accent-folded; a raw substring check misses Café
                elif query == "ภาษาไทย English":
                    expected = [5]  # terms are ANDed, not matched as one substring
                elif query == "ทย":
                    expected = [3, 4, 5, 6]
                else:
                    expected = truth(query)
                self.assertEqual(sorted(got), expected, query)
            one = chat_store.search(conn, "ค")["messages"]
            self.assertEqual(sorted(m["id"] for m in one), truth("ค"))
            self.assertIsNone(chat_search.fts_query("ค"))
            self.assertIn("pyth", chat_search.fts_query("pyth"))

    def test_trigram_misses_two_char_thai_that_bigram_hits(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE tri USING fts5(body, tokenize='trigram')")
        conn.execute("INSERT INTO tri(body) VALUES (?)", (SAMPLES[2][1],))
        self.assertEqual(conn.execute("SELECT count(*) FROM tri WHERE tri MATCH ?", ('"ไป"',)).fetchone()[0], 0)
        with chat_store.read_txn(self.root) as dbconn:
            self.assertTrue(chat_store.search(dbconn, "ไป")["messages"])

    def test_delete_removes_fts_hits_and_deep_tree(self):
        with chat_store.write_txn(self.root) as conn:
            conv = chat_store.get_conversation(conn, 1)
            chat_store.delete_conversation(conn, conv["id"])
            self.assertEqual(chat_store.search(conn, "sqlite")["messages"], [])
            deep = chat_store.create_conversation(conn, title="deep")
            parent = None
            for _ in range(3000):
                row = chat_store.insert_message(conn, deep["id"], role="user", content="x", parent_id=parent)
                parent = row["id"]
            chat_store.delete_conversation(conn, deep["id"])
            self.assertEqual(conn.execute("SELECT count(*) FROM messages WHERE conversation_id=?", (deep["id"],)).fetchone()[0], 0)


class QueryTest(unittest.TestCase):
    def test_path_switch_compare_persona_usage(self):
        tmp, root = _root()
        self.addCleanup(tmp.cleanup)
        with chat_store.write_txn(root) as conn:
            coder = chat_store.create_persona(conn, name="Coder", system_prompt="คุณคือผู้ช่วยเขียนโค้ด")
            translator = chat_store.create_persona(conn, name="Translator", system_prompt="แปลไทย↔อังกฤษ")
            folder = chat_store.create_folder(conn, name="LCA", kind="project", persona_id=coder["id"], instructions="ใช้ SQL")
            conv = chat_store.create_conversation(conn, title="ออกแบบ DB", folder_id=folder["id"])
            cid = conv["id"]
            u1 = chat_store.insert_message(conn, cid, role="user", content="ช่วยออกแบบตาราง messages")
            a1 = chat_store.insert_message(
                conn, cid, role="assistant", content="ได้ครับ v1", parent_id=u1["id"],
                provider="ollama", model="qwen2.5-coder:3b", tokens_in=20, tokens_out=50, tokens_est=1,
            )
            a2 = chat_store.insert_message(
                conn, cid, role="assistant", content="ได้ครับ v2", parent_id=u1["id"],
                origin="regen", source_id=a1["id"], provider="ollama", model="qwen2.5-coder:3b",
                tokens_in=20, tokens_out=60,
            )
            a3 = chat_store.insert_message(
                conn, cid, role="assistant", content="คำตอบ claude", parent_id=u1["id"],
                origin="compare", provider="anthropic", model="claude-x", tokens_in=22, tokens_out=80,
            )
            conn.execute("UPDATE messages SET compare_id=? WHERE id IN (?,?)", (a2["id"], a2["id"], a3["id"]))
            u2 = chat_store.insert_message(conn, cid, role="user", content="เพิ่ม index ด้วย", parent_id=a2["id"])
            a4 = chat_store.insert_message(
                conn, cid, role="assistant", content="เพิ่มแล้ว", parent_id=u2["id"],
                provider="openai", model="gpt-x", tokens_in=90, tokens_out=40,
            )
            u2e = chat_store.insert_message(
                conn, cid, role="user", content="เพิ่ม index และ FTS ด้วย", parent_id=a2["id"],
                origin="edit", source_id=u2["id"],
            )
            a5 = chat_store.insert_message(
                conn, cid, role="assistant", content="เพิ่ม FTS", parent_id=u2e["id"],
                provider="xai", model="grok-x", tokens_in=95, tokens_out=70,
            )
            path = chat_store.active_path(conn, cid)
            self.assertEqual([m["content"] for m in path], [
                "ช่วยออกแบบตาราง messages", "ได้ครับ v2", "เพิ่ม index และ FTS ด้วย", "เพิ่ม FTS",
            ])
            fork = next(m for m in path if m["id"] == a2["id"])
            self.assertEqual((fork["ver"], fork["n_ver"]), (2, 3))
            self.assertEqual(chat_store.switch_branch(conn, cid, a2["id"]), a5["id"])
            self.assertEqual(chat_store.switch_branch(conn, cid, u2["id"]), a4["id"])
            self.assertEqual(chat_store.switch_branch(conn, cid, a1["id"]), a1["id"])
            self.assertEqual(chat_store.switch_branch(conn, cid, a2["id"]), a4["id"])
            self.assertEqual(chat_store.switch_branch(conn, cid, u2e["id"]), a5["id"])
            self.assertEqual(chat_store.switch_branch(conn, cid, a1["id"]), a1["id"])
            self.assertEqual(chat_store.switch_branch(conn, cid, a2["id"]), a5["id"])
            self.assertEqual(conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
            compared = chat_store.compare_set(conn, a2["id"])
            self.assertEqual([c["provider"] for c in compared], ["ollama", "anthropic"])
            self.assertIn("คุณคือผู้ช่วยเขียนโค้ด", chat_store.effective_system(conn, cid))
            self.assertIn("ใช้ SQL", chat_store.effective_system(conn, cid))
            chat_store.update_conversation(conn, cid, persona_id=translator["id"])
            self.assertEqual(chat_store.effective_system(conn, cid).split("\n", 1)[0], "แปลไทย↔อังกฤษ")
            usage = {(u["provider"], u["model"]): u["tokens_out"] for u in chat_store.usage_by_model(conn)}
            self.assertEqual(usage[("ollama", "qwen2.5-coder:3b")], 110)
            self.assertEqual(usage[("anthropic", "claude-x")], 80)
            plan = conn.execute(
                """EXPLAIN QUERY PLAN
                   SELECT s.id FROM messages s, messages m
                   WHERE m.id=? AND s.conversation_id=m.conversation_id AND s.parent_id IS m.parent_id""",
                (a1["id"],),
            ).fetchall()
            self.assertTrue(any("idx_msg_parent" in " ".join(map(str, row)) for row in plan))
            folder_plan = conn.execute(
                """EXPLAIN QUERY PLAN
                   SELECT id FROM conversations WHERE folder_id IS ? AND archived=0
                   ORDER BY pinned DESC, updated_at DESC LIMIT 50""",
                (folder["id"],),
            ).fetchall()
            self.assertTrue(any("idx_conv_folder" in " ".join(map(str, row)) for row in folder_plan))
            doc = chat_store.export_public(conn, cid)

        tmp2, root2 = _root()
        self.addCleanup(tmp2.cleanup)
        with chat_store.write_txn(root2) as conn:
            imported = chat_store.import_document(conn, doc)
            again = chat_store.import_document(conn, doc)
            self.assertEqual(imported["id"], again["id"])
            self.assertEqual(conn.execute("SELECT count(*) FROM messages").fetchone()[0], 8)
            contents = [r[0] for r in conn.execute("SELECT content FROM messages ORDER BY id")]
            self.assertIn("เพิ่ม FTS", contents)
            copied = chat_store.import_document(conn, doc, as_copy=True)
            self.assertNotEqual(copied["uid"], imported["uid"])
            self.assertEqual(conn.execute("SELECT count(*) FROM conversations").fetchone()[0], 2)


class ChatStoreExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_conversation_returns_id(self):
        with chat_store.write_txn(self.root) as conn:
            conv = chat_store.create_conversation(conn, title="test")
            self.assertIn("id", conv)

    def test_insert_message_returns_id(self):
        with chat_store.write_txn(self.root) as conn:
            conv = chat_store.create_conversation(conn, title="test")
            msg = chat_store.insert_message(conn, conv["id"], role="user", content="hi")
            self.assertIn("id", msg)

    def test_search_returns_messages_list(self):
        with chat_store.write_txn(self.root) as conn:
            conv = chat_store.create_conversation(conn, title="test")
            chat_store.insert_message(conn, conv["id"], role="user", content="สวัสดี")
            result = chat_store.search(conn, "สวัสดี")
            self.assertIn("messages", result)
            self.assertIsInstance(result["messages"], list)

    def test_active_path_returns_list(self):
        with chat_store.write_txn(self.root) as conn:
            conv = chat_store.create_conversation(conn, title="test")
            chat_store.insert_message(conn, conv["id"], role="user", content="hi")
            path = chat_store.active_path(conn, conv["id"])
            self.assertIsInstance(path, list)

    def test_usage_by_model_returns_list(self):
        with chat_store.write_txn(self.root) as conn:
            result = chat_store.usage_by_model(conn)
            self.assertIsInstance(result, list)

    def test_delete_conversation_removes_messages(self):
        with chat_store.write_txn(self.root) as conn:
            conv = chat_store.create_conversation(conn, title="to delete")
            chat_store.insert_message(conn, conv["id"], role="user", content="สวัสดี")
            chat_store.delete_conversation(conn, conv["id"])
            result = chat_store.search(conn, "สวัสดี")
            self.assertEqual(result["messages"], [])


if __name__ == "__main__":
    unittest.main()
