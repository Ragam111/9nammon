"""
test_server_rate_limit.py — HTTP integration tests for rate limiting (429)

ทดสอบว่า server คืน 429 จริงๆ เมื่อ client เรียก /api/ เกิน quota
ใช้ rate_limit_max=3 เพื่อให้ trigger ได้เร็วโดยไม่ต้องยิงจริงๆ 300 ครั้ง
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
    """สามารถ 429 เมื่อ IP เดียวเรียก /api/ เกิน max ในหน้าต่างเดียว"""

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

    # ── basic 429 behaviour ───────────────────────────────────────────────────

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

    # ── non-API paths are exempt ──────────────────────────────────────────────

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


if __name__ == "__main__":
    unittest.main()


class RateLimitServerExtraTest(unittest.TestCase):
    """Extra coverage: basic sanity checks on rate-limited and unlimited servers."""

    def setUp(self):
        self.httpd, self.port, self.session_token, self._tmp = _make_server(rate_limit_max=5)

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
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}
        return resp.status, data

    def test_first_api_request_is_200(self):
        st, _ = self._get("/api/health")
        self.assertEqual(st, 200)

    def test_second_api_request_is_200(self):
        self._get("/api/health")
        st, _ = self._get("/api/health")
        self.assertEqual(st, 200)

    def test_rate_limit_response_code_is_int(self):
        st, _ = self._get("/api/health")
        self.assertIsInstance(st, int)

    def test_blocked_response_has_error_key(self):
        # exhaust the 5-request quota then check blocked response has 'error'
        for _ in range(5):
            self._get("/api/health")
        _, data = self._get("/api/health")
        self.assertIn("error", data)

    def test_unlimited_server_first_request_200(self):
        httpd, port, _, tmp = _make_server(rate_limit_max=0)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            self.assertEqual(resp.status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()
            tmp.cleanup()

    def test_unlimited_server_fifth_request_not_429(self):
        httpd, port, _, tmp = _make_server(rate_limit_max=0)
        try:
            for _ in range(5):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/health")
                resp = conn.getresponse()
                st = resp.status
                resp.read()
                conn.close()
            self.assertNotEqual(st, 429)
        finally:
            httpd.shutdown()
            httpd.server_close()
            tmp.cleanup()
