"""
test_server_payments.py — HTTP layer of the PromptPay plan flow (real server, random port)

Roles: CEO via master token, USER via API key. Fake PROMPTPAY_ID only.
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import org_store, promptpay  # noqa: E402

MASTER = "master-secret-token"
FAKE_ID = "0812345678"


class ServerPaymentsTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop("PROMPTPAY_ID", None)
        self.addCleanup(env.stop)
        fast = mock.patch.object(org_store, "_PBKDF2_ITERATIONS", 1000)  # test speed only
        fast.start()
        self.addCleanup(fast.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "config.json").write_text(json.dumps({"PROMPTPAY_ID": FAKE_ID}), encoding="utf-8")
        org_store.create_user(self.root, "boss", "password123", "CEO")
        org_store.create_user(self.root, "alice", "password123", "USER", "CEO")
        org_store.create_user(self.root, "bob", "password123", "USER", "CEO")
        org_store.create_user(self.root, "adm", "password123", "ADMIN", "CEO")
        self.alice = {"X-API-Key": org_store.create_api_key(self.root, "alice", "free", "CEO")["key"]}
        self.bob = {"X-API-Key": org_store.create_api_key(self.root, "bob", "free", "CEO")["key"]}
        self.adm = {"X-API-Key": org_store.create_api_key(self.root, "adm", "free", "CEO")["key"]}
        self.ceo = {"X-Auth-Token": MASTER}
        handler = server.make_handler(self.root, MASTER)
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
        hdrs = dict(headers or {})
        payload = None
        if body is not None:
            payload = json.dumps(body)
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        ctype = resp.getheader("Content-Type") or ""
        conn.close()
        data = json.loads(raw) if raw and "json" in ctype else raw
        return resp.status, data

    def _buy(self, who=None, plan="plus"):
        st, d = self._req("POST", "/api/orders", {"plan": plan}, headers=who or self.alice)
        self.assertEqual(st, 200, d)
        return d["order"]

    def test_plans_public(self):
        st, d = self._req("GET", "/api/plans")
        self.assertEqual(st, 200, d)
        self.assertEqual([p["id"] for p in d["plans"]], ["free", "plus", "pro", "max"])
        self.assertTrue(d["promptpay_ready"])
        self.assertNotIn(FAKE_ID, json.dumps(d))
        self.assertNotIn("812345", json.dumps(d))

    def test_create_requires_user(self):
        st, _ = self._req("POST", "/api/orders", {"plan": "plus"})
        self.assertEqual(st, 401)

    def test_buy_returns_valid_payload_and_lists_own(self):
        o = self._buy()
        self.assertEqual(o["status"], "pending")
        self.assertTrue(promptpay.verify_crc(o["payload"]))
        st, d = self._req("GET", "/api/orders", headers=self.alice)
        self.assertEqual(st, 200)
        self.assertEqual([x["order_id"] for x in d["orders"]], [o["order_id"]])
        st, d = self._req("GET", "/api/orders", headers=self.bob)
        self.assertEqual(d["orders"], [])

    def test_user_cannot_confirm_own_payment(self):
        o = self._buy()
        for path in ("confirm-paid", "refund", "reject-refund"):
            st, _ = self._req("POST", f"/api/admin/orders/{o['order_id']}/{path}", {}, headers=self.alice)
            self.assertEqual(st, 403, path)
        st, _ = self._req("GET", "/api/admin/orders", headers=self.alice)
        self.assertEqual(st, 403)
        st, d = self._req("GET", "/api/orders", headers=self.alice)
        self.assertEqual(d["orders"][0]["status"], "pending")

    def test_user_cannot_touch_others_orders(self):
        o = self._buy(self.alice)
        st, _ = self._req("POST", f"/api/orders/{o['order_id']}/cancel", {}, headers=self.bob)
        self.assertEqual(st, 404)
        st, _ = self._req("POST", f"/api/orders/{o['order_id']}/refund-request",
                          {"reason": "x"}, headers=self.bob)
        self.assertEqual(st, 404)
        st, d = self._req("GET", "/api/admin/orders", headers=self.ceo)
        self.assertEqual(d["orders"][0]["status"], "pending")

    def test_cancel_own_pending(self):
        o = self._buy()
        st, d = self._req("POST", f"/api/orders/{o['order_id']}/cancel", {}, headers=self.alice)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["order"]["status"], "cancelled")
        st, d = self._req("POST", f"/api/orders/{o['order_id']}/cancel", {}, headers=self.alice)
        self.assertEqual(st, 200)
        self.assertFalse(d["changed"])
        st, d = self._req("POST", f"/api/orders/{o['order_id']}/refund-request",
                          {"reason": "x"}, headers=self.alice)
        self.assertEqual(st, 409)

    def test_admin_flow_and_double_confirm(self):
        o = self._buy()
        oid = o["order_id"]
        st, d = self._req("POST", f"/api/admin/orders/{oid}/confirm-paid", {}, headers=self.adm)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["order"]["status"], "active")
        self.assertTrue(d["changed"])
        st, d = self._req("POST", f"/api/admin/orders/{oid}/confirm-paid", {}, headers=self.ceo)
        self.assertEqual(st, 200)
        self.assertFalse(d["changed"])
        st, d = self._req("POST", f"/api/orders/{oid}/refund-request", {"reason": "ซื้อผิด"},
                          headers=self.alice)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["order"]["status"], "refund_requested")
        st, d = self._req("POST", f"/api/admin/orders/{oid}/refund", {}, headers=self.adm)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["order"]["status"], "refunded")
        st, d = self._req("GET", "/api/admin/orders?status=refunded", headers=self.adm)
        self.assertEqual(st, 200)
        self.assertEqual(len(d["orders"]), 1)
        self.assertEqual(d["orders"][0]["username"], "alice")
        self.assertGreaterEqual(len(d["orders"][0]["events"]), 4)

    def test_refund_request_needs_reason(self):
        o = self._buy()
        self._req("POST", f"/api/admin/orders/{o['order_id']}/confirm-paid", {}, headers=self.ceo)
        st, _ = self._req("POST", f"/api/orders/{o['order_id']}/refund-request", {}, headers=self.alice)
        self.assertEqual(st, 400)

    def test_unknown_order_404_and_bad_plan_400(self):
        st, _ = self._req("POST", "/api/admin/orders/ord_nope/confirm-paid", {}, headers=self.ceo)
        self.assertEqual(st, 404)
        st, _ = self._req("POST", "/api/orders", {"plan": "gold"}, headers=self.alice)
        self.assertEqual(st, 400)

    def test_promptpay_not_set_explains(self):
        (self.root / "config.json").write_text("{}", encoding="utf-8")
        st, d = self._req("GET", "/api/plans")
        self.assertFalse(d["promptpay_ready"])
        st, d = self._req("POST", "/api/orders", {"plan": "plus"}, headers=self.alice)
        self.assertEqual(st, 409)
        self.assertEqual(d["code"], "promptpay_not_configured")
        self.assertIn("PROMPTPAY_ID", d["error"])

    def test_plans_page_and_qr_script_served(self):
        st, body = self._req("GET", "/plans")
        self.assertEqual(st, 200)
        self.assertIn("/qr.js", body)
        self.assertIn("/api/plans", body)
        self.assertIn("savings_note", body)
        self.assertIn("esc(", body)  # every server string goes through the escaper
        self.assertNotIn("cdn", body.lower())
        st, js = self._req("GET", "/qr.js")
        self.assertEqual(st, 200)
        self.assertIn("encodeText", js)


if __name__ == "__main__":
    unittest.main()
