"""GUEST (ไม่ล็อกอิน): ปิดเป็นค่าเริ่มต้น; เปิดแล้วแชทได้เฉพาะ local, ไม่บันทึก, โควตาต่อ IP ต่อวัน"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import config_manager, model_backend, org_store  # noqa: E402

MASTER = "master-secret-token"


class GuestChatTest(unittest.TestCase):
    def setUp(self):
        server._guest_quota_reset()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_gen = model_backend.generate
        self._orig_stream = model_backend.generate_stream
        model_backend.generate = lambda project_root, model, messages, num_ctx=8192, options=None: "guest-reply"

        def gen(project_root, model, messages, num_ctx=8192, options=None):
            yield "g"
        model_backend.generate_stream = gen
        handler = server.make_handler(self.root, MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        model_backend.generate = self._orig_gen
        model_backend.generate_stream = self._orig_stream
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()
        server._guest_quota_reset()

    def _req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def _enable(self):
        config_manager.set_key(self.root, "GUEST_CHAT_ENABLED", "1")

    def test_guest_off_by_default_401(self):
        st, d = self._req("POST", "/api/chat", {"messages": [{"role": "user", "content": "hi"}], "model": "m"})
        self.assertEqual(st, 401, d)

    def test_guest_role_cannot_be_created_as_account(self):
        with self.assertRaises(ValueError):
            org_store.create_user(self.root, "g", "password123", "GUEST")
        self.assertFalse(org_store.role_at_least("GUEST", "USER"))

    def test_guest_chat_when_enabled_no_persistence(self):
        self._enable()
        st, d = self._req("POST", "/api/chat", {"messages": [{"role": "user", "content": "hi"}], "model": "m"})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["reply"], "guest-reply")
        # ไม่มีการใช้งานถูกบันทึกใน usage.db / ไม่มีบทสนทนาใน DB
        st, d = self._req("GET", "/api/admin/usage", headers={"X-Auth-Token": MASTER})
        self.assertEqual(st, 200)
        self.assertEqual(d.get("usage", []), [])
        st, d = self._req("GET", "/api/chat/conversations", headers={"X-Auth-Token": MASTER})
        self.assertEqual(d["conversations"], [])

    def test_guest_stream_works(self):
        self._enable()
        st, raw = self._req("POST", "/api/chat/stream", {"messages": [{"role": "user", "content": "hi"}], "model": "m"})
        self.assertEqual(st, 200)
        self.assertIn('data: {"delta": "g"}', raw)
        self.assertIn('{"done": true}', raw)

    def test_guest_cannot_touch_history_or_cloud(self):
        self._enable()
        st, d = self._req("POST", "/api/chat", {"conversation_id": 1, "content": "hi", "model": "m"})
        self.assertEqual(st, 403, d)
        st, d = self._req("POST", "/api/chat", {"messages": [{"role": "user", "content": "hi"}],
                                                "model": "gpt-x", "provider": "openai"})
        self.assertEqual(st, 403, d)
        # history API ยังต้องล็อกอิน
        st, _ = self._req("GET", "/api/chat/conversations")
        self.assertEqual(st, 401)
        st, _ = self._req("GET", "/api/me")
        self.assertEqual(st, 401)

    def test_guest_daily_quota_429(self):
        self._enable()
        body = {"messages": [{"role": "user", "content": "hi"}], "model": "m"}
        for _ in range(server.GUEST_DAILY_LIMIT):
            st, _ = self._req("POST", "/api/chat", body)
            self.assertEqual(st, 200)
        st, d = self._req("POST", "/api/chat", body)
        self.assertEqual(st, 429, d)
        # ล็อกอิน (master) ยังใช้ได้ — โควตา guest ไม่กระทบผู้ใช้จริง
        st, _ = self._req("POST", "/api/chat", body, {"X-Auth-Token": MASTER})
        self.assertEqual(st, 200)


if __name__ == "__main__":
    unittest.main()
