"""Host / Origin / per-launch session token สำหรับ server ที่ bind loopback.

ยืนยันช่องโหว่เดิม: ไม่ตั้ง token = CEO และไม่ตรวจ Origin/Host
แล้วล็อกพฤติกรรมหลังแก้ — 403 เมื่อ Host/Origin แปลก, 401 เมื่อไม่มี session token
"""

import json
import http.client
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

MASTER_TOKEN = "secret-master-token-abcdefghij"


class LocalSessionGuardTest(unittest.TestCase):
    """make_handler(..., None) — โหมด local ไม่ได้ตั้ง token"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.handler = server.make_handler(Path(self._tmp.name), None)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.token = getattr(self.handler, "session_token", None)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = None
        hdrs = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        cors = resp.getheader("Access-Control-Allow-Origin")
        status = resp.status
        conn.close()
        return status, raw, cors

    def _auth(self, extra=None):
        hdrs = dict(extra or {})
        if self.token:
            hdrs["X-Auth-Token"] = self.token
        return hdrs

    def test_cross_origin_post_rejected(self):
        # เว็บอื่นยิงมาที่ loopback (มีหรือไม่มี token) ต้องไม่เปลี่ยน state
        status, raw, cors = self._req(
            "POST", "/api/todos", {"text": "from-evil-origin"},
            self._auth({"Origin": "https://evil.example"}))
        self.assertEqual(status, 403, raw)
        self.assertIsNone(cors)
        self.assertNotIn(b"Access-Control-Allow-Origin", raw)
        listed, body, _ = self._req("GET", "/api/todos", headers=self._auth())
        self.assertEqual(listed, 200, body)
        self.assertNotIn(b"from-evil-origin", body)

    def test_evil_host_rejected(self):
        status, raw, _ = self._req(
            "POST", "/api/todos", {"text": "from-evil-host"},
            self._auth({"Host": f"evil.example:{self.port}"}))
        self.assertEqual(status, 403, raw)
        status, raw, _ = self._req(
            "GET", "/api/version", headers={"Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403, raw)
        status, raw, _ = self._req(
            "GET", "/api/version", headers={"Host": "evil.example"})
        self.assertEqual(status, 403, raw)

    def test_host_without_listen_port_rejected(self):
        status, raw, _ = self._req(
            "GET", "/api/version", headers={"Host": "127.0.0.1"})
        self.assertEqual(status, 403, raw)
        status, raw, _ = self._req(
            "GET", "/api/version", headers={"Host": f"127.0.0.1:{self.port + 1}"})
        self.assertEqual(status, 403, raw)

    def test_loopback_hosts_allowed_for_public_version(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"):
            status, raw, cors = self._req("GET", "/api/version", headers={"Host": host})
            self.assertEqual(status, 200, (host, raw))
            self.assertIn(b'"version"', raw)
            self.assertIsNone(cors)

    def test_same_origin_post_allowed_with_session_token(self):
        status, raw, cors = self._req(
            "POST", "/api/todos", {"text": "same-origin"},
            self._auth({"Origin": f"http://127.0.0.1:{self.port}"}))
        self.assertEqual(status, 200, raw)
        self.assertIsNone(cors)
        self.assertIn(b"same-origin", raw)

    def test_localhost_origin_allowed(self):
        status, raw, _ = self._req(
            "POST", "/api/todos", {"text": "via-localhost"},
            self._auth({"Origin": f"http://localhost:{self.port}"}))
        self.assertEqual(status, 200, raw)

    def test_missing_origin_cli_allowed_only_with_token(self):
        # ไม่มี Origin = ไคลเอนต์ที่ไม่ใช่เบราว์เซอร์ (curl/CLI) — ยังต้องมี token
        status, raw, _ = self._req("POST", "/api/todos", {"text": "cli-no-token"})
        self.assertEqual(status, 401, raw)
        status, raw, _ = self._req(
            "POST", "/api/todos", {"text": "cli-with-token"}, self._auth())
        self.assertEqual(status, 200, raw)

    def test_auto_session_token_required_for_privileged(self):
        self.assertTrue(self.token)
        self.assertTrue(getattr(self.handler, "session_token_auto", False))
        status, raw, _ = self._req("GET", "/api/me")
        self.assertEqual(status, 401, raw)
        status, raw, _ = self._req("GET", "/api/me", headers={"X-Auth-Token": "wrong"})
        self.assertEqual(status, 401, raw)
        status, raw, _ = self._req("GET", "/api/me", headers=self._auth())
        self.assertEqual(status, 200, raw)
        me = json.loads(raw)
        self.assertEqual(me["role"], "CEO")
        # session ที่สุ่มให้โหมด local ยังเป็นตัวตน local เดิม (ไม่ใช่ master token ที่ผู้ใช้ตั้ง)
        self.assertEqual(me["username"], "__local__")

    def test_public_version_and_health_stay_open(self):
        # /api/version คง public: ไม่มี token/path/ข้อมูลผู้ใช้. python version เป็นของเดิมสำหรับ support
        status, raw, _ = self._req("GET", "/api/version")
        self.assertEqual(status, 200, raw)
        data = json.loads(raw)
        self.assertIn("version", data)
        self.assertIn("python", data)
        self.assertNotIn("token", data)
        status, raw, _ = self._req("GET", "/api/health")
        self.assertEqual(status, 200, raw)

    def test_html_receives_session_token_for_the_ui(self):
        status, raw, cors = self._req("GET", "/")
        self.assertEqual(status, 200, raw)
        self.assertIsNone(cors)
        self.assertIn(b"window.__LCA_SESSION_TOKEN=", raw)
        self.assertIn(self.token.encode("utf-8"), raw)
        # asset ที่ cache ได้ต้องไม่ฝัง token
        status, js, _ = self._req("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertNotIn(self.token.encode("utf-8"), js)

    def test_upgrade_and_unused_write_methods_reject_cross_origin(self):
        status, raw, cors = self._req(
            "GET", "/",
            headers=self._auth({
                "Origin": "https://evil.example",
                "Upgrade": "websocket",
                "Connection": "Upgrade",
            }))
        self.assertEqual(status, 403, raw)
        self.assertIsNone(cors)
        status, raw, _ = self._req(
            "PUT", "/api/todos", {"text": "put"},
            self._auth({"Origin": "https://evil.example"}))
        self.assertEqual(status, 403, raw)
        status, raw, _ = self._req(
            "PATCH", "/api/todos", {"text": "patch"},
            self._auth({"Origin": "http://127.0.0.1:" + str(self.port)}))
        self.assertEqual(status, 404, raw)
        status, raw, _ = self._req(
            "DELETE", "/api/todos", headers=self._auth())
        self.assertEqual(status, 404, raw)


class ConfiguredTokenUnchangedTest(unittest.TestCase):
    """ตั้ง master token เอง — เส้นทางเดิมต้องเหมือนเดิม และไม่ฝัง token ลงหน้าเว็บ"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.handler = server.make_handler(Path(self._tmp.name), MASTER_TOKEN)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = None
        hdrs = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
        conn.close()
        return status, raw

    def test_configured_token_is_not_replaced_or_injected(self):
        self.assertEqual(self.handler.session_token, MASTER_TOKEN)
        self.assertFalse(self.handler.session_token_auto)
        status, raw = self._req("GET", "/")
        self.assertEqual(status, 200, raw)
        self.assertNotIn(MASTER_TOKEN.encode("utf-8"), raw)
        self.assertNotIn(b"__LCA_SESSION_TOKEN", raw)

    def test_master_token_still_grants_ceo_and_wrong_token_does_not(self):
        status, raw = self._req("GET", "/api/me")
        self.assertEqual(status, 401, raw)
        status, raw = self._req("GET", "/api/me", headers={"X-Auth-Token": "nope"})
        self.assertEqual(status, 401, raw)
        status, raw = self._req("GET", "/api/me", headers={"X-Auth-Token": MASTER_TOKEN})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)["role"], "CEO")
        status, raw = self._req(
            "POST", "/api/todos", {"text": "owned"},
            {"X-Auth-Token": MASTER_TOKEN, "Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(status, 200, raw)
        # token ถูกก็ยังห้าม cross-origin
        status, raw = self._req(
            "POST", "/api/todos", {"text": "stolen"},
            {"X-Auth-Token": MASTER_TOKEN, "Origin": "https://evil.example"})
        self.assertEqual(status, 403, raw)


class HostOriginPolicyTest(unittest.TestCase):
    def test_wildcard_bind_allows_lan_host_on_listen_port(self):
        self.assertTrue(server.host_header_allowed("192.168.1.5:8420", 8420, "0.0.0.0"))
        self.assertTrue(server.host_header_allowed("127.0.0.1:8420", 8420, "0.0.0.0"))
        self.assertFalse(server.host_header_allowed("192.168.1.5:9", 8420, "0.0.0.0"))
        self.assertTrue(server.origin_header_allowed(
            "http://192.168.1.5:8420", 8420, "0.0.0.0", "192.168.1.5:8420"))
        self.assertFalse(server.origin_header_allowed(
            "https://evil.example", 8420, "0.0.0.0", "192.168.1.5:8420"))

    def test_loopback_bind_rejects_lan_name(self):
        self.assertFalse(server.host_header_allowed("192.168.1.5:8420", 8420, "127.0.0.1"))
        self.assertTrue(server.host_header_allowed("[::1]:8420", 8420, "127.0.0.1"))
        self.assertTrue(server.origin_header_allowed(
            "http://[::1]:8420", 8420, "127.0.0.1", "[::1]:8420"))
        self.assertFalse(server.origin_header_allowed(
            "null", 8420, "127.0.0.1", "127.0.0.1:8420"))

    def test_explicit_non_loopback_bind_is_allowlisted(self):
        self.assertTrue(server.host_header_allowed("192.168.1.5:8420", 8420, "192.168.1.5"))
        self.assertTrue(server.host_header_allowed("localhost:8420", 8420, "192.168.1.5"))
        self.assertFalse(server.host_header_allowed("evil.example:8420", 8420, "192.168.1.5"))


if __name__ == "__main__":
    unittest.main()
