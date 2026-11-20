"""
test_history_store.py — unittest สำหรับ history/log SQLite layer (stdlib เท่านั้น)

Covers:
  Module constants    — HISTORY_DB_NAME, VALID_LEVELS
  record_snapshot()   — validation (non-dict raises), return shape (all fields,
                        cpu/mem stored, raw parsed back, partial/empty dict → None)
  list_snapshots()    — empty [], no raw key, newest-first, limit
  log_error()         — validation (bad level, empty/whitespace message), return shape
                        (all fields, level normalized, None/whitespace source → None)
  list_errors()       — empty [], newest-first, level filter, limit
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import history_store  # noqa: E402


class _TmpRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _report(self, cpu=12.0, mem=34.0, verdict="ok", worst="OK"):
        return {
            "snapshot": {"cpu": {"percent": cpu}, "memory": {"percent": mem}},
            "verdict": verdict,
            "worst_severity": worst,
        }


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants(unittest.TestCase):
    def test_history_db_name_is_string(self):
        self.assertIsInstance(history_store.HISTORY_DB_NAME, str)

    def test_history_db_name_ends_with_db(self):
        self.assertTrue(history_store.HISTORY_DB_NAME.endswith(".db"))

    def test_valid_levels_is_set(self):
        self.assertIsInstance(history_store.VALID_LEVELS, (set, frozenset))

    def test_valid_levels_contains_error(self):
        self.assertIn("error", history_store.VALID_LEVELS)

    def test_valid_levels_contains_all_expected(self):
        for lvl in ("debug", "info", "warning", "error", "critical"):
            self.assertIn(lvl, history_store.VALID_LEVELS)


# ---------------------------------------------------------------------------
# record_snapshot — validation
# ---------------------------------------------------------------------------

class TestRecordSnapshotValidation(_TmpRoot):
    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            history_store.record_snapshot(self.root, "not a dict")

    def test_list_raises(self):
        with self.assertRaises(ValueError):
            history_store.record_snapshot(self.root, [])

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            history_store.record_snapshot(self.root, None)


# ---------------------------------------------------------------------------
# record_snapshot — return shape
# ---------------------------------------------------------------------------

class TestRecordSnapshotShape(_TmpRoot):
    def test_returns_dict(self):
        self.assertIsInstance(history_store.record_snapshot(self.root, self._report()), dict)

    def test_has_all_expected_fields(self):
        s = history_store.record_snapshot(self.root, self._report())
        for field in ("id", "recorded_at", "verdict", "worst_severity", "cpu_percent", "mem_percent", "raw"):
            self.assertIn(field, s)

    def test_cpu_mem_stored_correctly(self):
        s = history_store.record_snapshot(self.root, self._report(cpu=55.5, mem=77.7))
        self.assertAlmostEqual(s["cpu_percent"], 55.5, places=1)
        self.assertAlmostEqual(s["mem_percent"], 77.7, places=1)

    def test_verdict_and_worst_stored(self):
        s = history_store.record_snapshot(self.root, self._report(verdict="warn", worst="WARN"))
        self.assertEqual(s["verdict"], "warn")
        self.assertEqual(s["worst_severity"], "WARN")

    def test_raw_parsed_back_to_dict(self):
        report = self._report()
        s = history_store.record_snapshot(self.root, report)
        self.assertIsInstance(s["raw"], dict)
        self.assertEqual(s["raw"]["verdict"], "ok")

    def test_partial_dict_cpu_none(self):
        s = history_store.record_snapshot(self.root, {"verdict": "x"})
        self.assertIsNone(s["cpu_percent"])
        self.assertIsNone(s["mem_percent"])

    def test_empty_snapshot_key_cpu_none(self):
        s = history_store.record_snapshot(self.root, {"snapshot": {}, "verdict": "y"})
        self.assertIsNone(s["cpu_percent"])


# ---------------------------------------------------------------------------
# list_snapshots
# ---------------------------------------------------------------------------

class TestListSnapshots(_TmpRoot):
    def test_empty_db_returns_empty_list(self):
        self.assertEqual(history_store.list_snapshots(self.root), [])

    def test_list_has_no_raw_key(self):
        history_store.record_snapshot(self.root, self._report())
        rows = history_store.list_snapshots(self.root)
        self.assertNotIn("raw", rows[0])

    def test_newest_first_ordering(self):
        history_store.record_snapshot(self.root, self._report(verdict="first"))
        history_store.record_snapshot(self.root, self._report(verdict="second"))
        rows = history_store.list_snapshots(self.root)
        self.assertEqual(rows[0]["verdict"], "second")

    def test_limit_parameter(self):
        for i in range(5):
            history_store.record_snapshot(self.root, self._report(cpu=float(i)))
        rows = history_store.list_snapshots(self.root, limit=3)
        self.assertEqual(len(rows), 3)

    def test_cpu_percent_accessible_in_list(self):
        history_store.record_snapshot(self.root, self._report(cpu=42.0))
        rows = history_store.list_snapshots(self.root)
        self.assertAlmostEqual(rows[0]["cpu_percent"], 42.0, places=1)


# ---------------------------------------------------------------------------
# log_error — validation
# ---------------------------------------------------------------------------

class TestLogErrorValidation(_TmpRoot):
    def test_bad_level_raises(self):
        with self.assertRaises(ValueError):
            history_store.log_error(self.root, "bogus", "src", "msg")

    def test_empty_level_raises(self):
        with self.assertRaises(ValueError):
            history_store.log_error(self.root, "", "src", "msg")

    def test_empty_message_raises(self):
        with self.assertRaises(ValueError):
            history_store.log_error(self.root, "error", "src", "")

    def test_whitespace_message_raises(self):
        with self.assertRaises(ValueError):
            history_store.log_error(self.root, "error", "src", "   ")

    def test_invalid_list_level_raises(self):
        with self.assertRaises(ValueError):
            history_store.list_errors(self.root, level="bogus")


# ---------------------------------------------------------------------------
# log_error — return shape
# ---------------------------------------------------------------------------

class TestLogErrorShape(_TmpRoot):
    def test_returns_dict(self):
        self.assertIsInstance(
            history_store.log_error(self.root, "info", "s", "m"), dict)

    def test_has_all_expected_fields(self):
        e = history_store.log_error(self.root, "info", "s", "m")
        for field in ("id", "logged_at", "level", "source", "message"):
            self.assertIn(field, e)

    def test_level_stored_as_given(self):
        e = history_store.log_error(self.root, "warning", "s", "m")
        self.assertEqual(e["level"], "warning")

    def test_level_uppercased_input_normalized(self):
        e = history_store.log_error(self.root, "ERROR", "s", "m")
        self.assertEqual(e["level"], "error")

    def test_source_stored_when_given(self):
        e = history_store.log_error(self.root, "info", "mymodule", "m")
        self.assertEqual(e["source"], "mymodule")

    def test_empty_source_stored_as_none(self):
        e = history_store.log_error(self.root, "info", "", "m")
        self.assertIsNone(e["source"])

    def test_whitespace_source_stored_as_none(self):
        e = history_store.log_error(self.root, "info", "   ", "m")
        self.assertIsNone(e["source"])

    def test_message_stored_correctly(self):
        e = history_store.log_error(self.root, "info", "s", "hello world")
        self.assertEqual(e["message"], "hello world")


# ---------------------------------------------------------------------------
# list_errors
# ---------------------------------------------------------------------------

class TestListErrors(_TmpRoot):
    def test_empty_db_returns_empty_list(self):
        self.assertEqual(history_store.list_errors(self.root), [])

    def test_newest_first_ordering(self):
        history_store.log_error(self.root, "info", "a", "one")
        history_store.log_error(self.root, "info", "a", "two")
        errs = history_store.list_errors(self.root)
        self.assertEqual(errs[0]["message"], "two")

    def test_level_filter(self):
        history_store.log_error(self.root, "error", "s", "err1")
        history_store.log_error(self.root, "info", "s", "inf1")
        errs = history_store.list_errors(self.root, level="error")
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["message"], "err1")

    def test_level_filter_no_match_returns_empty(self):
        history_store.log_error(self.root, "info", "s", "m")
        self.assertEqual(history_store.list_errors(self.root, level="critical"), [])

    def test_limit_parameter(self):
        for i in range(5):
            history_store.log_error(self.root, "info", "s", f"msg{i}")
        errs = history_store.list_errors(self.root, limit=3)
        self.assertEqual(len(errs), 3)


if __name__ == "__main__":
    unittest.main()
