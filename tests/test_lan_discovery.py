"""
test_lan_discovery.py — HTTP integration tests + unit tests for LAN discovery
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
from app import model_backend, lan_discovery  # noqa: E402

_ORIG_GENERATE = model_backend.generate

_FAKE_DISCOVERY = {
    "nodes": [
        {"ip": "192.168.1.50", "port": 8420, "url": "http://192.168.1.50:8420",
         "version": "0.2.3", "latency_ms": 12.5},
    ],
    "scanned": 255,
    "base_ip": "192.168.1.1",
    "elapsed_s": 1.2,
}


def _mock_discover(base_ip=None, port=8420, timeout=0.5, max_threads=50):
    return dict(_FAKE_DISCOVERY)


def _make_server(tmp_dir: Path):
    handler = server.make_handler(tmp_dir, None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, handler.session_token


class LanDiscoveryApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: f"MODEL={model}"
        )
        cls._orig_discover = lan_discovery.discover
        lan_discovery.discover = _mock_discover

    @classmethod
    def tearDownClass(cls):
        model_backend.generate = _ORIG_GENERATE
        lan_discovery.discover = cls._orig_discover

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.httpd, self.port, self.session_token = _make_server(self.root)
        # สร้าง ADMIN token
        import server as _srv
        handler_cls = _srv.make_handler(self.root, None)
        self.admin_token = handler_cls.session_token  # session token = ADMIN level in test mode

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

    def test_discover_requires_auth(self):
        st, _ = self._get("/api/nodes/discover", token="bad-token-xyz")
        self.assertIn(st, (401, 403))

    def test_discover_returns_200(self):
        st, _ = self._get("/api/nodes/discover", token=self.session_token)
        self.assertEqual(st, 200)

    def test_discover_shape(self):
        _, data = self._get("/api/nodes/discover", token=self.session_token)
        for key in ("nodes", "scanned", "base_ip", "elapsed_s"):
            self.assertIn(key, data, f"missing key: {key}")

    def test_discover_nodes_is_list(self):
        _, data = self._get("/api/nodes/discover", token=self.session_token)
        self.assertIsInstance(data["nodes"], list)

    def test_discover_scanned_is_int(self):
        _, data = self._get("/api/nodes/discover", token=self.session_token)
        self.assertIsInstance(data["scanned"], int)

    def test_discover_elapsed_is_number(self):
        _, data = self._get("/api/nodes/discover", token=self.session_token)
        self.assertIsInstance(data["elapsed_s"], (int, float))


class LanDiscoveryUnitTest(unittest.TestCase):
    """Unit tests สำหรับ lan_discovery functions โดยตรง"""

    def test_get_local_ips_returns_list(self):
        ips = lan_discovery.get_local_ips()
        self.assertIsInstance(ips, list)

    def test_discover_loopback_no_external(self):
        """สแกน 127.0.0.x/24 ด้วย timeout เล็กมาก — ไม่ควร crash ไม่ว่าจะหาเจอหรือไม่"""
        result = lan_discovery.discover(
            base_ip="127.0.0.1", port=19999, timeout=0.05, max_threads=4)
        self.assertIn("nodes", result)
        self.assertIn("scanned", result)
        self.assertIsInstance(result["nodes"], list)

    def test_discover_invalid_base_ip(self):
        result = lan_discovery.discover(base_ip="not-an-ip", port=8420, timeout=0.05)
        self.assertIn("error", result)
        self.assertEqual(result["nodes"], [])

    def test_discover_self_found(self):
        """เครื่องนี้รัน LCA server จริง — ถ้า discover ชี้ไปที่ 127.0.0.1 จะไม่เจอ
        (เพราะ 127.x ถูกกรองใน get_local_ips() แต่ _probe ยังรองรับ)
        ทดสอบว่า _probe คืน dict ที่ถูกต้องเมื่อ server ตอบ"""
        import http.server
        responses = []

        class _MockHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"version": "test-0.1"}')
            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        mock_port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            result = lan_discovery._probe("127.0.0.1", mock_port, timeout=1.0)
            self.assertIsNotNone(result)
            self.assertEqual(result["version"], "test-0.1")
            self.assertIn("ip", result)
            self.assertIn("url", result)
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()


class LanDiscoveryApiExtraTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: f"MODEL={model}"
        )
        cls._orig_discover = lan_discovery.discover
        lan_discovery.discover = _mock_discover

    @classmethod
    def tearDownClass(cls):
        model_backend.generate = _ORIG_GENERATE
        lan_discovery.discover = cls._orig_discover

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

    def test_discover_200_with_token(self):
        st, _ = self._get("/api/nodes/discover", token=self.session_token)
        self.assertEqual(st, 200)

    def test_discover_response_is_dict(self):
        _, data = self._get("/api/nodes/discover", token=self.session_token)
        self.assertIsInstance(data, dict)

    def test_discover_nodes_is_list(self):
        _, data = self._get("/api/nodes/discover", token=self.session_token)
        self.assertIsInstance(data["nodes"], list)

    def test_discover_scanned_matches_fake(self):
        _, data = self._get("/api/nodes/discover", token=self.session_token)
        self.assertEqual(data["scanned"], 255)

    def test_discover_no_token_401(self):
        st, _ = self._get("/api/nodes/discover")
        self.assertIn(st, (401, 403))

    def test_discover_base_ip_is_string(self):
        _, data = self._get("/api/nodes/discover", token=self.session_token)
        self.assertIsInstance(data["base_ip"], str)
