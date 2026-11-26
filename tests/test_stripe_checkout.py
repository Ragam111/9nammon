"""
test_stripe_checkout.py — Stripe hosted Checkout + webhook (real server, random port, Stripe HTTP mocked)

No network to stripe.com: stripe_pay._http is patched in every test. Fake test keys only.
"""

import hashlib
import hmac
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import org_store, payments, stripe_pay  # noqa: E402

MASTER = "master-secret-token"
SK = "sk_test_FAKEFAKEFAKE0000"
WHSEC = "whsec_FAKEFAKEFAKE1111"
SECRETS = (SK, WHSEC, "FAKEFAKEFAKE")


def sign(raw: bytes, ts=None, secret=WHSEC) -> str:
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


class StripeCheckoutTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        for k in ("PROMPTPAY_ID", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_MODE",
                  "PUBLIC_BASE_URL"):
            os.environ.pop(k, None)
        self.addCleanup(env.stop)
        fast = mock.patch.object(org_store, "_PBKDF2_ITERATIONS", 1000)
        fast.start()
        self.addCleanup(fast.stop)
        stripe_pay.CHECKOUT_LIMITER._hits.clear()
        self.calls = []
        self.http = mock.patch.object(stripe_pay, "_http", side_effect=self._fake_http)
        self.http.start()
        self.addCleanup(self.http.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._config({"PROMPTPAY_ID": "0812345678", "STRIPE_SECRET_KEY": SK,
                      "STRIPE_WEBHOOK_SECRET": WHSEC})
        org_store.create_user(self.root, "boss", "password123", "CEO")
        org_store.create_user(self.root, "alice", "password123", "USER", "CEO")
        org_store.create_user(self.root, "adm", "password123", "ADMIN", "CEO")
        self.alice = {"X-API-Key": org_store.create_api_key(self.root, "alice", "free", "CEO")["key"]}
        self.adm = {"X-API-Key": org_store.create_api_key(self.root, "adm", "free", "CEO")["key"]}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.root, MASTER))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _config(self, cfg):
        (self.root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def _fake_http(self, method, url, form, key, idem):
        self.calls.append({"url": url, "form": dict(form), "key": key, "idem": idem})
        self.assertTrue(url.startswith("https://api.stripe.com/v1/"))
        if url.endswith("/checkout/sessions"):
            return {"id": "cs_test_" + form["client_reference_id"],
                    "url": "https://checkout.stripe.com/c/pay/cs_test_x"}
        if url.endswith("/refunds"):
            return {"id": "re_test_1", "status": "succeeded"}
        raise AssertionError(url)

    def _req(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = dict(headers or {})
        payload = raw
        if body is not None:
            payload = json.dumps(body)
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8")
        conn.close()
        return resp.status, (json.loads(text) if text.startswith("{") else text)

    def _checkout(self, plan="plus", extra=None):
        st, d = self._req("POST", "/api/pay/stripe/checkout", dict({"plan": plan}, **(extra or {})),
                          headers=self.alice)
        self.assertEqual(st, 200, d)
        return d

    def _event(self, oid, etype="checkout.session.completed", amount=9900, currency="thb",
               eid=None, paid="paid"):
        return json.dumps({"id": eid or ("evt_" + os.urandom(6).hex()), "type": etype,
                           "data": {"object": {"id": "cs_test_" + oid, "client_reference_id": oid,
                                               "metadata": {"order_id": oid},
                                               "amount_total": amount, "currency": currency,
                                               "payment_status": paid,
                                               "payment_intent": "pi_test_1"}}}).encode()

    def _hook(self, raw, sig=None):
        return self._req("POST", "/api/pay/stripe/webhook", raw=raw,
                         headers={"Stripe-Signature": sig if sig is not None else sign(raw),
                                  "Content-Type": "application/json"})

    def _status(self, oid):
        return payments.get_order(self.root, oid)["status"]

    # ---- checkout ----
    def test_checkout_requires_login(self):
        st, _ = self._req("POST", "/api/pay/stripe/checkout", {"plan": "plus"})
        self.assertEqual(st, 401)
        self.assertEqual(self.calls, [])

    def test_checkout_creates_session_server_price(self):
        d = self._checkout(extra={"price_thb": 1, "amount": 1, "unit_amount": 1})
        self.assertTrue(d["url"].startswith("https://checkout.stripe.com/"))
        f = self.calls[0]["form"]
        self.assertEqual(f["line_items[0][price_data][unit_amount]"], "9900")
        self.assertEqual(f["line_items[0][price_data][currency]"], "thb")
        self.assertEqual(f["mode"], "payment")
        self.assertEqual({f["payment_method_types[0]"], f["payment_method_types[1]"]},
                         {"card", "promptpay"})
        self.assertEqual(f["client_reference_id"], d["order_id"])
        self.assertEqual(f["metadata[username]"], "alice")
        self.assertEqual(self.calls[0]["idem"], d["order_id"])
        self.assertTrue(f["success_url"].startswith(f"http://127.0.0.1:{self.port}/plans"))
        o = payments.get_order(self.root, d["order_id"])
        self.assertEqual((o["status"], o["amount_thb"]), ("pending", 99))
        self.assertTrue(stripe_pay.is_stripe(self.root, d["order_id"]))
        # same plan again = same session (no second Stripe call)
        self.assertEqual(self._checkout()["order_id"], d["order_id"])
        self.assertEqual(len(self.calls), 1)

    def test_bad_plan(self):
        st, _ = self._req("POST", "/api/pay/stripe/checkout", {"plan": "free"}, headers=self.alice)
        self.assertEqual(st, 400)

    def test_rate_limit_per_user(self):
        codes = [self._req("POST", "/api/pay/stripe/checkout", {"plan": "plus"},
                           headers=self.alice)[0] for _ in range(7)]
        self.assertIn(429, codes)

    def test_unconfigured_hidden_and_503(self):
        self._config({"PROMPTPAY_ID": "0812345678"})
        st, d = self._req("GET", "/api/plans")
        self.assertFalse(d["stripe_ready"])
        self.assertTrue(d["promptpay_ready"])
        st, d = self._req("POST", "/api/pay/stripe/checkout", {"plan": "plus"}, headers=self.alice)
        self.assertEqual(st, 503)
        self.assertIn("Stripe", d["error"])
        st, _ = self._hook(b"{}")
        self.assertEqual(st, 503)
        st, d = self._req("POST", "/api/orders", {"plan": "plus"}, headers=self.alice)
        self.assertEqual(st, 200)  # PromptPay flow unchanged

    def test_live_key_refused_in_test_mode(self):
        self._config({"STRIPE_SECRET_KEY": "sk_live_FAKE", "STRIPE_WEBHOOK_SECRET": WHSEC})
        self.assertFalse(stripe_pay.ready(self.root))
        st, _ = self._req("POST", "/api/pay/stripe/checkout", {"plan": "plus"}, headers=self.alice)
        self.assertEqual(st, 503)
        self._config({"STRIPE_SECRET_KEY": "sk_live_FAKE", "STRIPE_WEBHOOK_SECRET": WHSEC,
                      "STRIPE_MODE": "live"})
        self.assertTrue(stripe_pay.ready(self.root))

    # ---- webhook ----
    def test_valid_signature_activates(self):
        oid = self._checkout()["order_id"]
        st, d = self._hook(self._event(oid))
        self.assertEqual((st, d["result"]), (200, "paid"))
        self.assertEqual(self._status(oid), "active")

    def test_async_promptpay(self):
        oid = self._checkout()["order_id"]
        st, d = self._hook(self._event(oid, paid="unpaid"))
        self.assertEqual(d["result"], "awaiting_async")
        self.assertEqual(self._status(oid), "pending")
        st, d = self._hook(self._event(oid, "checkout.session.async_payment_succeeded"))
        self.assertEqual(self._status(oid), "active")

    def test_failed_and_expired(self):
        oid = self._checkout()["order_id"]
        st, d = self._hook(self._event(oid, "checkout.session.async_payment_failed"))
        self.assertEqual(d["result"], "failed")
        self.assertEqual(self._status(oid), "cancelled")
        oid2 = self._checkout()["order_id"]
        st, d = self._hook(self._event(oid2, "checkout.session.expired"))
        self.assertEqual(d["result"], "cancelled")

    def test_invalid_signature(self):
        oid = self._checkout()["order_id"]
        raw = self._event(oid)
        st, _ = self._hook(raw, sign(raw, secret="whsec_wrong"))
        self.assertEqual(st, 400)
        st, _ = self._hook(raw, "garbage")
        self.assertEqual(st, 400)
        st, _ = self._hook(raw, "")
        self.assertEqual(st, 400)
        self.assertEqual(self._status(oid), "pending")

    def test_expired_signature(self):
        oid = self._checkout()["order_id"]
        raw = self._event(oid)
        st, _ = self._hook(raw, sign(raw, ts=int(time.time()) - 301))
        self.assertEqual(st, 400)
        self.assertEqual(self._status(oid), "pending")

    def test_tampered_body(self):
        oid = self._checkout()["order_id"]
        raw = self._event(oid, amount=1)
        sig = sign(raw)
        tampered = raw.replace(b'"amount_total": 1', b'"amount_total": 9900')
        self.assertNotEqual(raw, tampered)
        st, _ = self._hook(tampered, sig)
        self.assertEqual(st, 400)
        self.assertEqual(self._status(oid), "pending")

    def test_replay_and_duplicate_event(self):
        oid = self._checkout()["order_id"]
        raw = self._event(oid, eid="evt_same")
        self.assertEqual(self._hook(raw)[1]["result"], "paid")
        st, d = self._hook(raw)
        self.assertEqual((st, d.get("duplicate")), (200, True))
        events = payments.list_events(self.root, oid)
        self.assertEqual(sum(1 for e in events if e["to_status"] == "active"), 1)
        n = org_store.run_read(self.root, "SELECT COUNT(*) AS n FROM stripe_events", one=True)["n"]
        self.assertEqual(n, 1)

    def test_wrong_amount_or_currency_review(self):
        oid = self._checkout()["order_id"]
        st, d = self._hook(self._event(oid, amount=100))
        self.assertEqual(d["result"], "review")
        self.assertEqual(self._status(oid), "pending")
        st, d = self._hook(self._event(oid, currency="usd"))
        self.assertEqual(d["result"], "review")
        self.assertEqual(self._status(oid), "pending")

    def test_unknown_order(self):
        st, d = self._hook(self._event("ord_0000000000000000"))
        self.assertEqual((st, d["result"]), (200, "unknown_order"))

    # ---- refunds ----
    def test_refund_path(self):
        oid = self._checkout()["order_id"]
        self._hook(self._event(oid))
        st, _ = self._req("POST", f"/api/admin/orders/{oid}/refund", {}, headers=self.alice)
        self.assertEqual(st, 403)
        st, d = self._req("POST", f"/api/admin/orders/{oid}/refund", {}, headers=self.adm)
        self.assertEqual(st, 200, d)
        self.assertEqual(self._status(oid), "refunded")
        rf = [c for c in self.calls if c["url"].endswith("/refunds")]
        self.assertEqual(rf[0]["form"]["payment_intent"], "pi_test_1")
        self.assertEqual(rf[0]["idem"], "refund_" + oid)

    def test_promptpay_refund_stays_manual(self):
        st, d = self._req("POST", "/api/orders", {"plan": "plus"}, headers=self.alice)
        oid = d["order"]["order_id"]
        payments._force_status(self.root, oid, "refund_requested")
        st, _ = self._req("POST", f"/api/admin/orders/{oid}/refund", {}, headers=self.adm)
        self.assertEqual(st, 200)
        self.assertFalse([c for c in self.calls if c["url"].endswith("/refunds")])

    # ---- secrets ----
    def test_secrets_never_in_responses_or_logs(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            d = self._checkout()
            _, plans = self._req("GET", "/api/plans")
            _, mine = self._req("GET", "/api/orders", headers=self.alice)
            _, hook = self._hook(self._event(d["order_id"]))
            _, bad = self._hook(b"{}", "t=1,v1=00")
        blob = json.dumps([d, plans, mine, hook, bad]) + buf.getvalue()
        for s in SECRETS:
            self.assertNotIn(s, blob)
        self.assertEqual(self.calls[0]["key"], SK)  # only sent to (mocked) Stripe

    def test_verify_signature_unit(self):
        raw = b'{"a":1}'
        now = 1_700_000_000
        self.assertTrue(stripe_pay.verify_signature(raw, sign(raw, now), WHSEC, now=now))
        self.assertFalse(stripe_pay.verify_signature(raw, sign(raw, now), WHSEC, now=now + 301))
        self.assertTrue(stripe_pay.verify_signature(raw, f"t={now},v1=00," + sign(raw, now).split(",")[1],
                                                    WHSEC, now=now))


if __name__ == "__main__":
    unittest.main()
