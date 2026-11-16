"""Host/Origin หลัง reverse proxy (Render, HF Spaces, Docker, cloudflared) + LCA_ALLOWED_HOSTS
+ X-Frame-Options / CSP frame-ancestors บนหน้า HTML.

wildcard bind (0.0.0.0 / ::) บังคับ token อยู่แล้ว จึงรับ Host ที่ไม่มีพอร์ต และเทียบ Origin
กับ Host โดยไม่สนพอร์ต. loopback ยังเข้มเหมือนเดิม.
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

TOKEN = "proxy-test-master-token-0123456789"


class WildcardPolicyUnitTest(unittest.TestCase):
    def test_cloud_host_without_port_passes_in_wildcard_mode(self):
        for bind in ("0.0.0.0", "::"):
            self.assertTrue(server.host_header_allowed("lca.onrender.com", 8420, bind, frozenset()))
            self.assertTrue(server.host_header_allowed("lca.onrender.com:443", 8420, bind, frozenset()))
            self.assertTrue(server.host_header_allowed("x.hf.space:8420", 8420, bind, frozenset()))

    def test_wildcard_still_rejects_odd_port_and_garbage(self):
        self.assertFalse(server.host_header_allowed("lca.onrender.com:9999", 8420, "0.0.0.0", frozenset()))
        self.assertFalse(server.host_header_allowed("", 8420, "0.0.0.0", frozenset()))

    def test_https_origin_matches_host_ignoring_port(self):
        self.assertTrue(server.origin_header_allowed(
            "https://lca.onrender.com", 8420, "0.0.0.0", "lca.onrender.com", frozenset()))
        self.assertTrue(server.origin_header_allowed(
            "https://lca.onrender.com", 8420, "0.0.0.0", "lca.onrender.com:443", frozenset()))

    def test_foreign_origin_rejected_in_wildcard_mode(self):
        self.assertFalse(server.origin_header_allowed(
            "https://evil.example", 8420, "0.0.0.0", "lca.onrender.com", frozenset()))
        self.assertFalse(server.origin_header_allowed(
            "null", 8420, "0.0.0.0", "lca.onrender.com", frozenset()))
        # loopback origin บน wildcard ต้องพอร์ตตรงเหมือนเดิม
        self.assertFalse(server.origin_header_allowed(
            "http://127.0.0.1:9999", 8420, "0.0.0.0", "lca.onrender.com", frozenset()))

    def test_loopback_stays_strict(self):
        self.assertFalse(server.host_header_allowed("127.0.0.1", 8420, "127.0.0.1", frozenset()))
        self.assertFalse(server.host_header_allowed("localhost:443", 8420, "127.0.0.1", frozenset()))
        self.assertFalse(server.host_header_allowed("evil.example:8420", 8420, "127.0.0.1", frozenset()))
        self.assertFalse(server.origin_header_allowed(
            "https://localhost:8420", 8420, "127.0.0.1", "localhost:8420", frozenset()))


class AllowedHostsUnitTest(unittest.TestCase):
    def test_parse_allowed_hosts(self):
        got = server.parse_allowed_hosts(" A.trycloudflare.com , b.example:443,[fd00::1],,localhost,bad@x ")
        self.assertEqual(got, frozenset({"a.trycloudflare.com", "b.example", "fd00::1"}))
        self.assertEqual(server.parse_allowed_hosts(None), frozenset())

    def test_allow_list_admits_named_host_on_loopback_bind(self):
        allowed = server.parse_allowed_hosts("a.trycloudflare.com")
        self.assertTrue(server.host_header_allowed("a.trycloudflare.com", 8420, "127.0.0.1", allowed))
        self.assertTrue(server.origin_header_allowed(
            "https://a.trycloudflare.com", 8420, "127.0.0.1", "a.trycloudflare.com", allowed))
        self.assertFalse(server.host_header_allowed("b.trycloudflare.com", 8420, "127.0.0.1", allowed))
        self.assertFalse(server.origin_header_allowed(
            "https://b.trycloudflare.com", 8420, "127.0.0.1", "a.trycloudflare.com", allowed))

    def test_loopback_names_cannot_be_relaxed_by_allow_list(self):
        allowed = server.parse_allowed_hosts("localhost,127.0.0.1")
        self.assertFalse(server.host_header_allowed("localhost", 8420, "127.0.0.1", allowed))


class _LiveServer(unittest.TestCase):
    bind = "127.0.0.1"
    token = None
    env = {}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        with mock.patch.dict(os.environ, self.env, clear=False):
            self.handler = server.make_handler(Path(self._tmp.name), self.token, bind_host=self.bind)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _req(self, method, path, headers, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        hdrs = dict(headers)
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        out = (resp.status, raw, {k.lower(): v for k, v in resp.getheaders()})
        conn.close()
        return out


class WildcardLiveTest(_LiveServer):
    """handler ที่คิดว่า bind 0.0.0.0 + master token (เหมือน Docker/Render)"""
    bind = "0.0.0.0"
    token = TOKEN

    def test_cloud_host_without_port_serves_page_without_token_injection(self):
        status, raw, hdrs = self._req("GET", "/", {"Host": "lca.onrender.com"})
        self.assertEqual(status, 200, raw)
        self.assertNotIn(TOKEN.encode(), raw)

    def test_cloud_https_origin_post_passes_and_foreign_origin_403(self):
        base = {"Host": "lca.onrender.com", "X-Auth-Token": TOKEN}
        ok, raw, _ = self._req("POST", "/api/todos",
                               dict(base, Origin="https://lca.onrender.com"), {"text": "ok"})
        self.assertEqual(ok, 200, raw)
        bad, raw, _ = self._req("POST", "/api/todos",
                                dict(base, Origin="https://evil.example"), {"text": "evil"})
        self.assertEqual(bad, 403, raw)


class AllowListLiveTest(_LiveServer):
    """loopback bind + LCA_ALLOWED_HOSTS (เช่น cloudflared → localhost)"""
    env = {"LCA_ALLOWED_HOSTS": "a.trycloudflare.com"}

    def test_allowed_tunnel_host_gets_page_but_no_session_token(self):
        status, raw, _ = self._req("GET", "/", {"Host": "a.trycloudflare.com"})
        self.assertEqual(status, 200, raw)
        self.assertNotIn(self.handler.session_token.encode(), raw)
        # API ยังต้องมี token
        status, raw, _ = self._req("GET", "/api/me", {"Host": "a.trycloudflare.com"})
        self.assertEqual(status, 401, raw)

    def test_unlisted_host_and_foreign_origin_still_403(self):
        status, raw, _ = self._req("GET", "/", {"Host": "b.trycloudflare.com"})
        self.assertEqual(status, 403, raw)
        status, raw, _ = self._req(
            "POST", "/api/todos",
            {"Host": "a.trycloudflare.com", "Origin": "https://evil.example",
             "X-Auth-Token": self.handler.session_token}, {"text": "x"})
        self.assertEqual(status, 403, raw)

    def test_loopback_still_gets_session_token(self):
        status, raw, _ = self._req("GET", "/", {"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(status, 200, raw)
        self.assertIn(self.handler.session_token.encode(), raw)


class FrameHeadersLiveTest(_LiveServer):
    def test_html_has_anti_framing_headers(self):
        for path in ("/", "/console", "/login", "/dev"):
            status, raw, hdrs = self._req("GET", path, {"Host": f"127.0.0.1:{self.port}"})
            self.assertEqual(status, 200, (path, raw[:200]))
            self.assertEqual(hdrs.get("x-frame-options"), "DENY", path)
            self.assertEqual(hdrs.get("content-security-policy"), "frame-ancestors 'none'", path)

    def test_non_html_asset_has_no_csp(self):
        status, _raw, hdrs = self._req("GET", "/app.js", {"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(status, 200)
        self.assertNotIn("content-security-policy", hdrs)


if __name__ == "__main__":
    unittest.main()
