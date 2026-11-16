"""Personal space vs Org space: บทสนทนาของ USER คนหนึ่ง อีกคนต้องมองไม่เห็น/แก้ไม่ได้

- owner=ชื่อผู้ใช้  → พื้นที่ส่วนตัว (เจ้าของ + ADMIN/CEO เท่านั้น)
- owner=NULL      → พื้นที่บริษัท (ทุกคนที่ล็อกอินเห็น) — เช่นที่สร้างจาก master/local
"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import chat_hub, session_store  # noqa: E402
from app.providers.base import ChatResponse, Usage  # noqa: E402

MASTER = "master-secret-token"


class ChatOwnershipTest(unittest.TestCase):
    def setUp(self):
        session_store.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

        def chat(messages, model, *, provider, project_root=None, **_opts):
            return ChatResponse("ok-reply", model, provider, Usage(1, 1, 2, False, "provider"), None)

        self.patch = mock.patch("app.providers.chat", chat)
        self.patch.start()
        handler = server.make_handler(self.root, MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.master = {"X-Auth-Token": MASTER}
        for u, p, r in (("boss", "password123", "CEO"), ("alice", "alicepass1", "USER"),
                        ("bob", "bobpass123", "USER"), ("ops", "opspass123", "ADMIN")):
            st, d = self._req("POST", "/api/admin/users", {"username": u, "password": p, "role": r}, self.master)
            self.assertEqual(st, 200, d)
        self.alice = self._login("alice", "alicepass1")
        self.bob = self._login("bob", "bobpass123")
        self.ops = self._login("ops", "opspass123")

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.patch.stop()
        self._tmp.cleanup()
        session_store.clear()

    def _req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        ctype = resp.getheader("Content-Type") or ""
        conn.close()
        if "json" in ctype:
            return resp.status, (json.loads(raw) if raw else {})
        return resp.status, raw

    def _login(self, u, p):
        st, d = self._req("POST", "/api/auth/login", {"username": u, "password": p})
        self.assertEqual(st, 200, d)
        return {"X-Auth-Token": d["token"]}

    def _new_conv(self, hdr, title):
        st, d = self._req("POST", "/api/chat/conversations", {"title": title}, hdr)
        self.assertEqual(st, 200, d)
        return d["conversation"]

    def test_private_conversation_hidden_from_other_user(self):
        conv = self._new_conv(self.alice, "alice-private")
        self.assertEqual(conv["owner"], "alice")
        # bob มองไม่เห็นในรายการ
        st, d = self._req("GET", "/api/chat/conversations", headers=self.bob)
        self.assertEqual(st, 200)
        self.assertNotIn(conv["id"], [c["id"] for c in d["conversations"]])
        # bob อ่านตรง ๆ → 403
        st, d = self._req("GET", f"/api/chat/conversations?id={conv['id']}", headers=self.bob)
        self.assertEqual(st, 403, d)
        # bob แก้/ลบ/export/switch → 403
        st, _ = self._req("POST", "/api/chat/conversations/update", {"id": conv["id"], "title": "x"}, self.bob)
        self.assertEqual(st, 403)
        st, _ = self._req("POST", "/api/chat/conversations/delete", {"id": conv["id"]}, self.bob)
        self.assertEqual(st, 403)
        st, _ = self._req("GET", f"/api/chat/export?id={conv['id']}", headers=self.bob)
        self.assertEqual(st, 403)
        # bob ส่งข้อความเข้าบทสนทนาของ alice → 403 และต้องไม่มีอะไรถูกเขียน
        st, d = self._req("POST", "/api/chat", {"conversation_id": conv["id"], "content": "hi",
                                                "provider": "ollama", "model": "m"}, self.bob)
        self.assertEqual(st, 403, d)
        st, d = self._req("GET", f"/api/chat/conversations?id={conv['id']}", headers=self.alice)
        self.assertEqual(st, 200)
        self.assertEqual(d["messages"], [])
        # เจ้าของยังใช้ได้ปกติ
        st, d = self._req("POST", "/api/chat/conversations/update", {"id": conv["id"], "title": "mine"}, self.alice)
        self.assertEqual(st, 200, d)

    def test_admin_sees_everything_and_shared_space_visible_to_all(self):
        private = self._new_conv(self.alice, "alice-private")
        shared = self._new_conv(self.master, "company-shared")   # master/local → owner NULL
        self.assertIsNone(shared["owner"])
        st, d = self._req("GET", "/api/chat/conversations", headers=self.ops)
        ids = [c["id"] for c in d["conversations"]]
        self.assertIn(private["id"], ids)
        self.assertIn(shared["id"], ids)
        st, d = self._req("GET", "/api/chat/conversations", headers=self.bob)
        ids = [c["id"] for c in d["conversations"]]
        self.assertNotIn(private["id"], ids)
        self.assertIn(shared["id"], ids)
        st, _ = self._req("GET", f"/api/chat/conversations?id={private['id']}", headers=self.ops)
        self.assertEqual(st, 200)

    def test_search_filtered_by_owner(self):
        self._new_conv(self.alice, "zebra-secret-title")
        st, d = self._req("GET", "/api/chat/search?q=zebra", headers=self.bob)
        self.assertEqual(st, 200)
        self.assertEqual(d["conversations"], [])
        st, d = self._req("GET", "/api/chat/search?q=zebra", headers=self.alice)
        self.assertEqual(len(d["conversations"]), 1)

    def test_import_forces_owner_to_importer(self):
        conv = self._new_conv(self.alice, "to-export")
        st, doc = self._req("GET", f"/api/chat/export?id={conv['id']}", headers=self.alice)
        self.assertEqual(st, 200)
        self.assertEqual(doc["conversation"]["owner"], "alice")
        st, d = self._req("POST", "/api/chat/import", {"document": doc, "as_copy": True}, self.bob)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["conversation"]["owner"], "bob")

    def test_markdown_export_session_tape(self):
        conv = self._new_conv(self.alice, "tape-title")
        st, d = self._req("POST", "/api/chat", {"conversation_id": conv["id"], "content": "สวัสดี",
                                                "provider": "ollama", "model": "m1"}, self.alice)
        self.assertEqual(st, 200, d)
        st, text = self._req("GET", f"/api/chat/export?id={conv['id']}&format=md", headers=self.alice)
        self.assertEqual(st, 200)
        self.assertTrue(text.startswith("# tape-title"))
        self.assertIn("## ผู้ใช้", text)
        self.assertIn("สวัสดี", text)
        self.assertIn("## ผู้ช่วย (ollama/m1)", text)
        self.assertIn("ok-reply", text)

    def test_can_see_rules_unit(self):
        self.assertTrue(chat_hub._can_see(None, {"username": "x", "role": "USER"}))
        self.assertTrue(chat_hub._can_see("x", {"username": "x", "role": "USER"}))
        self.assertFalse(chat_hub._can_see("y", {"username": "x", "role": "USER"}))
        self.assertTrue(chat_hub._can_see("y", {"username": "x", "role": "ADMIN"}))
        self.assertTrue(chat_hub._can_see("y", {"username": "__master__", "role": "CEO"}))
        self.assertFalse(chat_hub._can_see("y", {"username": None, "role": "GUEST"}))


if __name__ == "__main__":
    unittest.main()
