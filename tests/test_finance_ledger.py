"""
test_finance_ledger.py — unittest สำหรับ finance ledger (record-only, stdlib sqlite3)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import finance_ledger  # noqa: E402


class FinanceLedgerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    # ---- record ----
    def test_record_and_get(self):
        rec = finance_ledger.record_entry(self.root, 1500, "in", note="เบิก - รอหัวหน้าโอน")
        self.assertEqual(rec["amount"], 1500.0)
        self.assertEqual(rec["direction"], "in")
        self.assertEqual(rec["status"], "pending")
        self.assertEqual(rec["note"], "เบิก - รอหัวหน้าโอน")
        got = finance_ledger.get_entry(self.root, rec["id"])
        self.assertEqual(got["id"], rec["id"])

    def test_record_rejects_bad_amount(self):
        with self.assertRaises(ValueError):
            finance_ledger.record_entry(self.root, 0, "in")
        with self.assertRaises(ValueError):
            finance_ledger.record_entry(self.root, -10, "in")
        with self.assertRaises(ValueError):
            finance_ledger.record_entry(self.root, "abc", "in")

    def test_record_rejects_bad_direction(self):
        with self.assertRaises(ValueError):
            finance_ledger.record_entry(self.root, 10, "sideways")

    def test_record_rejects_status_direction_mismatch(self):
        # เงินเข้าจะเป็น paid ไม่ได้ (ต้อง received)
        with self.assertRaises(ValueError):
            finance_ledger.record_entry(self.root, 10, "in", status="paid")
        # เงินออกจะเป็น received ไม่ได้
        with self.assertRaises(ValueError):
            finance_ledger.record_entry(self.root, 10, "out", status="received")

    def test_record_returns_dict(self):
        rec = finance_ledger.record_entry(self.root, 100, "out")
        self.assertIsInstance(rec, dict)

    def test_record_has_required_keys(self):
        rec = finance_ledger.record_entry(self.root, 200, "in")
        for key in ("id", "amount", "direction", "status", "note", "created_at"):
            self.assertIn(key, rec)

    def test_record_id_is_int(self):
        rec = finance_ledger.record_entry(self.root, 50, "out")
        self.assertIsInstance(rec["id"], int)

    def test_record_amount_is_float(self):
        rec = finance_ledger.record_entry(self.root, 300, "in")
        self.assertIsInstance(rec["amount"], float)

    def test_record_out_direction_works(self):
        rec = finance_ledger.record_entry(self.root, 400, "out", note="ค่าบริการ")
        self.assertEqual(rec["direction"], "out")
        self.assertEqual(rec["status"], "pending")

    # ---- list ----
    def test_list_newest_first_and_filters(self):
        finance_ledger.record_entry(self.root, 100, "in", note="first")
        finance_ledger.record_entry(self.root, 200, "out", note="second")
        rows = finance_ledger.list_entries(self.root)
        self.assertEqual(rows[0]["note"], "second")  # ใหม่สุดก่อน
        self.assertEqual(len(finance_ledger.list_entries(self.root, direction="in")), 1)
        self.assertEqual(len(finance_ledger.list_entries(self.root, status="pending")), 2)

    def test_list_rejects_bad_filter(self):
        with self.assertRaises(ValueError):
            finance_ledger.list_entries(self.root, status="bogus")
        with self.assertRaises(ValueError):
            finance_ledger.list_entries(self.root, direction="bogus")

    def test_list_returns_list(self):
        result = finance_ledger.list_entries(self.root)
        self.assertIsInstance(result, list)

    def test_get_entry_returns_none_for_missing(self):
        result = finance_ledger.get_entry(self.root, 99999)
        self.assertIsNone(result)

    # ---- set_status ----
    def test_set_status_flow(self):
        rec = finance_ledger.record_entry(self.root, 1500, "in", note="เบิก")
        updated = finance_ledger.set_status(self.root, rec["id"], "received")
        self.assertEqual(updated["status"], "received")
        self.assertEqual(finance_ledger.set_status(self.root, 99999, "received"), None)

    def test_set_status_validates_direction(self):
        rec = finance_ledger.record_entry(self.root, 1500, "in")
        with self.assertRaises(ValueError):
            finance_ledger.set_status(self.root, rec["id"], "paid")  # in -> paid ไม่ได้
        with self.assertRaises(ValueError):
            finance_ledger.set_status(self.root, rec["id"], "bogus")

    def test_set_status_out_to_paid(self):
        rec = finance_ledger.record_entry(self.root, 500, "out")
        updated = finance_ledger.set_status(self.root, rec["id"], "paid")
        self.assertEqual(updated["status"], "paid")

    def test_set_status_missing_id_returns_none(self):
        result = finance_ledger.set_status(self.root, 99999, "cancelled")
        self.assertIsNone(result)

    # ---- delete ----
    def test_delete(self):
        rec = finance_ledger.record_entry(self.root, 50, "out")
        self.assertTrue(finance_ledger.delete_entry(self.root, rec["id"]))
        self.assertFalse(finance_ledger.delete_entry(self.root, rec["id"]))

    # ---- summary ----
    def test_summary_balance(self):
        a = finance_ledger.record_entry(self.root, 1500, "in", note="เบิก")
        finance_ledger.set_status(self.root, a["id"], "received")
        b = finance_ledger.record_entry(self.root, 400, "out", note="ค่าบริการ")
        finance_ledger.set_status(self.root, b["id"], "paid")
        finance_ledger.record_entry(self.root, 999, "in")  # pending — ไม่นับ balance
        s = finance_ledger.summary(self.root)
        self.assertEqual(s["received_in"], 1500.0)
        self.assertEqual(s["paid_out"], 400.0)
        self.assertEqual(s["pending_in"], 999.0)
        self.assertEqual(s["balance"], 1100.0)
        self.assertEqual(s["count"], 3)

    def test_summary_empty(self):
        s = finance_ledger.summary(self.root)
        self.assertEqual(s["balance"], 0)
        self.assertEqual(s["count"], 0)

    def test_summary_has_required_keys(self):
        s = finance_ledger.summary(self.root)
        for key in ("received_in", "paid_out", "pending_in", "balance", "count"):
            self.assertIn(key, s)


if __name__ == "__main__":
    unittest.main()
