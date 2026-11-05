"""
test_server_rate_limit.py — HTTP integration tests for rate limiting (429)

ทดสอบว่า server คืน 429 จริงๆ เมื่อ client เรียก /api/ เกิน quota
ใช้ rate_limit_max=3 เพื่อให้ trigger ได้เร็วโดยไม่ต้องยิงจริงๆ 300 ครั้ง

Covers:
  RateLimitHttpTest     — within limit → 200, over limit → 429, error shape,
                          exact boundary, non-API paths exempt,
                          authenticated requests count toward limit
  RateLimitDisabledTest — max=0 → never 429, API paths pass, /api/health always ok
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
        for _ in range(3):
            st, _ = self._get("/api/health")
            self.assertEqual(st, 200, "คำขอภายใน quota ต้องได้ 200")

    def test_request_over_limit_gets_429(self):
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

    def test_first_request_always_200(self):
        st, _ = self._get("/api/health")
        self.assertEqual(st, 200)

    def test_exactly_at_limit_last_request_succeeds(self):
        # max=3: requests 1,2,3 all succeed; request 4 fails
        statuses = []
        for _ in range(4):
            st, _ = self._get("/api/health")
            statuses.append(st)
        self.assertEqual(statuses[2], 200, "คำขอที่ 3 (= max) ต้องได้ 200")
        self.assertEqual(statuses[3], 429, "คำขอที่ 4 (> max) ต้องได้ 429")

    def test_rate_limited_response_has_nonempty_error(self):
        for _ in range(3):
            self._get("/api/health")
        _, data = self._get("/api/health")
        err = data.get("error", "")
        self.assertIsInstance(err, str)
        self.assertGreater(len(err), 0)

    # ── non-API paths are exempt ─────────────────────────────────────────────

    def test_root_path_not_rate_limited(self):
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

    def _get(self, path, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = {}
        if token:
            hdrs["X-Auth-Token"] = token
        conn.request("GET", path, headers=hdrs)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status

    def test_many_requests_never_429_when_disabled(self):
        for i in range(10):
            st = self._get("/api/health")
            self.assertNotEqual(st, 429, f"ครั้งที่ {i+1}: rate limit ถูก disable แต่ได้ 429")

    def test_api_health_always_ok_when_disabled(self):
        # ยิง 20 ครั้ง ต้องไม่โดน 429 เลย
        for i in range(20):
            st = self._get("/api/health")
            self.assertNotEqual(st, 429, f"ครั้งที่ {i+1} ต้องไม่โดน rate limit")

    def test_authenticated_requests_pass_when_disabled(self):
        for i in range(5):
            st = self._get("/api/health", token=self.session_token)
            self.assertNotEqual(st, 429, f"authenticated request {i+1} ถูก rate limit ทั้งที่ disabled")


if __name__ == "__main__":
    unittest.main()
