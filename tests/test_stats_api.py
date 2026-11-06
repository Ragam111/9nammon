"""
test_stats_api.py — HTTP integration tests for GET /api/admin/stats

ทดสอบว่า server คืน snapshot สถิติ request/response ถูกต้อง:
- โครงข้อมูล, RBAC, error_rate type, total เพิ่มหลังยิง request
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
from app import model_backend  # noqa: E402


def _make_server(tmp_dir: Path):
    handler = server.make_handler(tmp_dir, None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, handler.session_token


class StatsApiTest(unittest.TestCase):
    """GET /api/admin/stats — ADMIN-gated stats snapshot"""

    @classmethod
    def setUpClass(cls):
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: f"MODEL={model}"
        )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.httpd, self.port, self.session_token = _make_server(self.root)

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
        return resp.status, json.loads(body) if body else {}

    # ── basic 200 + shape ───────────────────────────────────────────────────

    def test_stats_returns_200(self):
        # local bind + session token = CEO auto → ADMIN
        st, _ = self._get("/api/admin/stats", token=self.session_token)
        self.assertEqual(st, 200)

    def test_stats_shape(self):
        _, data = self._get("/api/admin/stats", token=self.session_token)
        for key in ("total_requests", "total_errors", "error_rate", "last_24h", "by_endpoint"):
            self.assertIn(key, data, f"missing key: {key}")

    def test_stats_error_rate_is_float(self):
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertIsInstance(data["error_rate"], float)

    # ── RBAC ────────────────────────────────────────────────────────────────

    def test_stats_requires_auth_token(self):
        # ไม่ส่ง token เลย (not CEO bind, not token) — ต้องได้ 401
        # NOTE: local bind = CEO-auto, so we need a server with an actual token set
        # ทดสอบด้วยการส่ง token ผิด
        st, data = self._get("/api/admin/stats", token="wrong-token-xyz")
        self.assertIn(st, (401, 403), f"ต้องได้ 401/403 ด้วย token ผิด แต่ได้ {st}")

    # ── accumulation ────────────────────────────────────────────────────────

    def test_stats_total_increases_after_requests(self):
        # เรียก /api/health สองครั้ง แล้วดู total_requests เพิ่มขึ้น
        self._get("/api/health")
        self._get("/api/health")
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertGreaterEqual(data["total_requests"], 2)

    def test_stats_by_endpoint_contains_entries_after_requests(self):
        # ยิง /api/health ก่อน แล้วตรวจว่า by_endpoint มี entry
        self._get("/api/health")
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertIsInstance(data["by_endpoint"], list)
        # ต้องมี entry อย่างน้อย 1 (อย่างน้อย /api/health หรือ /api/admin/stats)
        self.assertGreater(len(data["by_endpoint"]), 0)


class StatsApiExtraTest(unittest.TestCase):
    """ทดสอบ response shape ละเอียดขึ้น และ type checking"""

    @classmethod
    def setUpClass(cls):
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: f"MODEL={model}"
        )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.httpd, self.port, self.session_token = _make_server(self.root)

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
        return resp.status, json.loads(body) if body else {}

    def test_stats_total_requests_is_int(self):
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertIsInstance(data["total_requests"], int)

    def test_stats_total_errors_is_int(self):
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertIsInstance(data["total_errors"], int)

    def test_stats_last_24h_is_int(self):
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertIsInstance(data["last_24h"], int)
        self.assertGreaterEqual(data["last_24h"], 0)

    def test_stats_by_endpoint_is_list(self):
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertIsInstance(data["by_endpoint"], list)

    def test_stats_error_rate_non_negative(self):
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertGreaterEqual(data["error_rate"], 0.0)

    def test_stats_total_errors_non_negative(self):
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertGreaterEqual(data["total_errors"], 0)

    def test_stats_total_requests_non_negative(self):
        _, data = self._get("/api/admin/stats", token=self.session_token)
        self.assertGreaterEqual(data["total_requests"], 0)


if __name__ == "__main__":
    unittest.main()
