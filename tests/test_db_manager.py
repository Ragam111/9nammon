"""
test_db_manager.py — HTTP integration tests for GET /api/admin/db/status
                   + unit tests for db_manager.get_db_status / log_event
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
from app import model_backend, db_manager  # noqa: E402

_ORIG_GENERATE = model_backend.generate


def _make_server(tmp_dir: Path):
    handler = server.make_handler(tmp_dir, None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, handler.session_token


class DbStatusHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: f"MODEL={model}"
        )

    @classmethod
    def tearDownClass(cls):
        model_backend.generate = _ORIG_GENERATE

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

    def test_db_status_returns_200(self):
        st, _ = self._get("/api/admin/db/status", token=self.session_token)
        self.assertEqual(st, 200)

    def test_db_status_shape(self):
        _, data = self._get("/api/admin/db/status", token=self.session_token)
        for key in ("status", "db_version", "code_version",
                    "db_size_bytes", "tables", "migrations_applied"):
            self.assertIn(key, data, f"missing key: {key}")

    def test_db_status_requires_admin(self):
        st, _ = self._get("/api/admin/db/status", token="bad-token-xyz")
        self.assertIn(st, (401, 403))

    def test_db_status_tables_is_list(self):
        _, data = self._get("/api/admin/db/status", token=self.session_token)
        self.assertIsInstance(data["tables"], list)

    def test_db_status_versions_are_ints(self):
        _, data = self._get("/api/admin/db/status", token=self.session_token)
        self.assertIsInstance(data["db_version"], int)
        self.assertIsInstance(data["code_version"], int)

    def test_db_code_version_at_least_11(self):
        _, data = self._get("/api/admin/db/status", token=self.session_token)
        self.assertGreaterEqual(data["code_version"], 11,
                                "code_version ต้อง >= 11 หลัง migration 0011")


class DbManagerUnitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_db_status_ok(self):
        data = db_manager.get_db_status(self.root)
        self.assertIn(data["status"], ("ok", "pending"))

    def test_log_event_silent_on_uninitialized(self):
        db_manager.log_event(self.root, "test", "hello world")

    def test_log_event_after_migration(self):
        db_manager.get_db_status(self.root)  # migrate
        db_manager.log_event(self.root, "startup", "server started", level="info")
        data = db_manager.get_db_status(self.root)
        self.assertIn("server_events", data["tables"])


if __name__ == "__main__":
    unittest.main()
