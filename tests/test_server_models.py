"""แผน C: HTTP ของ /api/models/catalog และ /api/models/pull (ไม่ใช้ Ollama จริง)"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server
from app import model_manager


class ServerModelsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        handler = server.make_handler(Path(self._tmp.name), None)
        self.token = handler.session_token
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _req(self, method, path, body=None, auth=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}",
                   "Origin": f"http://127.0.0.1:{self.port}"}
        if auth:
            headers["X-Auth-Token"] = self.token
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = c.getresponse()
        data = r.read().decode("utf-8")
        c.close()
        return r.status, data

    def test_catalog_requires_auth(self):
        status, _ = self._req("GET", "/api/models/catalog", auth=False)
        self.assertIn(status, (401, 403))

    def test_catalog_returns_ram_and_installed(self):
        fake = {"ram_free_gb": 2.0, "ram_total_gb": 8.0, "ollama_running": True,
                "installed": [{"name": "qwen2.5-coder:1.5b", "size_gb": 1.0}], "catalog": []}
        with mock.patch.object(model_manager, "catalog", return_value=fake) as cat:
            status, data = self._req("GET", "/api/models/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["installed"][0]["name"], "qwen2.5-coder:1.5b")
        cat.assert_called_once()

    def test_pull_rejects_unknown_model(self):
        status, data = self._req("POST", "/api/models/pull", {"model": "evil:latest"})
        self.assertEqual(status, 400)
        self.assertIn("ไม่อนุญาต", json.loads(data)["error"])

    def test_pull_streams_ndjson_until_done(self):
        events = iter([{"status": "pulling manifest"},
                       {"status": "downloading", "completed": 1, "total": 2, "digest": "x"},
                       {"status": "success"}])
        with mock.patch.object(model_manager, "pull", return_value=events):
            status, data = self._req("POST", "/api/models/pull", {"model": "qwen2.5-coder:0.5b"})
        self.assertEqual(status, 200)
        lines = [json.loads(x) for x in data.splitlines() if x.strip()]
        self.assertEqual([x["status"] for x in lines],
                         ["pulling manifest", "downloading", "success", "done"])
        self.assertNotIn("digest", lines[1])

    def test_pull_reports_ollama_error_in_stream(self):
        def boom(name):
            raise model_manager.ModelManagerError("ติดต่อ Ollama ไม่ได้")
            yield  # pragma: no cover
        with mock.patch.object(model_manager, "pull", side_effect=boom):
            status, data = self._req("POST", "/api/models/pull", {"model": "qwen2.5:1.5b"})
        self.assertEqual(status, 200)
        last = json.loads(data.splitlines()[-1])
        self.assertEqual(last["status"], "error")

    def test_pull_unexpected_error_mid_stream_stays_ndjson(self):
        def boom(name):
            yield {"status": "pulling manifest"}
            raise RuntimeError("unexpected")
        with mock.patch.object(model_manager, "pull", side_effect=boom):
            status, data = self._req("POST", "/api/models/pull", {"model": "qwen2.5:1.5b"})
        self.assertEqual(status, 200)
        self.assertNotIn("HTTP/1.", data)
        lines = [json.loads(x) for x in data.splitlines() if x.strip()]
        self.assertEqual(lines[0]["status"], "pulling manifest")
        self.assertEqual(lines[-1]["status"], "error")


if __name__ == "__main__":
    unittest.main()
