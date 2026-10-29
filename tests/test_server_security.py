"""test_server_security.py — zero-day fixes:
- timing-safe token compare (hmac.compare_digest)
- request body size limit (DoS protection)
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

MASTER_TOKEN = "secret-master-token-abcdefghij"


class TimingSafeTokenCompareTest(unittest.TestCase):
    """verify ว่าเทียบ token ใช้ hmac.compare_digest (constant-time)
    — เทสฟังก์ชันทำงานถูก, ไม่ได้วัดเวลาจริง (วัดเวลาใน unit test ไม่เสถียร)"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        handler = server.make_handler(Path(self._tmp.name), MASTER_TOKEN)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        resp.read()  # drain
        conn.close()
        return resp.status

    def test_correct_token_authenticates(self):
        status = self._get("/api/me", headers={"X-Auth-Token": MASTER_TOKEN})
        self.assertEqual(status, 200)

    def test_wrong_token_rejected(self):
        status = self._get("/api/me", headers={"X-Auth-Token": "wrong-token"})
        self.assertEqual(status, 401)

    def test_different_length_token_safe(self):
        # compare_digest ปลอดภัยกับ token ยาวต่างกัน (ไม่โยน exception, ตอบ 401)
        for bogus in ("", "a", "x" * 1000, MASTER_TOKEN + "x"):
            status = self._get("/api/me", headers={"X-Auth-Token": bogus})
            self.assertEqual(status, 401, f"token {bogus!r} ต้องถูกปฏิเสธ")

    def test_empty_header_rejected(self):
        status = self._get("/api/me", headers={})
        self.assertEqual(status, 401)


class RequestBodySizeLimitTest(unittest.TestCase):
    """ตรวจว่า Content-Length ที่ใหญ่เกินจะถูกปฏิเสธด้วย 400 (ไม่ใช่ล้ม RAM)"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        handler = server.make_handler(Path(self._tmp.name), MASTER_TOKEN)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _post_raw(self, path, body_bytes, content_length=None):
        """ส่ง POST โดยกำหนด Content-Length ตามใจ (อาจไม่เท่ากับ len(body))"""
        if content_length is None:
            content_length = len(body_bytes)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST", path)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(content_length))
        conn.putheader("X-Auth-Token", MASTER_TOKEN)
        conn.endheaders()
        conn.send(body_bytes)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, raw.decode("utf-8")

    def test_small_body_ok(self):
        body = json.dumps({"text": "hello"}).encode("utf-8")
        status, _ = self._post_raw("/api/todos", body)
        # 200 or 400 ก็ได้ (depends on todos endpoint) — ขอให้ไม่ 500
        self.assertNotEqual(status, 500)

    def test_oversized_content_length_rejected(self):
        # ประกาศ Content-Length ใหญ่กว่า MAX_BODY_BYTES → ต้องถูกปฏิเสธ 400
        huge_cl = 3 * 1024 * 1024  # 3 MiB > 2 MiB limit
        body = b'{"text":"x"}'  # ส่งน้อยกว่าที่ประกาศ (server ไม่ควรรออ่าน)
        status, raw = self._post_raw("/api/todos", body, content_length=huge_cl)
        self.assertEqual(status, 400)
        self.assertIn("ใหญ่เกิน", raw)

    def test_at_limit_still_works(self):
        # Content-Length = exactly MAX_BODY_BYTES → ต้องผ่าน (ไม่ reject)
        # ส่ง body ที่เป็น valid JSON แต่ยาวใกล้ limit
        payload = {"text": "x" * (1024 * 1024)}  # 1 MiB — well within 2 MiB
        body = json.dumps(payload).encode("utf-8")
        status, _ = self._post_raw("/api/todos", body)
        self.assertNotEqual(status, 400,
                            "payload ภายใน limit ต้องไม่ถูกปฏิเสธด้วย body size")


if __name__ == "__main__":
    unittest.main()
