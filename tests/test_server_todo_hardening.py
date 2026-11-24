"""test_server_todo_hardening.py — HTTP-level checks for /api/todos hardening.

ครอบคลุม:
- socket timeout: request ที่ body ค้าง ต้องถูกตัดการเชื่อมต่อ (ไม่จองเธรดตลอดกาล)
- body ที่ไม่ใช่ JSON object / text ที่ไม่ใช่ string → 400 JSON (ไม่ใช่ 500)
- id ผิดรูปแบบ → 400 โดยไม่ส่งข้อความ exception ดิบของ Python กลับไป
- บันทึกไฟล์ไม่สำเร็จ → 500 JSON (ไม่ใช่ 200 และไม่ใช่การตัดการเชื่อมต่อ)
"""

import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


class TodoHardeningHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.handler = server.make_handler(self.root, None)
        self.auth = {"X-Auth-Token": self.handler.session_token}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _post_raw(self, path, raw: bytes):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, body=raw,
                     headers={"Content-Type": "application/json", **self.auth})
        resp = conn.getresponse()
        text = resp.read().decode("utf-8")
        conn.close()
        return resp.status, text

    def _post(self, path, payload):
        status, text = self._post_raw(path, json.dumps(payload).encode("utf-8"))
        return status, json.loads(text)

    def test_handler_has_socket_timeout(self):
        self.assertIsNotNone(self.handler.timeout)
        self.assertGreater(self.handler.timeout, 0)

    def test_stalled_request_is_closed(self):
        # ส่ง header ว่า body ยาว 100 bytes แต่ไม่ส่ง body → server ต้องตัดการเชื่อมต่อ
        self.handler.timeout = 1
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        try:
            request = (
                "POST /api/todos HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                "Content-Type: application/json\r\n"
                "Content-Length: 100\r\n"
                f"X-Auth-Token: {self.handler.session_token}\r\n"
                "\r\n"
            )
            sock.sendall(request.encode("ascii"))
            started = time.monotonic()
            data = sock.recv(4096)   # ต้องได้ EOF (b"") เมื่อ server ปิดตามเวลา
            elapsed = time.monotonic() - started
        finally:
            sock.close()
        self.assertEqual(data, b"", "server should close a stalled connection without responding")
        self.assertLess(elapsed, 8, "stalled connection was not closed by the socket timeout")

    def test_non_object_json_body_rejected_with_400(self):
        for raw in (b'["a", "b"]', b'"just a string"', b"42", b"{bad json"):
            with self.subTest(body=raw):
                status, text = self._post_raw("/api/todos", raw)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(text))

    def test_non_string_text_rejected_with_400(self):
        for payload in ({"text": 123}, {"text": ["a"]}, {"text": {"x": 1}}, {"text": None}):
            with self.subTest(payload=payload):
                status, body = self._post("/api/todos", payload)
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_non_numeric_content_length_returns_fixed_400(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("POST", "/api/todos")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", "abc")
        conn.putheader("X-Auth-Token", self.handler.session_token)
        conn.endheaders()
        resp = conn.getresponse()
        text = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 400)
        body = json.loads(text)
        self.assertEqual(body["error"], "Content-Length ไม่ถูกต้อง")
        self.assertNotIn("invalid literal", text)

    def test_bad_toggle_id_does_not_leak_python_error(self):
        status, body = self._post("/api/todos/toggle", {"id": "abc"})
        self.assertEqual(status, 400)
        self.assertNotIn("invalid literal", body["error"])
        self.assertNotIn("Traceback", body["error"])

    def test_non_object_toggle_body_rejected_with_400(self):
        status, body = self._post_raw("/api/todos/toggle", b"[1]")
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))

    def test_save_failure_returns_500_json(self):
        # todos.json ถูกแทนด้วยโฟลเดอร์ → เขียนไม่ได้ ต้องตอบ 500 พร้อม JSON error
        (self.root / "todos.json").mkdir()
        status, body = self._post("/api/todos", {"text": "will fail"})
        self.assertEqual(status, 500)
        self.assertIn("error", body)
        self.assertNotIn(str(self.root), body["error"])


if __name__ == "__main__":
    unittest.main()
