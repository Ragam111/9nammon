"""
test_usage_store.py — unittest สำหรับ usage metering (SQLite, stdlib)

Covers:
  UsageStoreTest      — record_and_list, record_rejects_bad_units, list (newest first, filter),
                        summary units+cost, summary by_key, summary empty
  UsageStoreMetaTest  — record returns dict with required fields, record has recorded_at,
                        list all returns multiple rows, filter by tier, summary has required keys,
                        total_cost is float, record multiple units
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import usage_store  # noqa: E402


class UsageStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_and_list(self):
        rec = usage_store.record_usage(self.root, "k1", "dev", "free")
        self.assertEqual(rec["key_id"], "k1")
        self.assertEqual(rec["units"], 1)
        self.assertEqual(rec["endpoint"], "chat")
        rows = usage_store.list_usage(self.root)
        self.assertEqual(len(rows), 1)

    def test_record_rejects_bad_units(self):
        with self.assertRaises(ValueError):
            usage_store.record_usage(self.root, "k1", "dev", "free", units=0)
        with self.assertRaises(ValueError):
            usage_store.record_usage(self.root, "k1", "dev", "free", units=-3)
        with self.assertRaises(ValueError):
            usage_store.record_usage(self.root, "k1", "dev", "free", units="x")

    def test_list_newest_first_and_filter(self):
        usage_store.record_usage(self.root, "k1", "a", "free", endpoint="first")
        usage_store.record_usage(self.root, "k2", "b", "paid", endpoint="second")
        rows = usage_store.list_usage(self.root)
        self.assertEqual(rows[0]["endpoint"], "second")
        self.assertEqual(len(usage_store.list_usage(self.root, key_id="k1")), 1)

    def test_summary_units_and_cost(self):
        for _ in range(2):
            usage_store.record_usage(self.root, "kf", "freeuser", "free")
        for _ in range(3):
            usage_store.record_usage(self.root, "kp", "paiduser", "paid")
        s = usage_store.summary(self.root)
        self.assertEqual(s["total_units"], 5)
        self.assertEqual(s["by_tier"]["free"]["units"], 2)
        self.assertEqual(s["by_tier"]["free"]["cost"], 0.0)
        self.assertEqual(s["by_tier"]["paid"]["units"], 3)
        self.assertEqual(s["by_tier"]["paid"]["cost"], 0.30)
        self.assertEqual(s["total_cost"], 0.30)

    def test_summary_by_key(self):
        usage_store.record_usage(self.root, "kp", "paiduser", "paid", units=2)
        s = usage_store.summary(self.root)
        top = s["by_key"][0]
        self.assertEqual(top["key_id"], "kp")
        self.assertEqual(top["units"], 2)
        self.assertEqual(top["cost"], 0.20)

    def test_summary_empty(self):
        s = usage_store.summary(self.root)
        self.assertEqual(s["total_units"], 0)
        self.assertEqual(s["total_cost"], 0.0)
        self.assertEqual(s["by_key"], [])

    def test_record_returns_dict_with_required_fields(self):
        rec = usage_store.record_usage(self.root, "k1", "u", "free")
        for field in ("key_id", "units", "endpoint"):
            self.assertIn(field, rec, f"missing field: {field}")

    def test_record_has_used_at(self):
        rec = usage_store.record_usage(self.root, "k1", "u", "free")
        self.assertIn("used_at", rec)

    def test_list_multiple_records(self):
        for i in range(5):
            usage_store.record_usage(self.root, f"k{i}", "u", "free")
        rows = usage_store.list_usage(self.root)
        self.assertEqual(len(rows), 5)

    def test_summary_has_required_keys(self):
        s = usage_store.summary(self.root)
        for key in ("total_units", "total_cost", "by_tier", "by_key"):
            self.assertIn(key, s, f"summary ต้องมี key: {key}")

    def test_total_cost_is_float(self):
        usage_store.record_usage(self.root, "k", "u", "paid")
        s = usage_store.summary(self.root)
        self.assertIsInstance(s["total_cost"], float)

    def test_record_multiple_units(self):
        rec = usage_store.record_usage(self.root, "k1", "u", "paid", units=5)
        self.assertEqual(rec["units"], 5)
        s = usage_store.summary(self.root)
        self.assertEqual(s["total_units"], 5)

    def test_list_filter_by_key_id_returns_only_that_key(self):
        usage_store.record_usage(self.root, "key-A", "u", "free")
        usage_store.record_usage(self.root, "key-B", "u", "free")
        usage_store.record_usage(self.root, "key-A", "u", "free")
        rows = usage_store.list_usage(self.root, key_id="key-A")
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertEqual(r["key_id"], "key-A")


if __name__ == "__main__":
    unittest.main()
