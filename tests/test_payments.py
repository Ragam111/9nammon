"""
test_payments.py — plans + order state machine + plan activation/expiry (app/payments.py)

Uses a temp project root with a fake PROMPTPAY_ID (0812345678) in config.json.
No network, no real payment API: payment is confirmed by an ADMIN by hand.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import finance_ledger, org_store, payments, promptpay  # noqa: E402

FAKE_ID = "0812345678"
T0 = float(int(time.time()))  # fixed clock per run (plan limits compare with wall time)


def _root(promptpay_id=FAKE_ID, plans=None):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    cfg = {}
    if promptpay_id:
        cfg["PROMPTPAY_ID"] = promptpay_id
    if plans is not None:
        cfg["PLANS"] = plans
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return tmp, root


class _Base(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop("PROMPTPAY_ID", None)
        os.environ.pop("PLANS", None)
        self.addCleanup(env.stop)
        fast = mock.patch.object(org_store, "_PBKDF2_ITERATIONS", 1000)  # test speed only
        fast.start()
        self.addCleanup(fast.stop)
        self.tmp, self.root = _root()
        self.addCleanup(self.tmp.cleanup)
        org_store.create_user(self.root, "boss", "password123", "CEO")
        org_store.create_user(self.root, "alice", "password123", "USER", "CEO")
        org_store.create_user(self.root, "bob", "password123", "USER", "CEO")
        self.alice_key = org_store.create_api_key(self.root, "alice", "free", "CEO")

    def new_order(self, user="alice", plan="plus", now=T0):
        return payments.create_order(self.root, user, plan, now=now)["order"]

    def key_limit(self, key_id=None):
        key_id = key_id or self.alice_key["key_id"]
        return next(k for k in org_store.list_api_keys(self.root) if k["key_id"] == key_id)["daily_limit"]


class FormatAmountTest(unittest.TestCase):
    def test_rejects_nan_and_inf(self) -> None:
        for bad in (float("nan"), float("inf"), float("-inf"), "NaN", "sNaN", "Infinity"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                promptpay.format_amount(bad)
        self.assertEqual(promptpay.format_amount(299), "299.00")


class PlansTest(_Base):
    def test_default_plans_present_and_ordered(self):
        plans = payments.load_plans(self.root)
        self.assertEqual([p["id"] for p in plans], ["free", "plus", "pro", "max"])
        free = plans[0]
        self.assertEqual(free["price_thb"], 0)
        self.assertFalse(free["buyable"])
        self.assertEqual(free["daily_limit"], org_store.TIER_DAILY_LIMIT["free"])
        for p in plans[1:]:
            self.assertTrue(p["buyable"])
            self.assertGreater(p["price_thb"], 0)
            self.assertGreater(p["monthly_requests"], 0)
            self.assertGreater(p["monthly_tokens"], 0)

    def test_savings_note_vs_smaller_plan(self):
        tmp, root = _root(plans={
            "plus": {"price_thb": 100, "monthly_requests": 1000},
            "pro": {"price_thb": 300, "monthly_requests": 6000},
            "max": {"price_thb": 1000, "monthly_requests": 10000},
        })
        self.addCleanup(tmp.cleanup)
        plans = {p["id"]: p for p in payments.load_plans(root)}
        self.assertEqual(plans["plus"]["price_per_1k"], 100.0)
        self.assertIsNone(plans["plus"]["savings_note"])
        self.assertEqual(plans["pro"]["price_per_1k"], 50.0)
        self.assertEqual(plans["pro"]["savings_pct"], 50)
        self.assertIn("ประหยัดกว่า", plans["pro"]["savings_note"])
        self.assertIn("Plus", plans["pro"]["savings_note"])
        # max: 100/1k vs pro 50/1k -> more expensive per 1k -> no savings note
        self.assertIsNone(plans["max"]["savings_note"])

    def test_config_override_and_bad_values_ignored(self):
        tmp, root = _root(plans={"plus": {"price_thb": 49, "name": "Plus <b>"},
                                 "pro": {"price_thb": "abc"}, "evil": {"price_thb": 1}})
        self.addCleanup(tmp.cleanup)
        plans = {p["id"]: p for p in payments.load_plans(root)}
        self.assertEqual(plans["plus"]["price_thb"], 49)
        self.assertEqual(plans["pro"]["price_thb"], payments.DEFAULT_PLANS["pro"]["price_thb"])
        self.assertNotIn("evil", plans)


class StateMachineTest(_Base):
    def test_transition_table_exact(self):
        self.assertEqual(payments.TRANSITIONS, {
            "pending": {"paid", "cancelled"},
            "paid": {"active", "refund_requested"},
            "active": {"refund_requested", "expired"},
            "refund_requested": {"refunded", "refund_rejected"},
            "cancelled": set(), "refunded": set(), "refund_rejected": set(), "expired": set(),
        })

    def test_all_forbidden_transitions_rejected(self):
        states = list(payments.TRANSITIONS)
        for src in states:
            for dst in states:
                if dst in payments.TRANSITIONS[src] or dst == src:
                    continue
                o = self.new_order(user="bob")
                payments._force_status(self.root, o["order_id"], src)
                with self.assertRaises(payments.PaymentError, msg=f"{src}->{dst}") as cm:
                    payments.transition(self.root, o["order_id"], dst, "boss", "CEO", now=T0)
                self.assertEqual(cm.exception.status, 409)
                payments._force_status(self.root, o["order_id"], "cancelled")

    def test_all_allowed_transitions_accepted(self):
        for src, dsts in payments.TRANSITIONS.items():
            for dst in dsts:
                o = self.new_order(user="bob")
                payments._force_status(self.root, o["order_id"], src)
                res = payments.transition(self.root, o["order_id"], dst, "boss", "CEO", now=T0)
                self.assertTrue(res["changed"], f"{src}->{dst}")
                self.assertEqual(res["order"]["status"], dst)
                payments._force_status(self.root, o["order_id"], "cancelled")

    def test_same_state_is_noop(self):
        o = self.new_order()
        res = payments.transition(self.root, o["order_id"], "pending", "boss", "CEO", now=T0)
        self.assertFalse(res["changed"])

    def test_full_happy_path_logs_who_and_when(self):
        o = self.new_order()
        self.assertEqual(o["status"], "pending")
        self.assertTrue(promptpay.verify_crc(o["payload"]))
        self.assertEqual(promptpay.parse_tlv(o["payload"])["54"], "%.2f" % o["amount_thb"])
        res = payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0 + 60)
        self.assertEqual(res["order"]["status"], "active")
        req = payments.request_refund(self.root, o["order_id"], "alice", "ไม่ได้ใช้", now=T0 + 120)
        self.assertEqual(req["order"]["status"], "refund_requested")
        self.assertEqual(req["order"]["refund_reason"], "ไม่ได้ใช้")
        done = payments.refund(self.root, o["order_id"], "boss", "CEO", now=T0 + 180)
        self.assertEqual(done["order"]["status"], "refunded")
        ev = payments.list_events(self.root, o["order_id"])
        self.assertEqual([(e["from_status"], e["to_status"]) for e in ev], [
            (None, "pending"), ("pending", "paid"), ("paid", "active"),
            ("active", "refund_requested"), ("refund_requested", "refunded")])
        self.assertEqual([e["actor"] for e in ev], ["alice", "boss", "boss", "alice", "boss"])
        self.assertTrue(all(e["at"] for e in ev))

    def test_ledger_records_money_in_and_out(self):
        o = self.new_order()
        entries = finance_ledger.list_entries(self.root)
        self.assertEqual(entries[0]["status"], "pending")
        payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0 + 1)
        self.assertEqual(finance_ledger.get_entry(self.root, entries[0]["id"])["status"], "received")
        payments.request_refund(self.root, o["order_id"], "alice", "x", now=T0 + 2)
        payments.refund(self.root, o["order_id"], "boss", "CEO", now=T0 + 3)
        outs = finance_ledger.list_entries(self.root, direction="out")
        self.assertEqual(len(outs), 1)
        self.assertEqual(outs[0]["status"], "paid")
        self.assertEqual(outs[0]["amount"], o["amount_thb"])
        s = finance_ledger.summary(self.root)
        self.assertEqual(s["balance"], 0)

    def test_cancel_marks_ledger_cancelled(self):
        o = self.new_order()
        payments.cancel_order(self.root, o["order_id"], "alice", "USER", owner="alice", now=T0 + 5)
        self.assertEqual(finance_ledger.list_entries(self.root)[0]["status"], "cancelled")

    def test_double_confirm_is_noop(self):
        o = self.new_order()
        first = payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0 + 1)
        second = payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0 + 2)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["order"]["status"], "active")
        self.assertEqual(second["order"]["active_until"], first["order"]["active_until"])
        self.assertEqual(len(finance_ledger.list_entries(self.root, status="received")), 1)
        self.assertEqual(len(payments.list_events(self.root, o["order_id"])), 3)

    def test_no_refund_of_cancelled(self):
        o = self.new_order()
        payments.cancel_order(self.root, o["order_id"], "alice", "USER", owner="alice", now=T0)
        with self.assertRaises(payments.PaymentError) as cm:
            payments.request_refund(self.root, o["order_id"], "alice", "x", now=T0)
        self.assertEqual(cm.exception.status, 409)
        payments._force_status(self.root, o["order_id"], "cancelled")
        with self.assertRaises(payments.PaymentError):
            payments.refund(self.root, o["order_id"], "boss", "CEO", now=T0)

    def test_double_refund_is_noop(self):
        o = self.new_order()
        payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0)
        payments.request_refund(self.root, o["order_id"], "alice", "x", now=T0)
        payments.refund(self.root, o["order_id"], "boss", "CEO", now=T0)
        again = payments.refund(self.root, o["order_id"], "boss", "CEO", now=T0)
        self.assertFalse(again["changed"])
        self.assertEqual(len(finance_ledger.list_entries(self.root, direction="out")), 1)

    def test_refund_requires_reason(self):
        o = self.new_order()
        payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0)
        with self.assertRaises(payments.PaymentError) as cm:
            payments.request_refund(self.root, o["order_id"], "alice", "  ", now=T0)
        self.assertEqual(cm.exception.status, 400)

    def test_owner_checks(self):
        o = self.new_order()
        with self.assertRaises(payments.PaymentError) as cm:
            payments.cancel_order(self.root, o["order_id"], "bob", "USER", owner="bob", now=T0)
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(payments.PaymentError):
            payments.request_refund(self.root, o["order_id"], "bob", "x", now=T0)
        self.assertEqual(payments.get_order(self.root, o["order_id"])["status"], "pending")

    def test_unknown_plan_and_free_plan_rejected(self):
        for plan in ("free", "nope", ""):
            with self.assertRaises(payments.PaymentError) as cm:
                payments.create_order(self.root, "alice", plan, now=T0)
            self.assertEqual(cm.exception.status, 400)

    def test_one_pending_order_per_user(self):
        o = self.new_order(plan="plus")
        again = payments.create_order(self.root, "alice", "plus", now=T0 + 1)
        self.assertEqual(again["order"]["order_id"], o["order_id"])
        self.assertFalse(again["changed"])
        with self.assertRaises(payments.PaymentError) as cm:
            payments.create_order(self.root, "alice", "pro", now=T0 + 1)
        self.assertEqual(cm.exception.status, 409)

    def test_missing_promptpay_id(self):
        tmp, root = _root(promptpay_id=None)
        self.addCleanup(tmp.cleanup)
        self.assertFalse(payments.promptpay_ready(root))
        with self.assertRaises(payments.PaymentError) as cm:
            payments.create_order(root, "alice", "plus", now=T0)
        self.assertEqual(cm.exception.code, "promptpay_not_configured")
        self.assertIn("PROMPTPAY_ID", cm.exception.message)


class ExpiryTest(_Base):
    def test_pending_expires_after_30_minutes(self):
        o = self.new_order()
        payments.sweep(self.root, now=T0 + 29 * 60)
        self.assertEqual(payments.get_order(self.root, o["order_id"])["status"], "pending")
        payments.sweep(self.root, now=T0 + 30 * 60)
        got = payments.get_order(self.root, o["order_id"])
        self.assertEqual(got["status"], "cancelled")
        ev = payments.list_events(self.root, o["order_id"])[-1]
        self.assertEqual(ev["actor"], "system")
        self.assertIn("หมดเวลา", ev["note"])

    def test_confirm_after_expiry_rejected(self):
        o = self.new_order()
        with self.assertRaises(payments.PaymentError) as cm:
            payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0 + 31 * 60)
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(payments.get_order(self.root, o["order_id"])["status"], "cancelled")
        self.assertEqual(self.key_limit(), org_store.TIER_DAILY_LIMIT["free"])

    def test_new_order_allowed_after_old_one_expired(self):
        o = self.new_order(plan="plus")
        o2 = payments.create_order(self.root, "alice", "pro", now=T0 + 31 * 60)["order"]
        self.assertNotEqual(o["order_id"], o2["order_id"])


class ActivationQuotaTest(_Base):
    def plan(self, pid):
        return next(p for p in payments.load_plans(self.root) if p["id"] == pid)

    def test_activation_raises_quota_for_30_days_and_expiry_reverts(self):
        free = org_store.TIER_DAILY_LIMIT["free"]
        self.assertEqual(self.key_limit(), free)
        o = self.new_order(plan="pro")
        res = payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0)
        want = self.plan("pro")["daily_limit"]
        self.assertGreater(want, free)
        self.assertEqual(self.key_limit(), want)
        self.assertEqual(res["order"]["active_until"], T0 + 30 * 86400)
        lim = org_store.plan_limit(self.root, "alice")
        self.assertEqual(lim["plan"], "pro")
        # key issued while the plan is active gets the plan limit too
        k2 = org_store.create_api_key(self.root, "alice", "free", "CEO")
        self.assertEqual(self.key_limit(k2["key_id"]), want)
        payments.sweep(self.root, now=T0 + 30 * 86400 - 1)
        self.assertEqual(self.key_limit(), want)
        payments.sweep(self.root, now=T0 + 30 * 86400)
        self.assertEqual(self.key_limit(), free)
        self.assertEqual(self.key_limit(k2["key_id"]), free)
        self.assertEqual(payments.get_order(self.root, o["order_id"])["status"], "expired")
        self.assertIsNone(org_store.plan_limit(self.root, "alice"))

    def test_refund_reverts_quota(self):
        o = self.new_order(plan="plus")
        payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0)
        self.assertEqual(self.key_limit(), self.plan("plus")["daily_limit"])
        payments.request_refund(self.root, o["order_id"], "alice", "x", now=T0 + 5)
        self.assertEqual(self.key_limit(), self.plan("plus")["daily_limit"])  # still on plan
        payments.refund(self.root, o["order_id"], "boss", "CEO", now=T0 + 10)
        self.assertEqual(self.key_limit(), org_store.TIER_DAILY_LIMIT["free"])

    def test_reject_refund_keeps_plan(self):
        o = self.new_order(plan="plus")
        payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0)
        payments.request_refund(self.root, o["order_id"], "alice", "x", now=T0 + 5)
        r = payments.reject_refund(self.root, o["order_id"], "boss", "CEO", now=T0 + 6)
        self.assertEqual(r["order"]["status"], "refund_rejected")
        self.assertEqual(self.key_limit(), self.plan("plus")["daily_limit"])
        payments.sweep(self.root, now=T0 + 30 * 86400)
        self.assertEqual(self.key_limit(), org_store.TIER_DAILY_LIMIT["free"])

    def test_paid_tier_key_not_downgraded(self):
        paid = org_store.create_api_key(self.root, "alice", "paid", "CEO")
        o = self.new_order(plan="plus")
        payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0)
        self.assertEqual(self.key_limit(paid["key_id"]), 0)
        payments.request_refund(self.root, o["order_id"], "alice", "x", now=T0)
        payments.refund(self.root, o["order_id"], "boss", "CEO", now=T0)
        self.assertEqual(self.key_limit(paid["key_id"]), 0)

    def test_quota_enforced_with_plan_limit(self):
        o = self.new_order(plan="plus")
        payments.confirm_paid(self.root, o["order_id"], "boss", "CEO", now=T0)
        ok, remaining = org_store.consume_quota(self.root, self.alice_key["key_id"])
        self.assertTrue(ok)
        self.assertEqual(remaining, self.plan("plus")["daily_limit"] - 1)

    def test_newer_plan_supersedes_old_one(self):
        o1 = self.new_order(plan="plus")
        payments.confirm_paid(self.root, o1["order_id"], "boss", "CEO", now=T0)
        o2 = payments.create_order(self.root, "alice", "pro", now=T0 + 100)["order"]
        payments.confirm_paid(self.root, o2["order_id"], "boss", "CEO", now=T0 + 200)
        self.assertEqual(payments.get_order(self.root, o1["order_id"])["status"], "expired")
        self.assertEqual(self.key_limit(), self.plan("pro")["daily_limit"])
        # refunding the old (superseded) plan is not possible; the new one stays
        with self.assertRaises(payments.PaymentError):
            payments.request_refund(self.root, o1["order_id"], "alice", "x", now=T0 + 300)


if __name__ == "__main__":
    unittest.main()
