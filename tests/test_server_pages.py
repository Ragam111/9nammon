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

    def test_dev_page_has_usage_monitor(self):
        # มอนิเตอร์ต่อ API key: /dev ต้องมี panel ที่ดึง usage summary (by_key)
        _, _, _, body = self._get("/dev")
        self.assertIn(b"/api/admin/usage/summary", body)
        self.assertIn(b"usage-wrap", body)

    def test_dev_page_has_cluster_monitor(self):
        # มอนิเตอร์คลัสเตอร์: /dev ต้องมี panel ที่ดึง health ของทุก node + เพิ่ม node ได้
        _, _, _, body = self._get("/dev")
        self.assertIn(b"/api/admin/cluster/health", body)
        self.assertIn(b"/api/admin/cluster/nodes", body)
        self.assertIn(b"cluster-wrap", body)

    def test_dev_page_has_ecosystem_settings(self):
        # ecosystem: /dev ต้องตั้งค่าตัวตน node + join hub ได้
        _, _, _, body = self._get("/dev")
        self.assertIn(b"/api/admin/cluster/settings", body)
        self.assertIn(b"/api/admin/cluster/join", body)

    def test_dev_page_has_hw_profile(self):
        # hardware profile: /dev ต้องมี panel ที่ดึงโปรไฟล์เครื่อง + แนะนำ config
        _, _, _, body = self._get("/dev")
        self.assertIn(b"/api/admin/hw-profile", body)
        self.assertIn(b"hwprofile-wrap", body)

    def test_hw_profile_endpoint_returns_profile(self):
        # GET /api/admin/hw-profile (no-disk) ต้องคืนโปรไฟล์ที่มี tier + recommended_config
        import json as _json
        st, ctype, _, body = self._get("/api/admin/hw-profile")
        self.assertEqual(st, 200)
        data = _json.loads(body)
        self.assertIn("profile", data)
        self.assertIn("tier", data["profile"])
        self.assertIn("MAX_CONCURRENT_GENERATIONS", data["profile"]["recommended_config"])

    def test_dev_page_has_model_backend_settings(self):
        # เสียบ cloud GPU: /dev ต้องตั้งค่า + ทดสอบ model backend ได้
        _, _, _, body = self._get("/dev")
        self.assertIn(b"/api/admin/model-backend/settings", body)
        self.assertIn(b"/api/admin/model-backend/test", body)

    def test_chat_stream_emits_sse_deltas(self):
        # /api/chat/stream ต้อง stream คำตอบทีละ chunk แบบ SSE แล้วปิดด้วย done
        import json as _json
        from unittest import mock
        fake = ["def ", "foo", "()"]
        with mock.patch.object(server.model_backend, "generate_stream",
                               lambda *a, **k: iter(fake)):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request("POST", "/api/chat/stream",
                         body=_json.dumps({"messages": [{"role": "user", "content": "hi"}]}),
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.getheader("Content-Type"))
            body = resp.read().decode("utf-8")
            conn.close()
        # รวม delta จากทุก event ต้องได้ข้อความเต็ม + มี event done ปิดท้าย
        deltas = []
        for block in body.split("\n\n"):
            block = block.strip()
            if block.startswith("data:"):
                evt = _json.loads(block[5:].strip())
                if "delta" in evt:
                    deltas.append(evt["delta"])
        self.assertEqual("".join(deltas), "def foo()")
        self.assertIn('"done": true', body)

    def test_dev_page_has_config_versions(self):
        # config rollback: /dev ต้องมี panel ที่ snapshot/list/rollback ได้
        _, _, _, body = self._get("/dev")
        self.assertIn(b"cfgver-wrap", body)
        self.assertIn(b"/api/admin/config/snapshot", body)
        self.assertIn(b"/api/admin/config/rollback", body)

    def test_config_version_snapshot_list_rollback(self):
        # local mode = CEO → snapshot + list + rollback ใช้ได้ครบ (flow กัน incident)
        import json as _json
        def _post(path, body):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request("POST", path, body=_json.dumps(body),
                         headers={"Content-Type": "application/json"})
            r = conn.getresponse(); data = r.read(); conn.close()
            return r.status, _json.loads(data or b"{}")
        # snapshot 1 อัน
        st, data = _post("/api/admin/config/snapshot", {"label": "ก่อนปล่อย"})
        self.assertEqual(st, 200)
        vid = data["snapshot"]["id"]
        # list ต้องเห็นเวอร์ชันนั้น
        st, _, _, body = self._get("/api/admin/config/versions")
        self.assertEqual(st, 200)
        self.assertIn(vid.encode(), body)
        # rollback กลับเวอร์ชันนั้น (ต้องสำเร็จ)
        st, data = _post("/api/admin/config/rollback", {"id": vid})
        self.assertEqual(st, 200)
        self.assertEqual(data["rolledback"]["restored"], vid)
        # rollback id มั่ว → 404
        st, _ = _post("/api/admin/config/rollback", {"id": "v-nope"})
        self.assertEqual(st, 404)

    def test_unknown_route_404(self):
        st, _, _, _ = self._get("/does-not-exist")
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
