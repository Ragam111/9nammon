"""
test_server_org.py — integration test ของ RBAC/API-key ที่ชั้น HTTP (stdlib unittest)

สตาร์ท server จริงใน process เดียวกันบนพอร์ตสุ่ม แล้วยิง request ผ่าน http.client
mock call_ollama ไว้ ไม่ต้องมี Ollama จริงรันอยู่
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

MASTER = "master-secret-token"


class ServerOrgTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # mock Model layer — ไม่เรียก Ollama จริง
        server.call_ollama = lambda model, messages, num_ctx=8192: "mocked-reply"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        handler = server.make_handler(root, MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        data = json.loads(raw) if raw else {}
        return resp.status, data

    # ---- bootstrap + identity ----
    def test_full_org_flow(self):
        master_hdr = {"X-Auth-Token": MASTER}

        # 1) bootstrap: server ตั้ง master token ไว้ → ต้องใส่ token ถึงสร้าง CEO คนแรกได้
        st, _ = self._req("POST", "/api/admin/users",
                          {"username": "boss", "password": "password123", "role": "CEO"})
        self.assertEqual(st, 401)  # ไม่ใส่ token → ปฏิเสธ (กันชิงสิทธิ์)
        st, d = self._req("POST", "/api/admin/users",
                          {"username": "boss", "password": "password123", "role": "CEO"},
                          headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertTrue(d.get("bootstrap"))

        # 2) หลัง bootstrap แล้ว สร้าง user ต่อโดยไม่ auth ไม่ได้
        st, _ = self._req("POST", "/api/admin/users",
                          {"username": "x", "password": "password123", "role": "USER"})
        self.assertEqual(st, 401)

        # 3) master token = CEO
        st, d = self._req("GET", "/api/me", headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["role"], "CEO")

        # 4) CEO สร้าง USER + ออก free API key
        st, d = self._req("POST", "/api/admin/users",
                          {"username": "dev", "password": "password123", "role": "USER"},
                          headers=master_hdr)
        self.assertEqual(st, 200, d)

        st, d = self._req("POST", "/api/admin/apikeys",
                          {"owner": "dev", "tier": "free"}, headers=master_hdr)
        self.assertEqual(st, 200, d)
        dev_key = d["api_key"]["key"]
        self.assertTrue(dev_key.startswith("lca_f_"))

        # 5) ใช้ dev key แชทได้ (กินโควตา)
        st, d = self._req("POST", "/api/chat",
                          {"messages": [{"role": "user", "content": "hi"}]},
                          headers={"X-API-Key": dev_key})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["reply"], "mocked-reply")

        # 6) dev (USER) เข้า admin route ไม่ได้ → 403
        st, _ = self._req("GET", "/api/admin/users", headers={"X-API-Key": dev_key})
        self.assertEqual(st, 403)

        # 7) ไม่มี auth เลย (ตั้ง master token ไว้) → chat 401
        st, _ = self._req("POST", "/api/chat",
                          {"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(st, 401)

        # 8) key มั่ว → 401
        st, _ = self._req("POST", "/api/chat",
                          {"messages": [{"role": "user", "content": "hi"}]},
                          headers={"X-API-Key": "lca_f_wrong"})
        self.assertEqual(st, 401)

    def _bootstrap_dev_key(self, tier="free"):
        """ช่วย: bootstrap CEO + สร้าง dev USER + ออก key — คืน (master_hdr, key)"""
        master_hdr = {"X-Auth-Token": MASTER}
        self._req("POST", "/api/admin/users",
                  {"username": "boss", "password": "password123", "role": "CEO"},
                  headers=master_hdr)
        self._req("POST", "/api/admin/users",
                  {"username": "dev", "password": "password123", "role": "USER"},
                  headers=master_hdr)
        _, d = self._req("POST", "/api/admin/apikeys",
                         {"owner": "dev", "tier": tier}, headers=master_hdr)
        return master_hdr, d["api_key"]["key"]

    def test_api_key_user_me_has_username(self):
        _, key = self._bootstrap_dev_key()
        st, me = self._req("GET", "/api/me", headers={"X-API-Key": key})
        self.assertEqual(st, 200)
        self.assertEqual(me["username"], "dev")  # ต้องไม่เป็น null

    def test_malformed_body_does_not_consume_quota(self):
        _, key = self._bootstrap_dev_key()
        # ส่ง body ที่ไม่ใช่ JSON → 400 และต้องไม่หักโควตา
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/chat", body="{not valid json",
                     headers={"X-API-Key": key})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 400)
        from app import org_store
        keys = org_store.list_api_keys(Path(self._tmp.name))
        self.assertEqual(keys[0]["used_today"], 0)  # ไม่โดนหัก

    def test_successful_chat_consumes_one_quota(self):
        _, key = self._bootstrap_dev_key()
        st, _ = self._req("POST", "/api/chat",
                          {"messages": [{"role": "user", "content": "hi"}]},
                          headers={"X-API-Key": key})
        self.assertEqual(st, 200)
        from app import org_store
        keys = org_store.list_api_keys(Path(self._tmp.name))
        self.assertEqual(keys[0]["used_today"], 1)  # หักพอดี 1

    def test_delete_todo_route(self):
        master_hdr = {"X-Auth-Token": MASTER}
        self._req("POST", "/api/admin/users",
                  {"username": "boss", "password": "password123", "role": "CEO"},
                  headers=master_hdr)
        st, item = self._req("POST", "/api/todos", {"text": "temp"}, headers=master_hdr)
        self.assertEqual(st, 200, item)
        tid = item["id"]
        # ลบได้
        st, d = self._req("POST", "/api/todos/delete", {"id": tid}, headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertTrue(d["success"])
        # หายจริง (GET /api/todos ตอนนี้ต้อง auth แล้ว)
        _, todos = self._req("GET", "/api/todos", headers=master_hdr)
        self.assertEqual([t for t in todos if t["id"] == tid], [])
        # ลบ id ที่ไม่มี -> 404
        st, _ = self._req("POST", "/api/todos/delete", {"id": 99999}, headers=master_hdr)
        self.assertEqual(st, 404)

    def test_delete_todo_requires_auth(self):
        master_hdr = {"X-Auth-Token": MASTER}
        self._req("POST", "/api/admin/users",
                  {"username": "boss", "password": "password123", "role": "CEO"},
                  headers=master_hdr)
        # ตั้ง token ไว้ แต่ไม่ส่ง auth -> 401
        st, _ = self._req("POST", "/api/todos/delete", {"id": 1})
        self.assertEqual(st, 401)

    def test_sysinfo_requires_admin(self):
        master_hdr, key = self._bootstrap_dev_key()  # dev = USER
        # ไม่ส่ง auth -> 401
        st, _ = self._req("GET", "/api/sysinfo")
        self.assertEqual(st, 401)
        # USER -> 403
        st, _ = self._req("GET", "/api/sysinfo", headers={"X-API-Key": key})
        self.assertEqual(st, 403)
        # ADMIN (master = CEO) -> 200 + มีข้อมูลเครื่อง
        st, info = self._req("GET", "/api/sysinfo", headers=master_hdr)
        self.assertEqual(st, 200, info)
        for k in ("cpu", "memory", "storage", "gpus", "gpu_note"):
            self.assertIn(k, info)

    def test_index_page_served_has_ux(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200)
        # ใช้ design system กลาง (app.css) + ยังมี marker UX เดิมในมาร์กอัป
        self.assertIn('href="/app.css"', body)
        self.assertIn('class="page-chat"', body)
        self.assertIn('id="sidebar-toggle"', body)
        self.assertIn('id="todo-msg"', body)

    def test_dev_page_served(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/dev")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn("Dev View", body)
        self.assertIn('href="/app.css"', body)
        self.assertIn('class="page-dev"', body)
        self.assertIn("/api/metrics", body)      # Item R: หน้าทรัพยากรสดเรียก metrics
        self.assertIn('id="metrics"', body)

    def test_app_css_served(self):
        # design system กลางต้องเสิร์ฟได้ เป็น text/css และมี token + responsive
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/app.css")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        ctype = resp.getheader("Content-Type") or ""
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn("text/css", ctype)
        self.assertIn("--lca-bg", body)                     # มี design token
        self.assertIn("@media (max-width: 720px)", body)    # responsive ย้ายมาอยู่ที่นี่
        self.assertIn("prefers-reduced-motion", body)       # กฎ perf สำหรับเครื่องอ่อน
        self.assertIn(".fill", body)                        # Item R: มิเตอร์ทรัพยากร

    def test_jobs_crud_and_rbac(self):
        master_hdr, key = self._bootstrap_dev_key()  # dev = USER
        # USER เข้า jobs ไม่ได้ -> 403
        st, _ = self._req("GET", "/api/admin/jobs", headers={"X-API-Key": key})
        self.assertEqual(st, 403)
        # ไม่ auth -> 401
        st, _ = self._req("POST", "/api/admin/jobs", {"name": "x"})
        self.assertEqual(st, 401)
        # ADMIN enqueue -> 200
        st, d = self._req("POST", "/api/admin/jobs",
                          {"name": "build", "payload": {"t": 1}}, headers=master_hdr)
        self.assertEqual(st, 200, d)
        jid = d["job"]["id"]
        self.assertEqual(d["job"]["status"], "pending")
        # list
        st, d = self._req("GET", "/api/admin/jobs", headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertEqual(len(d["jobs"]), 1)
        # set status
        st, d = self._req("POST", "/api/admin/jobs/status",
                          {"id": jid, "status": "done"}, headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertTrue(d["success"])
        # bad status -> 400
        st, _ = self._req("POST", "/api/admin/jobs/status",
                          {"id": jid, "status": "bogus"}, headers=master_hdr)
        self.assertEqual(st, 400)
        # delete
        st, d = self._req("POST", "/api/admin/jobs/delete", {"id": jid}, headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertTrue(d["success"])
        st, _ = self._req("POST", "/api/admin/jobs/delete", {"id": jid}, headers=master_hdr)
        self.assertEqual(st, 404)

    def test_history_rbac_and_flow(self):
        master_hdr, key = self._bootstrap_dev_key()  # dev = USER
        # USER เข้าไม่ได้ -> 403
        st, _ = self._req("GET", "/api/admin/history/errors", headers={"X-API-Key": key})
        self.assertEqual(st, 403)
        # log error (ADMIN)
        st, d = self._req("POST", "/api/admin/history/errors",
                          {"level": "error", "source": "test", "message": "boom"},
                          headers=master_hdr)
        self.assertEqual(st, 200, d)
        # bad level -> 400
        st, _ = self._req("POST", "/api/admin/history/errors",
                          {"level": "bogus", "message": "x"}, headers=master_hdr)
        self.assertEqual(st, 400)
        # list errors
        st, d = self._req("GET", "/api/admin/history/errors", headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertEqual(len(d["errors"]), 1)
        # record a live snapshot (short interval) + list
        st, d = self._req("POST", "/api/admin/history/snapshot",
                          {"interval": 0.1}, headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertIn("cpu_percent", d["snapshot"])
        st, d = self._req("GET", "/api/admin/history/snapshots", headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertEqual(len(d["snapshots"]), 1)

    def test_finance_rbac_and_flow(self):
        master_hdr, key = self._bootstrap_dev_key()  # dev = USER
        # USER เข้าไม่ได้ -> 403
        st, _ = self._req("GET", "/api/admin/finance", headers={"X-API-Key": key})
        self.assertEqual(st, 403)
        # ไม่ auth -> 401
        st, _ = self._req("POST", "/api/admin/finance", {"amount": 10, "direction": "in"})
        self.assertEqual(st, 401)
        # ADMIN บันทึก "เบิก 1500 รอโอน" -> 200 pending
        st, d = self._req("POST", "/api/admin/finance",
                          {"amount": 1500, "direction": "in", "note": "เบิก - รอหัวหน้าโอน"},
                          headers=master_hdr)
        self.assertEqual(st, 200, d)
        eid = d["entry"]["id"]
        self.assertEqual(d["entry"]["status"], "pending")
        # amount พัง -> 400
        st, _ = self._req("POST", "/api/admin/finance",
                          {"amount": -5, "direction": "in"}, headers=master_hdr)
        self.assertEqual(st, 400)
        # status ขัดทิศทาง (in -> paid) -> 400
        st, _ = self._req("POST", "/api/admin/finance/status",
                          {"id": eid, "status": "paid"}, headers=master_hdr)
        self.assertEqual(st, 400)
        # mark received -> 200
        st, d = self._req("POST", "/api/admin/finance/status",
                          {"id": eid, "status": "received"}, headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["entry"]["status"], "received")
        # summary สะท้อน balance
        st, d = self._req("GET", "/api/admin/finance/summary", headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["summary"]["received_in"], 1500.0)
        self.assertEqual(d["summary"]["balance"], 1500.0)
        # list filter
        st, d = self._req("GET", "/api/admin/finance?status=received", headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertEqual(len(d["entries"]), 1)
        # delete + 404
        st, d = self._req("POST", "/api/admin/finance/delete", {"id": eid}, headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertTrue(d["success"])
        st, _ = self._req("POST", "/api/admin/finance/delete", {"id": eid}, headers=master_hdr)
        self.assertEqual(st, 404)

    def test_usage_metering_rbac_and_flow(self):
        master_hdr, key = self._bootstrap_dev_key(tier="paid")  # dev = USER, paid
        # USER เข้า usage admin ไม่ได้ -> 403
        st, _ = self._req("GET", "/api/admin/usage", headers={"X-API-Key": key})
        self.assertEqual(st, 403)
        # ยังไม่มีการใช้ -> summary ว่าง
        st, d = self._req("GET", "/api/admin/usage/summary", headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["summary"]["total_units"], 0)
        # ยิง chat 2 ครั้งด้วย paid key -> ควรบันทึก usage 2 event
        body = {"messages": [{"role": "user", "content": "hi"}]}
        for _ in range(2):
            st, _ = self._req("POST", "/api/chat", body, headers={"X-API-Key": key})
            self.assertEqual(st, 200)
        st, d = self._req("GET", "/api/admin/usage", headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertEqual(len(d["usage"]), 2)
        # summary สะท้อน units + cost ต่อ tier paid
        st, d = self._req("GET", "/api/admin/usage/summary", headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["summary"]["total_units"], 2)
        self.assertEqual(d["summary"]["by_tier"]["paid"]["units"], 2)

    def test_todos_get_requires_auth(self):
        master_hdr, key = self._bootstrap_dev_key()  # server นี้ตั้ง MASTER token ไว้
        # ไม่ส่ง auth -> 401 (เดิมเปิดสาธารณะ ตอนนี้ปิดแล้ว)
        st, _ = self._req("GET", "/api/todos")
        self.assertEqual(st, 401)
        # USER (dev key) อ่านได้ -> 200
        st, todos = self._req("GET", "/api/todos", headers={"X-API-Key": key})
        self.assertEqual(st, 200)
        self.assertIsInstance(todos, list)

    def test_rate_limit_returns_429(self):
        # server แยกที่ตั้ง rate limit ต่ำ ๆ เพื่อพิสูจน์ 429
        root = Path(self._tmp.name)
        handler = server.make_handler(root, None, rate_limit_max=3, rate_limit_window=60)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            def hit():
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/todos")
                resp = conn.getresponse()
                resp.read()
                conn.close()
                return resp.status
            # 3 ครั้งแรกผ่าน (local mode = CEO, ไม่ตั้ง token), ครั้งที่ 4 โดน 429
            statuses = [hit() for _ in range(4)]
            self.assertEqual(statuses[:3], [200, 200, 200])
            self.assertEqual(statuses[3], 429)
            # path ที่ไม่ใช่ /api/ ไม่โดนจำกัด
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            self.assertEqual(resp.status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_notify_rbac_and_flow(self):
        master_hdr, key = self._bootstrap_dev_key()  # dev = USER
        # USER -> 403
        st, _ = self._req("POST", "/api/admin/notify",
                          {"event": "x", "text": "y"}, headers={"X-API-Key": key})
        self.assertEqual(st, 403)
        # ไม่ auth -> 401
        st, _ = self._req("POST", "/api/admin/notify", {"event": "x", "text": "y"})
        self.assertEqual(st, 401)
        # text ว่าง -> 400 (notifier โยน ValueError)
        st, _ = self._req("POST", "/api/admin/notify", {"event": "x", "text": "  "},
                          headers=master_hdr)
        self.assertEqual(st, 400)
        # ADMIN + ไม่มี config -> 200 แต่ทุกช่อง skipped (ไม่ยิงเน็ตจริง)
        st, d = self._req("POST", "/api/admin/notify",
                          {"event": "deploy", "text": "merged PR"}, headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["result"]["discord"], "skipped (no config)")
        self.assertEqual(d["result"]["email"], "skipped (no config)")

    def test_support_rbac_and_flow(self):
        master_hdr, key = self._bootstrap_dev_key()  # dev = USER
        # ไม่ auth -> 401
        st, _ = self._req("POST", "/api/support/ticket", {"subject": "x", "body": "y"})
        self.assertEqual(st, 401)
        # USER (ลูกค้า) แจ้ง ticket ได้ -> 200, reporter = dev, notify skipped (ไม่มี config)
        st, d = self._req("POST", "/api/support/ticket",
                          {"subject": "แชทพัง", "body": "error 500 ตอนกดส่ง", "kind": "bug"},
                          headers={"X-API-Key": key})
        self.assertEqual(st, 200, d)
        tid = d["ticket"]["id"]
        self.assertEqual(d["ticket"]["reporter"], "dev")
        self.assertEqual(d["ticket"]["status"], "open")
        self.assertEqual(d["notified"]["discord"], "skipped (no config)")
        # subject ว่าง -> 400
        st, _ = self._req("POST", "/api/support/ticket", {"subject": "", "body": "y"},
                          headers={"X-API-Key": key})
        self.assertEqual(st, 400)
        # USER ดู admin list ไม่ได้ -> 403
        st, _ = self._req("GET", "/api/admin/support/tickets", headers={"X-API-Key": key})
        self.assertEqual(st, 403)
        # ADMIN list เห็น ticket + counts
        st, d = self._req("GET", "/api/admin/support/tickets", headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(len(d["tickets"]), 1)
        self.assertEqual(d["counts"]["open"], 1)
        # ADMIN เปลี่ยนสถานะ -> resolved
        st, d = self._req("POST", "/api/admin/support/tickets/status",
                          {"id": tid, "status": "resolved"}, headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["ticket"]["status"], "resolved")
        # id ไม่มี -> 404
        st, _ = self._req("POST", "/api/admin/support/tickets/status",
                          {"id": 99999, "status": "open"}, headers=master_hdr)
        self.assertEqual(st, 404)

    def test_metrics_rbac_and_shape(self):
        master_hdr, key = self._bootstrap_dev_key()  # dev = USER
        # ไม่ auth -> 401
        st, _ = self._req("GET", "/api/metrics")
        self.assertEqual(st, 401)
        # USER -> 403
        st, _ = self._req("GET", "/api/metrics", headers={"X-API-Key": key})
        self.assertEqual(st, 403)
        # ADMIN -> 200 + โครงครบ (snapshot/verdict/findings/lca)
        st, d = self._req("GET", "/api/metrics?interval=0.1", headers=master_hdr)
        self.assertEqual(st, 200, d)
        for k in ("snapshot", "verdict", "worst_severity", "findings", "lca"):
            self.assertIn(k, d)
        self.assertIn("ollama_running", d["lca"])
        self.assertIsInstance(d["findings"], list)

    def test_dataset_rbac_and_export(self):
        master_hdr, key = self._bootstrap_dev_key()  # dev = USER
        # USER -> 403
        st, _ = self._req("GET", "/api/admin/dataset", headers={"X-API-Key": key})
        self.assertEqual(st, 403)
        # ADMIN เพิ่มตัวอย่าง -> 200
        st, d = self._req("POST", "/api/admin/dataset",
                          {"prompt": "เขียน for loop", "response": "for i in range(10): pass", "rating": 5},
                          headers=master_hdr)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["sample"]["rating"], 5)
        # prompt ว่าง -> 400
        st, _ = self._req("POST", "/api/admin/dataset", {"prompt": "", "response": "x"}, headers=master_hdr)
        self.assertEqual(st, 400)
        # list + count
        st, d = self._req("GET", "/api/admin/dataset", headers=master_hdr)
        self.assertEqual(st, 200)
        self.assertEqual(d["count"], 1)
        # export JSONL (ไม่ใช่ JSON ธรรมดา) — ยิงตรงเพื่ออ่าน body ดิบ
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/admin/dataset/export", headers=master_hdr)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        ctype = resp.getheader("Content-Type") or ""
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn("ndjson", ctype)
        obj = json.loads(body.strip().splitlines()[0])
        self.assertEqual(obj["messages"][0]["content"], "เขียน for loop")

    def test_chat_collects_training_data_when_enabled(self):
        _, key = self._bootstrap_dev_key()
        from app import config_manager
        root = Path(self._tmp.name)
        config_manager.set_key(root, "COLLECT_TRAINING_DATA", "1")  # เปิด opt-in
        st, _ = self._req("POST", "/api/chat",
                          {"messages": [{"role": "user", "content": "hello collect"}]},
                          headers={"X-API-Key": key})
        self.assertEqual(st, 200)
        from app import dataset_store
        rows = dataset_store.list_samples(root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prompt"], "hello collect")
        self.assertEqual(rows[0]["response"], "mocked-reply")  # จาก call_ollama ที่ mock ไว้

    def test_chat_does_not_collect_by_default(self):
        _, key = self._bootstrap_dev_key()  # ไม่ตั้ง config
        st, _ = self._req("POST", "/api/chat",
                          {"messages": [{"role": "user", "content": "hi"}]},
                          headers={"X-API-Key": key})
        self.assertEqual(st, 200)
        from app import dataset_store
        self.assertEqual(dataset_store.count(Path(self._tmp.name)), 0)  # ปิดเป็นค่าเริ่มต้น

    def test_quota_exhaustion_returns_429(self):
        master_hdr = {"X-Auth-Token": MASTER}
        self._req("POST", "/api/admin/users",
                  {"username": "boss", "password": "password123", "role": "CEO"},
                  headers=master_hdr)
        self._req("POST", "/api/admin/users",
                  {"username": "dev", "password": "password123", "role": "USER"},
                  headers=master_hdr)
        st, d = self._req("POST", "/api/admin/apikeys",
                          {"owner": "dev", "tier": "free"}, headers=master_hdr)
        key = d["api_key"]["key"]
        from app import org_store
        limit = org_store.TIER_DAILY_LIMIT["free"]
        hdr = {"X-API-Key": key}
        body = {"messages": [{"role": "user", "content": "hi"}]}
        for _ in range(limit):
            st, _ = self._req("POST", "/api/chat", body, headers=hdr)
            self.assertEqual(st, 200)
        st, _ = self._req("POST", "/api/chat", body, headers=hdr)
        self.assertEqual(st, 429)


if __name__ == "__main__":
    unittest.main()
