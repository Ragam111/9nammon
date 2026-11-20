"""
test_usage_store.py — unittest สำหรับ usage metering (SQLite, stdlib)

Covers:
  _unit_price()    — known tiers, unknown tier, None tier
  record_usage()   — happy path, bad units (0/-/str), None fields, custom units,
                     return shape, empty endpoint normalization
  list_usage()     — newest first, key_id filter, limit param, no-match returns []
  summary()        — shape/required keys, currency key, unknown-tier bucketing,
                     by_key ordering by units DESC, cost formula, empty db
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import usage_store  # noqa: E402


class _TmpRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# _unit_price helper
# ---------------------------------------------------------------------------

class TestUnitPrice(unittest.TestCase):
    def test_free_tier_is_zero(self):
        self.assertEqual(usage_store._unit_price("free"), 0.0)

    def test_paid_tier_is_nonzero(self):
        self.assertGreater(usage_store._unit_price("paid"), 0.0)

    def test_unknown_tier_returns_default(self):
        self.assertEqual(usage_store._unit_price("enterprise"),
                         usage_store._DEFAULT_PRICE)

    def test_none_tier_returns_default(self):
        self.assertEqual(usage_store._unit_price(None),
                         usage_store._DEFAULT_PRICE)

    def test_empty_string_returns_default(self):
        self.assertEqual(usage_store._unit_price(""),
                         usage_store._DEFAULT_PRICE)


# ---------------------------------------------------------------------------
# record_usage — validation
# ---------------------------------------------------------------------------

class TestRecordUsageValidation(_TmpRoot):
    def test_zero_units_raises(self):
        with self.assertRaises(ValueError):
            usage_store.record_usage(self.root, "k", "owner", "free", units=0)

    def test_negative_units_raises(self):
        with self.assertRaises(ValueError):
            usage_store.record_usage(self.root, "k", "owner", "free", units=-3)

    def test_non_numeric_units_raises(self):
        with self.assertRaises(ValueError):
            usage_store.record_usage(self.root, "k", "owner", "free", units="x")


# ---------------------------------------------------------------------------
# record_usage — happy path and return shape
# ---------------------------------------------------------------------------

class TestRecordUsageShape(_TmpRoot):
    def test_returns_dict(self):
        rec = usage_store.record_usage(self.root, "k1", "dev", "free")
        self.assertIsInstance(rec, dict)

    def test_return_has_all_expected_fields(self):
        rec = usage_store.record_usage(self.root, "k1", "dev", "free")
        for field in ("id", "used_at", "key_id", "owner", "tier", "endpoint", "units"):
            self.assertIn(field, rec)

    def test_default_units_is_one(self):
        rec = usage_store.record_usage(self.root, "k1", "dev", "free")
        self.assertEqual(rec["units"], 1)

    def test_default_endpoint_is_chat(self):
        rec = usage_store.record_usage(self.root, "k1", "dev", "free")
        self.assertEqual(rec["endpoint"], "chat")

    def test_custom_units_stored(self):
        rec = usage_store.record_usage(self.root, "k1", "dev", "paid", units=5)
        self.assertEqual(rec["units"], 5)

    def test_none_key_id_stored(self):
        rec = usage_store.record_usage(self.root, None, "dev", "free")
        self.assertIsNone(rec["key_id"])

    def test_none_tier_stored_as_none(self):
        rec = usage_store.record_usage(self.root, "k1", "dev", None)
        self.assertIsNone(rec["tier"])


# ---------------------------------------------------------------------------
# list_usage
# ---------------------------------------------------------------------------

class TestListUsage(_TmpRoot):
    def test_empty_db_returns_empty_list(self):
        self.assertEqual(usage_store.list_usage(self.root), [])

    def test_basic_record_and_list(self):
        usage_store.record_usage(self.root, "k1", "dev", "free")
        rows = usage_store.list_usage(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key_id"], "k1")

    def test_newest_first_ordering(self):
        usage_store.record_usage(self.root, "k1", "a", "free", endpoint="first")
        usage_store.record_usage(self.root, "k2", "b", "paid", endpoint="second")
        rows = usage_store.list_usage(self.root)
        self.assertEqual(rows[0]["endpoint"], "second")

    def test_key_id_filter(self):
        usage_store.record_usage(self.root, "k1", "a", "free")
        usage_store.record_usage(self.root, "k2", "b", "paid")
        rows = usage_store.list_usage(self.root, key_id="k1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key_id"], "k1")

    def test_key_id_filter_no_match_returns_empty(self):
        usage_store.record_usage(self.root, "k1", "a", "free")
        rows = usage_store.list_usage(self.root, key_id="nonexistent")
        self.assertEqual(rows, [])

    def test_limit_parameter_respected(self):
        for i in range(5):
            usage_store.record_usage(self.root, f"k{i}", "a", "free")
        rows = usage_store.list_usage(self.root, limit=2)
        self.assertEqual(len(rows), 2)


# ---------------------------------------------------------------------------
# summary — shape
# ---------------------------------------------------------------------------

class TestSummaryShape(_TmpRoot):
    def test_empty_db_shape(self):
        s = usage_store.summary(self.root)
        self.assertEqual(s["total_units"], 0)
        self.assertEqual(s["total_cost"], 0.0)
        self.assertEqual(s["by_key"], [])

    def test_has_all_top_level_keys(self):
        s = usage_store.summary(self.root)
        for key in ("total_units", "total_cost", "currency", "by_tier", "by_key"):
            self.assertIn(key, s)

    def test_currency_key_present(self):
        s = usage_store.summary(self.root)
        self.assertIn("currency", s)
        self.assertIsInstance(s["currency"], str)

    def test_by_tier_entry_has_required_fields(self):
        usage_store.record_usage(self.root, "k1", "a", "paid")
        s = usage_store.summary(self.root)
        for field in ("units", "events", "unit_price", "cost"):
            self.assertIn(field, s["by_tier"]["paid"])


# ---------------------------------------------------------------------------
# summary — cost and ordering
# ---------------------------------------------------------------------------

class TestSummaryCostOrdering(_TmpRoot):
    def test_free_cost_is_zero(self):
        for _ in range(2):
            usage_store.record_usage(self.root, "kf", "freeuser", "free")
        s = usage_store.summary(self.root)
        self.assertEqual(s["by_tier"]["free"]["cost"], 0.0)

    def test_paid_cost_formula(self):
        for _ in range(3):
            usage_store.record_usage(self.root, "kp", "paiduser", "paid")
        s = usage_store.summary(self.root)
        expected = round(3 * usage_store.TIER_UNIT_PRICE["paid"], 2)
        self.assertEqual(s["by_tier"]["paid"]["cost"], expected)

    def test_total_cost_sums_all_tiers(self):
        for _ in range(2):
            usage_store.record_usage(self.root, "kf", "freeuser", "free")
        for _ in range(3):
            usage_store.record_usage(self.root, "kp", "paiduser", "paid")
        s = usage_store.summary(self.root)
        self.assertEqual(s["total_units"], 5)
        self.assertEqual(s["total_cost"], round(3 * usage_store.TIER_UNIT_PRICE["paid"], 2))

    def test_unknown_tier_bucketed_as_unknown(self):
        usage_store.record_usage(self.root, "k1", "a", None)
        s = usage_store.summary(self.root)
        self.assertIn("unknown", s["by_tier"])

    def test_by_key_ordered_by_units_desc(self):
        usage_store.record_usage(self.root, "k_small", "a", "paid", units=1)
        usage_store.record_usage(self.root, "k_large", "b", "paid", units=5)
        s = usage_store.summary(self.root)
        self.assertEqual(s["by_key"][0]["key_id"], "k_large")

    def test_by_key_entry_has_cost(self):
        usage_store.record_usage(self.root, "kp", "paiduser", "paid", units=2)
        s = usage_store.summary(self.root)
        top = s["by_key"][0]
        self.assertEqual(top["cost"], round(2 * usage_store.TIER_UNIT_PRICE["paid"], 2))


if __name__ == "__main__":
    unittest.main()
