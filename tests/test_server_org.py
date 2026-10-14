"""
test_server_org.py — integration test ของ RBAC/API-key ที่ชั้น HTTP (stdlib unittest)

สตาร์ท server จริงใน process เดียวกันบนพอร์ตสุ่ม แล้วยิง request ผ่าน http.client
mock call_ollama ไว้ ไม่ต้องมี Ollama จริงรันอยู่
"""

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

MASTER = "master-secret-token"


class ServerOrgTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # mock Model layer — ไม่เรียก Ollama จริง
        server.call_ollama = lambda model, messages, num_ctx=8192: "mocked-reply"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        handler = server.make_handler(root, MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        data = json.loads(raw) if raw else {}
        return resp.status, data

    # ---- bootstrap + identity ----
    def test_full_org_flow(self):
        # 1) bootstrap: สร้าง CEO คนแรกได้โดยไม่ต้อง auth
        st, d = self._req("POST", "/api/admin/users",
                          {"username": "boss", "password": "password123", "role": "CEO"})
        self.assertEqual(st, 200, d)
        self.assertTrue(d.get("bootstrap"))

        # 2) หลัง bootstrap แล้ว สร้าง user ต่อโดยไม่ auth ไม่ได้
        st, _ = self._req("POST", "/api/admin/users",
                          {"username": "x", "password": "password123", "role": "USER"})
        self.assertEqual(st, 401)

        master_hdr = {"X-Auth-Token": MASTER}

        # 3) master token = CEO
        st, d = self._req("GET", "/api/me", headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["role"], "CEO")

        # 4) CEO สร้าง USER + ออก free API key
        st, d = self._req("POST", "/api/admin/users",
                          {"username": "dev", "password": "password123", "role": "USER"},
                          headers=master_hdr)
        self.assertEqual(st, 200, d)

        st, d = self._req("POST", "/api/admin/apikeys",
                          {"owner": "dev", "tier": "free"}, headers=master_hdr)
        self.assertEqual(st, 200, d)
        dev_key = d["api_key"]["key"]
        self.assertTrue(dev_key.startswith("lca_f_"))

        # 5) ใช้ dev key แชทได้ (กินโควตา)
        st, d = self._req("POST", "/api/chat",
                          {"messages": [{"role": "user", "content": "hi"}]},
                          headers={"X-API-Key": dev_key})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["reply"], "mocked-reply")

        # 6) dev (USER) เข้า admin route ไม่ได้ → 403
        st, _ = self._req("GET", "/api/admin/users", headers={"X-API-Key": dev_key})
        self.assertEqual(st, 403)

        # 7) ไม่มี auth เลย (ตั้ง master token ไว้) → chat 401
        st, _ = self._req("POST", "/api/chat",
                          {"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(st, 401)

        # 8) key มั่ว → 401
        st, _ = self._req("POST", "/api/chat",
                          {"messages": [{"role": "user", "content": "hi"}]},
                          headers={"X-API-Key": "lca_f_wrong"})
        self.assertEqual(st, 401)

    def test_quota_exhaustion_returns_429(self):
        self._req("POST", "/api/admin/users",
                  {"username": "boss", "password": "password123", "role": "CEO"})
        master_hdr = {"X-Auth-Token": MASTER}
        self._req("POST", "/api/admin/users",
                  {"username": "dev", "password": "password123", "role": "USER"},
                  headers=master_hdr)
        st, d = self._req("POST", "/api/admin/apikeys",
                          {"owner": "dev", "tier": "free"}, headers=master_hdr)
        key = d["api_key"]["key"]
        from app import org_store
        limit = org_store.TIER_DAILY_LIMIT["free"]
        hdr = {"X-API-Key": key}
        body = {"messages": [{"role": "user", "content": "hi"}]}
        for _ in range(limit):
            st, _ = self._req("POST", "/api/chat", body, headers=hdr)
            self.assertEqual(st, 200)
        st, _ = self._req("POST", "/api/chat", body, headers=hdr)
        self.assertEqual(st, 429)


if __name__ == "__main__":
    unittest.main()
