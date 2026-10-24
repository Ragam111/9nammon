"""test_agent_worker.py — worker 24/7 (ดึงงาน→รัน→วัดผล) + stats (วัดผล)"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import core, stats as stats_mod, worker  # noqa: E402


class StatsTest(unittest.TestCase):
    def test_empty_summary(self):
        s = stats_mod.Stats()
        self.assertEqual(s.summary()["count"], 0)

    def test_summary_math(self):
        s = stats_mod.Stats()
        s.record({"ok": True, "duration_s": 2.0, "steps": 3})
        s.record({"ok": False, "duration_s": 4.0, "steps": 5})
        summ = s.summary()
        self.assertEqual(summ["count"], 2)
        self.assertEqual(summ["ok"], 1)
        self.assertEqual(summ["success_rate"], 0.5)
        self.assertEqual(summ["avg_duration_s"], 3.0)
        self.assertEqual(summ["avg_steps"], 4.0)
        self.assertEqual(summ["est_per_day"], int(86400 / 3.0))   # throughput ต่อ 1 worker

    def test_recent_capped(self):
        s = stats_mod.Stats()
        for i in range(stats_mod.MAX_RECENT + 50):
            s.record({"ok": True, "duration_s": 1, "steps": 1, "task": str(i)})
        self.assertEqual(len(s.recent(99999)), stats_mod.MAX_RECENT)


class _Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


class RunOneTest(unittest.TestCase):
    def test_run_one_times_and_flags_ok(self):
        clk = _Clock()
        def fake_run(root, task, workspace, model, max_steps):
            clk.t += 1.5   # จำลองใช้เวลา 1.5s
            return {"final": "ตอบแล้ว", "steps": [{}, {}], "stopped_reason": "final"}
        with mock.patch.object(core, "run", fake_run):
            rec = worker.run_one(".", "โจทย์", ".", clock=clk)
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["duration_s"], 1.5)
        self.assertEqual(rec["steps"], 2)

    def test_run_one_max_steps_not_ok(self):
        with mock.patch.object(core, "run",
                               lambda *a, **k: {"final": None, "steps": [{}], "stopped_reason": "max_steps"}):
            rec = worker.run_one(".", "โจทย์", ".", clock=_Clock())
        self.assertFalse(rec["ok"])

    def test_run_one_exception_becomes_record(self):
        def boom(*a, **k): raise RuntimeError("LLM ล่ม")
        with mock.patch.object(core, "run", boom):
            rec = worker.run_one(".", "โจทย์", ".", clock=_Clock())
        self.assertFalse(rec["ok"])
        self.assertEqual(rec["stopped_reason"], "error")
        self.assertIn("LLM ล่ม", rec["error"])


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(
            core, "run",
            lambda root, task, workspace, model, max_steps: {
                "final": f"done:{task}", "steps": [{}], "stopped_reason": "final"})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_tick_no_job_returns_none(self):
        w = worker.Worker(claim_fn=lambda: None, clock=_Clock())
        self.assertIsNone(w.tick())

    def test_tick_processes_and_records(self):
        done = []
        jobs = [{"task": "งาน1", "workspace": "."}]
        w = worker.Worker(claim_fn=lambda: jobs.pop(0) if jobs else None,
                          done_fn=done.append, clock=_Clock())
        rec = w.tick()
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["task"], "งาน1")
        self.assertEqual(len(done), 1)                 # done_fn ถูกเรียก
        self.assertEqual(w.stats.summary()["count"], 1)  # เก็บ stats

    def test_done_fn_failure_does_not_crash_tick(self):
        def bad(rec): raise ValueError("แจ้งผลพัง")
        jobs = [{"task": "x", "workspace": "."}]
        w = worker.Worker(claim_fn=lambda: jobs.pop(0) if jobs else None,
                          done_fn=bad, clock=_Clock())
        rec = w.tick()           # ต้องไม่ raise
        self.assertTrue(rec["ok"])


if __name__ == "__main__":
    unittest.main()
