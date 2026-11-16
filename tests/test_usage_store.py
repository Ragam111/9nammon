"""
test_usage_store.py — unittest สำหรับ usage metering (SQLite, stdlib)
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
        self.assertEqual(rows[0]["endpoint"], "second")  # ใหม่สุดก่อน
        self.assertEqual(len(usage_store.list_usage(self.root, key_id="k1")), 1)

    def test_summary_units_and_cost(self):
        # free 2 ครั้ง (ฟรี cost 0), paid 3 ครั้ง (0.10 * 3 = 0.30)
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


if __name__ == "__main__":
    unittest.main()
