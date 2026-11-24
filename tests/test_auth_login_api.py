"""HTTP tests: login ด้วย username/password → session token, logout, และ page gate ของ /dev /console

ยิง request จริงผ่าน http.client (server บนพอร์ตสุ่ม) — ไม่ต้องมี Ollama
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
from app import session_store  # noqa: E402

MASTER = "master-secret-token"


class AuthLoginApiTest(unittest.TestCase):
    def setUp(self):
        session_store.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        handler = server.make_handler(self.root, MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        master = {"X-Auth-Token": MASTER}
        # bootstrap CEO + สร้าง USER กับ ADMIN
        st, d = self._req("POST", "/api/admin/users",
                          {"username": "boss", "password": "password123", "role": "CEO"}, master)
        self.assertEqual(st, 200, d)
        st, d = self._req("POST", "/api/admin/users",
                          {"username": "alice", "password": "alicepass1", "role": "USER"}, master)
        self.assertEqual(st, 200, d)
        st, d = self._req("POST", "/api/admin/users",
                          {"username": "ops", "password": "opspass123", "role": "ADMIN"}, master)
        self.assertEqual(st, 200, d)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()
        session_store.clear()

    def _raw(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, raw, hdrs

    def _req(self, method, path, body=None, headers=None):
        st, raw, _ = self._raw(method, path, body, headers)
        return st, (json.loads(raw) if raw else {})

    def _login(self, username, password):
        return self._req("POST", "/api/auth/login", {"username": username, "password": password})

    # ---- login / logout ----
    def test_login_returns_session_token_usable_as_x_auth_token(self):
        st, d = self._login("alice", "alicepass1")
        self.assertEqual(st, 200, d)
        self.assertTrue(d["token"].startswith("lcs_"))
        self.assertEqual(d["role"], "USER")
        self.assertEqual(d["username"], "alice")
        st, me = self._req("GET", "/api/me", headers={"X-Auth-Token": d["token"]})
        self.assertEqual(st, 200, me)
        self.assertEqual(me["username"], "alice")
        self.assertEqual(me["role"], "USER")
        self.assertEqual(me["source"], "session")
        self.assertIsNotNone(me["expires_at"])

    def test_login_wrong_password_and_unknown_user_same_401(self):
        st, d1 = self._login("alice", "wrong-password")
        self.assertEqual(st, 401)
        st, d2 = self._login("nobody", "whatever12")
        self.assertEqual(st, 401)
        self.assertEqual(d1["error"], d2["error"])  # ไม่เผยว่ามี user นี้ไหม

    def test_login_missing_fields_400(self):
        st, _ = self._req("POST", "/api/auth/login", {"username": "alice"})
        self.assertEqual(st, 400)

    def test_login_bruteforce_locks_ip_429(self):
        for _ in range(session_store.LOGIN_MAX_FAILURES):
            st, _ = self._login("alice", "bad-password")
            self.assertEqual(st, 401)
        st, d = self._login("alice", "alicepass1")   # รหัสถูกก็ยังโดนล็อกชั่วคราว
        self.assertEqual(st, 429, d)

    def test_inactive_user_cannot_login(self):
        st, _ = self._req("POST", "/api/admin/users/active",
                          {"username": "alice", "active": False}, {"X-Auth-Token": MASTER})
        self.assertEqual(st, 200)
        st, _ = self._login("alice", "alicepass1")
        self.assertEqual(st, 401)

    def test_logout_revokes_session(self):
        _, d = self._login("alice", "alicepass1")
        hdr = {"X-Auth-Token": d["token"]}
        st, out = self._req("POST", "/api/auth/logout", headers=hdr)
        self.assertEqual(st, 200)
        self.assertTrue(out["revoked"])
        st, _ = self._req("GET", "/api/me", headers=hdr)
        self.assertEqual(st, 401)
        # logout ด้วย master token = ไม่มี session ให้เพิกถอน แต่ไม่ error
        st, out = self._req("POST", "/api/auth/logout", headers={"X-Auth-Token": MASTER})
        self.assertEqual(st, 200)
        self.assertFalse(out["revoked"])

    def test_session_user_rbac_on_admin_api(self):
        _, u = self._login("alice", "alicepass1")
        _, a = self._login("ops", "opspass123")
        st, _ = self._req("GET", "/api/admin/users", headers={"X-Auth-Token": u["token"]})
        self.assertEqual(st, 403)
        st, _ = self._req("GET", "/api/admin/users", headers={"X-Auth-Token": a["token"]})
        self.assertEqual(st, 200)

    # ---- page gate (/dev, /console) ----
    def test_protected_pages_redirect_without_identity(self):
        for page in ("/dev", "/console"):
            st, _, hdrs = self._raw("GET", page)
            self.assertEqual(st, 302, page)
            self.assertEqual(hdrs.get("location"), f"/login?next={page}")
            self.assertIn("no-store", hdrs.get("cache-control", ""))

    def test_protected_pages_forbidden_for_user_cookie(self):
        _, u = self._login("alice", "alicepass1")
        st, raw, _ = self._raw("GET", "/dev", headers={"Cookie": f"lca_key={u['token']}"})
        self.assertEqual(st, 403)
        self.assertIn("ADMIN", raw)

    def test_protected_pages_served_for_admin_cookie_or_header(self):
        _, a = self._login("ops", "opspass123")
        st, raw, _ = self._raw("GET", "/dev", headers={"Cookie": f"other=1; lca_key={a['token']}"})
        self.assertEqual(st, 200)
        self.assertIn("page-dev", raw)
        st, raw, _ = self._raw("GET", "/console", headers={"X-Auth-Token": a["token"]})
        self.assertEqual(st, 200)

    def test_cookie_is_not_accepted_for_api(self):
        # API ยัง header-only (กัน CSRF) — cookie อย่างเดียวต้อง 401
        _, a = self._login("ops", "opspass123")
        st, _ = self._req("GET", "/api/admin/users", headers={"Cookie": f"lca_key={a['token']}"})
        self.assertEqual(st, 401)

    def test_public_pages_still_open(self):
        for page in ("/", "/login", "/chat", "/support"):
            st, _, _ = self._raw("GET", page)
            self.assertEqual(st, 200, page)


class LocalModePageTest(unittest.TestCase):
    """โหมด local (ไม่ได้ตั้ง token): เปิดจาก loopback = เจ้าของเครื่อง → /dev ได้เลย"""

    def test_dev_served_in_local_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = server.make_handler(Path(tmp), None)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            port = httpd.server_address[1]
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/dev")
                resp = conn.getresponse()
                body = resp.read().decode("utf-8")
                conn.close()
                self.assertEqual(resp.status, 200)
                self.assertIn("__LCA_SESSION_TOKEN", body)
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
