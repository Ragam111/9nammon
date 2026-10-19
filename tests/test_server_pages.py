"""
test_server_pages.py — integration test ของระบบหน้าเว็บ (web) ทุกหน้าในระบบ LCA

ตรวจว่า STATIC_ROUTES เสิร์ฟครบทุกหน้า (chat / dev / login / support) + asset (css/js)
ด้วย content-type ถูกต้อง และ route ที่ไม่มีคืน 404 — สตาร์ท server จริงบนพอร์ตสุ่ม
mock call_ollama ไว้ ไม่ต้องมี Ollama จริง
"""

import http.client
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


class ServerPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.call_ollama = lambda model, messages, num_ctx=8192: "mocked-reply"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        # ไม่ตั้ง master token = โหมด local (127.0.0.1) → หน้าเว็บ shell เสิร์ฟได้ไม่ต้อง auth
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
        body = resp.read()
        ctype = resp.getheader("Content-Type")
        cache = resp.getheader("Cache-Control")
        conn.close()
        return resp.status, ctype, cache, body

    def test_all_pages_served(self):
        # route -> (content-type มีคำนี้, ต้องมี Cache-Control ไหม)
        cases = {
            "/":        ("text/html", False),
            "/dev":     ("text/html", False),
            "/login":   ("text/html", False),
            "/support": ("text/html", False),
            "/app.css": ("text/css", True),
            "/app.js":  ("javascript", True),
        }
        for path, (ctype_part, want_cache) in cases.items():
            st, ctype, cache, body = self._get(path)
            self.assertEqual(st, 200, f"{path} ควรได้ 200 (ได้ {st})")
            self.assertIn(ctype_part, ctype, f"{path} content-type ผิด: {ctype}")
            self.assertTrue(len(body) > 0, f"{path} body ว่าง")
            if want_cache:
                self.assertIsNotNone(cache, f"{path} ควรมี Cache-Control")

    def test_pages_match_static_routes_table(self):
        # ทุก entry ใน STATIC_ROUTES ต้องเสิร์ฟได้จริง (กันเพิ่ม route แล้วลืมวางไฟล์)
        for route in server.STATIC_ROUTES:
            st, _, _, _ = self._get(route)
            self.assertEqual(st, 200, f"route {route} ใน STATIC_ROUTES เสิร์ฟไม่ได้ ({st})")

    def test_login_page_references_shared_auth_js(self):
        _, _, _, body = self._get("/login")
        self.assertIn(b"/app.js", body)

    def test_support_page_posts_to_ticket_api(self):
        _, _, _, body = self._get("/support")
        self.assertIn(b"/api/support/ticket", body)

    def test_dev_page_has_support_dashboard(self):
        # S2: /dev ต้องมี support dashboard ที่เรียก list + เปลี่ยนสถานะ ticket
        _, _, _, body = self._get("/dev")
        self.assertIn(b"/api/admin/support/tickets", body)
        self.assertIn(b"/api/admin/support/tickets/status", body)
        self.assertIn(b"support-wrap", body)

    def test_unknown_route_404(self):
        st, _, _, _ = self._get("/does-not-exist")
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
