"""
test_cluster_sync.py — HTTP integration tests + unit tests for cluster sync
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
from app import cluster_sync, lan_discovery, model_backend  # noqa: E402

_ORIG_GENERATE = model_backend.generate

_FAKE_SYNC = {
    "added": [
        {"name": "lca-192.168.1.50", "url": "http://192.168.1.50:8420", "version": "0.2.4"},
    ],
    "existing": [],
    "scanned": 255,
    "elapsed_s": 1.1,
}


def _mock_sync(project_root, base_ip=None, port=8420, timeout=0.5, max_threads=50):
    return dict(_FAKE_SYNC)


def _make_server(tmp_dir: Path):
    handler = server.make_handler(tmp_dir, None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, handler.session_token


class ClusterSyncApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: f"MODEL={model}"
        )
        cls._orig_sync = cluster_sync.sync_discovered
        cluster_sync.sync_discovered = _mock_sync

    @classmethod
    def tearDownClass(cls):
        model_backend.generate = _ORIG_GENERATE
        cluster_sync.sync_discovered = cls._orig_sync

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

    def test_sync_requires_auth(self):
        st, _ = self._get("/api/nodes/sync", token="bad-token-xyz")
        self.assertIn(st, (401, 403))

    def test_sync_returns_200(self):
        st, _ = self._get("/api/nodes/sync", token=self.session_token)
        self.assertEqual(st, 200)

    def test_sync_shape(self):
        _, data = self._get("/api/nodes/sync", token=self.session_token)
        for key in ("added", "existing", "scanned", "elapsed_s"):
            self.assertIn(key, data, f"missing key: {key}")

    def test_sync_added_is_list(self):
        _, data = self._get("/api/nodes/sync", token=self.session_token)
        self.assertIsInstance(data["added"], list)

    def test_sync_existing_is_list(self):
        _, data = self._get("/api/nodes/sync", token=self.session_token)
        self.assertIsInstance(data["existing"], list)

    def test_sync_scanned_is_int(self):
        _, data = self._get("/api/nodes/sync", token=self.session_token)
        self.assertIsInstance(data["scanned"], int)


class ClusterSyncUnitTest(unittest.TestCase):
    """Unit tests for cluster_sync.sync_discovered"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_discover = lan_discovery.discover

    def tearDown(self):
        lan_discovery.discover = self._orig_discover
        self._tmp.cleanup()

    def test_sync_no_nodes_found(self):
        lan_discovery.discover = lambda **kw: {
            "nodes": [], "scanned": 255, "base_ip": "192.168.1.1", "elapsed_s": 0.5
        }
        result = cluster_sync.sync_discovered(self.root)
        self.assertEqual(result["added"], [])
        self.assertEqual(result["existing"], [])
        self.assertEqual(result["scanned"], 255)

    def test_sync_adds_new_node(self):
        lan_discovery.discover = lambda **kw: {
            "nodes": [
                {"ip": "192.168.1.50", "port": 8420,
                 "url": "http://192.168.1.50:8420", "version": "0.2.4", "latency_ms": 10.0}
            ],
            "scanned": 255, "base_ip": "192.168.1.1", "elapsed_s": 0.8,
        }
        result = cluster_sync.sync_discovered(self.root)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["name"], "lca-192.168.1.50")
        self.assertEqual(result["added"][0]["url"], "http://192.168.1.50:8420")

    def test_sync_skips_existing_node(self):
        from app import cluster_store
        cluster_store.add_node(self.root, "lca-192.168.1.50", "http://192.168.1.50:8420")

        lan_discovery.discover = lambda **kw: {
            "nodes": [
                {"ip": "192.168.1.50", "port": 8420,
                 "url": "http://192.168.1.50:8420", "version": "0.2.4", "latency_ms": 10.0}
            ],
            "scanned": 255, "base_ip": "192.168.1.1", "elapsed_s": 0.8,
        }
        result = cluster_sync.sync_discovered(self.root)
        self.assertEqual(result["added"], [])
        self.assertEqual(len(result["existing"]), 1)

    def test_sync_error_passthrough(self):
        lan_discovery.discover = lambda **kw: {
            "nodes": [], "scanned": 0,
            "error": "invalid base_ip: not-an-ip", "elapsed_s": 0.0
        }
        result = cluster_sync.sync_discovered(self.root, base_ip="not-an-ip")
        self.assertIn("error", result)
        self.assertEqual(result["added"], [])


class ClusterSyncExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_discover = lan_discovery.discover

    def tearDown(self):
        lan_discovery.discover = self._orig_discover
        self._tmp.cleanup()

    def _empty_discover(self):
        lan_discovery.discover = lambda **kw: {
            "nodes": [], "scanned": 0, "base_ip": "192.168.1.1", "elapsed_s": 0.1
        }

    def test_sync_returns_dict(self):
        self._empty_discover()
        result = cluster_sync.sync_discovered(self.root)
        self.assertIsInstance(result, dict)

    def test_sync_has_added_key(self):
        self._empty_discover()
        result = cluster_sync.sync_discovered(self.root)
        self.assertIn("added", result)

    def test_sync_has_existing_key(self):
        self._empty_discover()
        result = cluster_sync.sync_discovered(self.root)
        self.assertIn("existing", result)

    def test_sync_added_is_list(self):
        self._empty_discover()
        result = cluster_sync.sync_discovered(self.root)
        self.assertIsInstance(result["added"], list)

    def test_sync_scanned_is_int(self):
        lan_discovery.discover = lambda **kw: {
            "nodes": [], "scanned": 128, "base_ip": "192.168.1.1", "elapsed_s": 0.1
        }
        result = cluster_sync.sync_discovered(self.root)
        self.assertIsInstance(result["scanned"], int)

    def test_sync_no_nodes_added_empty(self):
        self._empty_discover()
        result = cluster_sync.sync_discovered(self.root)
        self.assertEqual(result["added"], [])


if __name__ == "__main__":
    unittest.main()
