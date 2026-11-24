"""
test_server_body_shape.py — body JSON ที่ไม่ใช่ object ต้องได้ 400 JSON (ไม่ใช่ socket ถูกทิ้ง)

ก่อนแก้: POST ที่ body เป็น `[1,2]` ทำให้ handler เรียก .get() บน list → AttributeError
แล้ว server ไม่ตอบอะไรเลย. หลังแก้: _read_json_body โยน ValueError → do_POST ตอบ 400.
"""

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


class ServerBodyShapeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        handler = server.make_handler(Path(self._tmp.name), None)
        self.session_token = handler.session_token
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        orig = http.client.HTTPConnection.request

        def _request(conn, method, url, body=None, headers=None, *, encode_chunked=False):
            hdrs = dict(headers or {})
            hdrs.setdefault("X-Auth-Token", self.session_token)
            return orig(conn, method, url, body=body, headers=hdrs, encode_chunked=encode_chunked)

        patch = mock.patch.object(http.client.HTTPConnection, "request", _request)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _post_raw(self, path, raw: bytes):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", path, body=raw, headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, data

    def test_non_object_json_body_returns_400_json(self):
        # routes ที่อ่าน body ด้วย _read_json_body — ทุกตัวต้องได้ 400 ไม่ใช่ socket drop
        routes = [
            "/api/skills/update",
            "/api/skills/delete",
            "/api/bots/update",
            "/api/bots/delete",
            "/api/connections/update",
            "/api/todos",
        ]
        for path in routes:
            with self.subTest(path=path):
                status, data = self._post_raw(path, b"[1,2]")
                self.assertEqual(status, 400, f"{path} ควรได้ 400 (ได้ {status})")
                payload = json.loads(data)
                self.assertEqual(payload["error"], "request body ต้องเป็น JSON object")

    def test_scalar_json_body_returns_400(self):
        for raw in (b"\"text\"", b"42", b"null"):
            with self.subTest(raw=raw):
                status, _ = self._post_raw("/api/skills/update", raw)
                self.assertEqual(status, 400)

    def test_unexpected_exception_returns_500_json(self):
        # ด่านสุดท้าย: exception ที่ไม่รู้จักต้องตอบ 500 JSON ไม่ทิ้ง socket
        with mock.patch.object(server.skills_store, "update",
                               side_effect=RuntimeError("boom")):
            status, data = self._post_raw(
                "/api/skills/update", json.dumps({"id": "x"}).encode("utf-8"))
        self.assertEqual(status, 500)
        self.assertIn("error", json.loads(data))


if __name__ == "__main__":
    unittest.main()
