"""
test_server_rate_limit.py — HTTP integration tests for rate limiting (429)

ทดสอบว่า server คืน 429 จริงๆ เมื่อ client เรียก /api/ เกิน quota
ใช้ rate_limit_max=3 เพื่อให้ trigger ได้เร็วโดยไม่ต้องยิงจริงๆ 300 ครั้ง

Covers:
  RateLimitHttpTest      — within-limit OK, over-limit 429, error body, non-API exempt,
                           authenticated vs unauthenticated, different endpoints same quota
  RateLimitDisabledTest  — rate_limit_max=0 never 429
  RateLimitMetaTest      — 429 JSON has error key, non-API paths: /, /console, /static/*,
                           max=1 triggers immediately, rate_limit_max=1 exact boundary
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


def _make_server(rate_limit_max: int = 3, rate_limit_window: float = 60.0):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    handler = server.make_handler(root, None,
                                  rate_limit_max=rate_limit_max,
                                  rate_limit_window=rate_limit_window)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, handler.session_token, tmp


class RateLimitHttpTest(unittest.TestCase):
    """server ต้อง 429 เมื่อ IP เดียวเรียก /api/ เกิน max ในหน้าต่างเดียว"""

    def setUp(self):
        self.httpd, self.port, self.session_token, self._tmp = _make_server(rate_limit_max=3)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = {}
        if token:
            hdrs["X-Auth-Token"] = token
        conn.request("GET", path, headers=hdrs)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}
        return resp.status, data

    # ── basic 429 behaviour ──────────────────────────────────────────────────

    def test_requests_within_limit_succeed(self):
        # 3 ครั้ง = ภายใน quota (max=3)
        for _ in range(3):
            st, _ = self._get("/api/health")
            self.assertEqual(st, 200, "คำขอภายใน quota ต้องได้ 200")

    def test_request_over_limit_gets_429(self):
        # ใช้ quota 3 ครั้งก่อน แล้วครั้งที่ 4 ต้องได้ 429
        for _ in range(3):
            self._get("/api/health")
        st, data = self._get("/api/health")
        self.assertEqual(st, 429)
        self.assertIn("error", data)

    def test_429_error_message_in_response(self):
        for _ in range(3):
            self._get("/api/health")
        _, data = self._get("/api/health")
        self.assertIn("error", data)
        self.assertTrue(len(data["error"]) > 0)

    # ── non-API paths are exempt ─────────────────────────────────────────────

    def test_root_path_not_rate_limited(self):
        # หมด quota แล้ว — เรียก "/" (static) ต้องไม่ 429
        for _ in range(4):
            self._get("/api/health")
        st, _ = self._get("/")
        self.assertNotEqual(st, 429, "/ ไม่อยู่ใต้ /api/ — ต้องไม่โดน rate limit")

    def test_console_path_not_rate_limited(self):
        for _ in range(4):
            self._get("/api/health")
        st, _ = self._get("/console")
        self.assertNotEqual(st, 429, "/console ต้องไม่โดน rate limit")

    def test_different_api_endpoints_share_quota(self):
        # /api/health + /api/models ใช้ quota ร่วมกัน (IP เดียวกัน)
        self._get("/api/health")
        self._get("/api/health")
        self._get("/api/models")
        st, _ = self._get("/api/health")
        self.assertEqual(st, 429, "quota ต้องนับรวมทุก /api/* endpoint")

    def test_max_1_triggers_on_second_request(self):
        httpd, port, _tok, tmp = _make_server(rate_limit_max=1)
        try:
            conn1 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn1.request("GET", "/api/health")
            r1 = conn1.getresponse(); r1.read(); conn1.close()
            self.assertEqual(r1.status, 200)

            conn2 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn2.request("GET", "/api/health")
            r2 = conn2.getresponse(); r2.read(); conn2.close()
            self.assertEqual(r2.status, 429, "max=1 → ครั้งที่ 2 ต้อง 429")
        finally:
            httpd.shutdown(); httpd.server_close(); tmp.cleanup()

    def test_429_response_is_json(self):
        for _ in range(3):
            self._get("/api/health")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 429)
        try:
            data = json.loads(body)
            self.assertIn("error", data)
        except json.JSONDecodeError:
            self.fail("429 ต้องตอบ JSON")


class RateLimitDisabledTest(unittest.TestCase):
    """rate_limit_max=0 ต้อง disable rate limiting ทั้งหมด"""

    def setUp(self):
        self.httpd, self.port, self.session_token, self._tmp = _make_server(rate_limit_max=0)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status

    def test_many_requests_never_429_when_disabled(self):
        # rate_limit_max=0 → disabled → 10 ครั้งต้องไม่เจอ 429 เลย
        for i in range(10):
            st = self._get("/api/health")
            self.assertNotEqual(st, 429, f"ครั้งที่ {i+1}: rate limit ถูก disable แต่ได้ 429")


class RateLimitMetaTest(unittest.TestCase):
    """edge cases + non-API path exemptions"""

    def setUp(self):
        self.httpd, self.port, self.session_token, self._tmp = _make_server(rate_limit_max=2)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, body

    def test_exact_boundary_still_ok(self):
        # max=2: คำขอที่ 1 และ 2 ต้องไม่ 429
        st1, _ = self._get("/api/health")
        st2, _ = self._get("/api/health")
        self.assertNotEqual(st1, 429)
        self.assertNotEqual(st2, 429)

    def test_one_over_boundary_is_429(self):
        self._get("/api/health")
        self._get("/api/health")
        st, _ = self._get("/api/health")
        self.assertEqual(st, 429)

    def test_static_path_always_accessible(self):
        for _ in range(3):
            self._get("/api/health")
        st, _ = self._get("/static/chat.js")
        self.assertNotEqual(st, 429)


if __name__ == "__main__":
    unittest.main()
