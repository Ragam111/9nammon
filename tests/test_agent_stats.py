"""test_agent_stats.py — Stats: record, summary, recent, file persistence"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.stats import Stats, MAX_RECENT  # noqa: E402


class RecordTest(unittest.TestCase):
    def test_record_appears_in_recent(self):
        s = Stats()
        s.record({"task": "a", "ok": True, "duration_s": 1, "steps": 2})
        self.assertEqual(len(s.recent()), 1)

    def test_record_multiple(self):
        s = Stats()
        for i in range(5):
            s.record({"task": f"t{i}", "ok": True, "duration_s": 1, "steps": 1})
        self.assertEqual(len(s.recent(50)), 5)

    def test_recent_limit(self):
        s = Stats()
        for i in range(10):
            s.record({"task": f"t{i}", "ok": True, "duration_s": 1, "steps": 1})
        self.assertEqual(len(s.recent(3)), 3)

    def test_recent_returns_latest(self):
        s = Stats()
        s.record({"task": "old", "ok": True, "duration_s": 1, "steps": 1})
        s.record({"task": "new", "ok": True, "duration_s": 1, "steps": 1})
        last = s.recent(1)[0]
        self.assertEqual(last["task"], "new")

    def test_max_recent_cap(self):
        s = Stats()
        for i in range(MAX_RECENT + 50):
            s.record({"task": f"t{i}", "ok": True, "duration_s": 1, "steps": 1})
        self.assertEqual(len(s.recent(MAX_RECENT + 100)), MAX_RECENT)


class SummaryTest(unittest.TestCase):
    def test_empty_summary(self):
        s = Stats()
        sm = s.summary()
        self.assertEqual(sm["count"], 0)
        self.assertEqual(sm["ok"], 0)
        self.assertEqual(sm["success_rate"], 0.0)

    def test_all_ok(self):
        s = Stats()
        for _ in range(4):
            s.record({"ok": True, "duration_s": 10, "steps": 3})
        sm = s.summary()
        self.assertEqual(sm["count"], 4)
        self.assertEqual(sm["ok"], 4)
        self.assertEqual(sm["success_rate"], 1.0)

    def test_mixed_ok(self):
        s = Stats()
        s.record({"ok": True, "duration_s": 5, "steps": 2})
        s.record({"ok": False, "duration_s": 3, "steps": 1})
        sm = s.summary()
        self.assertEqual(sm["count"], 2)
        self.assertEqual(sm["ok"], 1)
        self.assertEqual(sm["success_rate"], 0.5)

    def test_avg_duration(self):
        s = Stats()
        s.record({"ok": True, "duration_s": 10, "steps": 1})
        s.record({"ok": True, "duration_s": 20, "steps": 1})
        sm = s.summary()
        self.assertEqual(sm["avg_duration_s"], 15.0)

    def test_avg_steps(self):
        s = Stats()
        s.record({"ok": True, "duration_s": 1, "steps": 4})
        s.record({"ok": True, "duration_s": 1, "steps": 6})
        sm = s.summary()
        self.assertEqual(sm["avg_steps"], 5.0)

    def test_est_per_day(self):
        s = Stats()
        s.record({"ok": True, "duration_s": 10, "steps": 1})
        sm = s.summary()
        self.assertEqual(sm["est_per_day"], 8640)


class FilePersistenceTest(unittest.TestCase):
    def test_records_appended_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "stats.jsonl"
            s = Stats(path=p)
            s.record({"task": "a", "ok": True, "duration_s": 1, "steps": 1})
            s.record({"task": "b", "ok": False, "duration_s": 2, "steps": 3})
            lines = p.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["task"], "a")
            self.assertEqual(json.loads(lines[1])["task"], "b")

    def test_no_file_when_path_none(self):
        s = Stats()
        s.record({"task": "x", "ok": True, "duration_s": 1, "steps": 1})
        self.assertIsNone(s.path)


if __name__ == "__main__":
    unittest.main()
