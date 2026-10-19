"""
test_server_health.py — integration test ของ GET /api/health (สัญญาณชีพระบบ)

สตาร์ท server จริงบนพอร์ตสุ่ม mock call_ollama ไว้ ไม่ต้องมี Ollama จริง
(/api/health เป็น public ไม่ต้อง auth — เช็กว่าคืนโครงถูกต้อง)
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


class ServerHealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.call_ollama = lambda model, messages, num_ctx=8192: "mocked-reply"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        handler = server.make_handler(root, None)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        return resp.status, json.loads(raw) if raw else {}

    def test_health_ok_and_shape(self):
        st, data = self._get("/api/health")
        self.assertEqual(st, 200)
        self.assertTrue(data["ok"])
        self.assertIn(data["ollama"], ("up", "down"))
        self.assertIsInstance(data["ram_pressure"], bool)
        self.assertTrue(data["recommended_model"].startswith("qwen2.5-coder:"))
        self.assertIn("backend", data)
        # default backend = cpu (ยังไม่ได้ตั้ง config)
        self.assertEqual(data["backend"]["backend"], "cpu")

    def test_health_public_no_auth_needed(self):
        # ไม่แนบ token ก็ต้องได้ 200 (เป็น liveness endpoint)
        st, _ = self._get("/api/health")
        self.assertEqual(st, 200)


if __name__ == "__main__":
    unittest.main()
