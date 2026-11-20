"""
test_hw_meter_api.py — HTTP integration tests for GET /api/metrics/hw
"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
import unittest.mock
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import model_backend, hw_meter  # noqa: E402

_ORIG_GENERATE = model_backend.generate

_FAKE_SNAPSHOT = {
    "cpu_pct": 15.5,
    "cpu_per_core": [10.0, 20.0, 15.0, 17.0],
    "cpu_freq_mhz": 2800.0,
    "logical_cores": 4,
    "load_avg_1m": 0.5,
    "ram_pct": 42.0,
    "ram_used_gb": 6.6,
    "ram_total_gb": 15.7,
    "tier": "workstation",
    "tier_reasons": ["test tier"],
    "recommended_model": "qwen2.5-coder:7b",
}


def _mock_snapshot(project_root, interval: float = 0.2) -> dict:
    return dict(_FAKE_SNAPSHOT)


def _make_server(tmp_dir: Path):
    handler = server.make_handler(tmp_dir, None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, handler.session_token


class HwMeterApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: f"MODEL={model}"
        )
        cls._orig_snapshot = hw_meter.snapshot
        hw_meter.snapshot = _mock_snapshot

    @classmethod
    def tearDownClass(cls):
        model_backend.generate = _ORIG_GENERATE
        hw_meter.snapshot = cls._orig_snapshot

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

    def test_hw_meter_returns_200(self):
        st, _ = self._get("/api/metrics/hw", token=self.session_token)
        self.assertEqual(st, 200)

    def test_hw_meter_shape(self):
        _, data = self._get("/api/metrics/hw", token=self.session_token)
        for key in ("cpu_pct", "ram_pct", "ram_total_gb", "tier", "logical_cores"):
            self.assertIn(key, data, f"missing key: {key}")

    def test_hw_meter_requires_auth(self):
        st, _ = self._get("/api/metrics/hw", token="bad-token-xyz")
        self.assertIn(st, (401, 403))

    def test_hw_meter_tier_is_string(self):
        _, data = self._get("/api/metrics/hw", token=self.session_token)
        self.assertIsInstance(data["tier"], str)

    def test_hw_meter_cpu_pct_is_number(self):
        _, data = self._get("/api/metrics/hw", token=self.session_token)
        self.assertIsInstance(data["cpu_pct"], (int, float))

    def test_hw_meter_per_core_is_list(self):
        _, data = self._get("/api/metrics/hw", token=self.session_token)
        self.assertIsInstance(data["cpu_per_core"], list)


class HwMeterApiExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)
        with unittest.mock.patch.object(hw_meter, "snapshot", _mock_snapshot):
            self._handler_cls = server.make_handler(self._root, None)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_cls)
        self.port = self.httpd.server_address[1]
        self.session_token = self._handler_cls.session_token
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = {"X-Auth-Token": token} if token else {}
        conn.request("GET", path, headers=hdrs)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body) if body else {}

    def test_logical_cores_is_int(self):
        with unittest.mock.patch.object(hw_meter, "snapshot", _mock_snapshot):
            _, data = self._get("/api/metrics/hw", token=self.session_token)
        self.assertIsInstance(data["logical_cores"], int)

    def test_ram_total_gb_is_number(self):
        with unittest.mock.patch.object(hw_meter, "snapshot", _mock_snapshot):
            _, data = self._get("/api/metrics/hw", token=self.session_token)
        self.assertIsInstance(data["ram_total_gb"], (int, float))

    def test_recommended_model_is_string(self):
        with unittest.mock.patch.object(hw_meter, "snapshot", _mock_snapshot):
            _, data = self._get("/api/metrics/hw", token=self.session_token)
        self.assertIsInstance(data["recommended_model"], str)

    def test_values_match_fake_snapshot(self):
        with unittest.mock.patch.object(hw_meter, "snapshot", _mock_snapshot):
            _, data = self._get("/api/metrics/hw", token=self.session_token)
        self.assertEqual(data["cpu_pct"], _FAKE_SNAPSHOT["cpu_pct"])
        self.assertEqual(data["tier"], _FAKE_SNAPSHOT["tier"])


if __name__ == "__main__":
    unittest.main()
