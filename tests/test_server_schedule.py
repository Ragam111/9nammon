"""test_server_schedule.py — integration test: schedule gate ปิด server นอกเวลาทำการ"""

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
from app import schedule_gate  # noqa: E402

MASTER_TOKEN = "master-token-for-test"


class ScheduleGateIntegrationTest(unittest.TestCase):
    def setUp(self):
        schedule_gate.invalidate_cache()  # กัน cache ข้ามเทส (optimization: TTL cache)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # ตั้ง auth_token เพื่อให้ anonymous request ไม่ fallback เป็น CEO
        # (ไม่งั้นทุก request จะ bypass gate เพราะ local mode = CEO)
        handler = server.make_handler(self.root, MASTER_TOKEN)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        # แทน status()/enabled() ให้ควบคุมได้
        self._orig_status = schedule_gate.status
        self._orig_enabled = schedule_gate.enabled

    def tearDown(self):
        schedule_gate.status = self._orig_status
        schedule_gate.enabled = self._orig_enabled
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        retry_after = resp.getheader("Retry-After")
        conn.close()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"_raw": raw}  # static route = HTML
        return resp.status, body, retry_after

    def _set_closed(self):
        schedule_gate.enabled = lambda root: True
        schedule_gate.status = lambda root, now_utc=None: {
            "enabled": True, "state": "closed", "open_hour": 6, "close_hour": 20,
            "next_change_at_th": "2026-10-30T06:00:00+07:00",
            "seconds_until_change": 3600,
            "message": "ปิดตามตารางเวลา",
        }

    def _set_open(self):
        schedule_gate.enabled = lambda root: True
        schedule_gate.status = lambda root, now_utc=None: {
            "enabled": True, "state": "open", "seconds_until_change": 3600,
        }

    def test_status_endpoint_public(self):
        status, body, _ = self._get("/api/status")
        self.assertEqual(status, 200)
        self.assertIn("state", body)

    def test_disabled_by_default_allows_health(self):
        # schedule_gate ปิดอยู่ (default) — /api/health public ต้องเข้าได้
        status, body, _ = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))

    def test_closed_blocks_anonymous_with_503(self):
        self._set_closed()
        status, body, retry = self._get("/api/me")  # endpoint ที่ไม่อยู่ใน allowlist
        self.assertEqual(status, 503)
        self.assertEqual(body["state"], "closed")
        self.assertEqual(retry, "3600")

    def test_closed_bypassed_by_ceo_master_token(self):
        self._set_closed()
        status, _, _ = self._get("/api/me",
                                 headers={"X-Auth-Token": MASTER_TOKEN})
        # CEO ผ่าน gate ได้ → endpoint ตอบปกติ (ไม่ใช่ 503)
        self.assertNotEqual(status, 503)

    def test_health_bypasses_gate_when_closed(self):
        self._set_closed()
        status, _, _ = self._get("/api/health")
        self.assertEqual(status, 200)

    def test_status_bypasses_gate_when_closed(self):
        self._set_closed()
        status, body, _ = self._get("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "closed")

    def test_static_route_bypasses_gate_when_closed(self):
        self._set_closed()
        status, _, _ = self._get("/")
        self.assertEqual(status, 200)

    def test_open_state_allows_requests(self):
        self._set_open()
        status, _, _ = self._get("/api/health")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
