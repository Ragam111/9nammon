"""
test_history_store.py — unittest สำหรับ history/log SQLite layer (stdlib เท่านั้น)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import history_store  # noqa: E402


class HistoryStoreTest(unittest.TestCase):
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

    def test_record_and_list_snapshot(self):
        stored = history_store.record_snapshot(self.root, self._report(cpu=50.0, mem=60.0))
        self.assertEqual(stored["cpu_percent"], 50.0)
        self.assertEqual(stored["mem_percent"], 60.0)
        self.assertEqual(stored["raw"]["verdict"], "ok")
        rows = history_store.list_snapshots(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["worst_severity"], "OK")
        self.assertNotIn("raw", rows[0])  # list ไม่ส่ง raw json หนัก ๆ

    def test_record_snapshot_defensive_on_partial_dict(self):
        stored = history_store.record_snapshot(self.root, {"verdict": "x"})
        self.assertIsNone(stored["cpu_percent"])
        self.assertIsNone(stored["mem_percent"])

    def test_record_snapshot_rejects_non_dict(self):
        with self.assertRaises(ValueError):
            history_store.record_snapshot(self.root, "not a dict")

    def test_snapshots_newest_first(self):
        history_store.record_snapshot(self.root, self._report(verdict="first"))
        history_store.record_snapshot(self.root, self._report(verdict="second"))
        rows = history_store.list_snapshots(self.root)
        self.assertEqual(rows[0]["verdict"], "second")

    def test_log_error_and_list(self):
        history_store.log_error(self.root, "error", "server", "boom")
        history_store.log_error(self.root, "info", "server", "hi")
        self.assertEqual(len(history_store.list_errors(self.root)), 2)
        errs = history_store.list_errors(self.root, level="error")
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["message"], "boom")

    def test_log_error_validates(self):
        with self.assertRaises(ValueError):
            history_store.log_error(self.root, "bogus", "s", "m")
        with self.assertRaises(ValueError):
            history_store.log_error(self.root, "error", "s", "   ")
        with self.assertRaises(ValueError):
            history_store.list_errors(self.root, level="bogus")

    def test_errors_newest_first(self):
        history_store.log_error(self.root, "info", "a", "one")
        history_store.log_error(self.root, "info", "a", "two")
        errs = history_store.list_errors(self.root)
        self.assertEqual(errs[0]["message"], "two")


if __name__ == "__main__":
    unittest.main()
