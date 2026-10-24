"""test_watchdog.py — เทส self-monitor 24/7: evaluate (pure) + Watchdog.tick (debounce)"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import watchdog as wd  # noqa: E402


class EvaluateTest(unittest.TestCase):
    def test_all_healthy_no_findings(self):
        self.assertEqual(wd.evaluate(ollama_up=True, ram_pressure=False, cluster_down=0), [])

    def test_ollama_down_is_critical(self):
        f = wd.evaluate(ollama_up=False, ram_pressure=False)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["key"], "ollama")
        self.assertEqual(f[0]["level"], wd.CRITICAL)

    def test_ram_pressure_is_warning(self):
        f = wd.evaluate(ollama_up=True, ram_pressure=True)
        self.assertEqual(f[0]["key"], "ram")
        self.assertEqual(f[0]["level"], wd.WARNING)

    def test_cluster_down_reported(self):
        f = wd.evaluate(ollama_up=True, ram_pressure=False, cluster_down=2)
        self.assertEqual(f[0]["key"], "cluster")
        self.assertIn("2", f[0]["msg"])

    def test_multiple_findings(self):
        f = wd.evaluate(ollama_up=False, ram_pressure=True, cluster_down=1)
        keys = {x["key"] for x in f}
        self.assertEqual(keys, {"ollama", "ram", "cluster"})


class _FakeClock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


class WatchdogTickTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.clock = _FakeClock()

    def _wd(self, findings):
        return wd.Watchdog(check_fn=lambda: findings,
                           notify_fn=lambda lvl, msg: self.sent.append((lvl, msg)),
                           min_notify_gap=300.0, clock=self.clock)

    def test_notifies_on_finding(self):
        w = self._wd([{"key": "ollama", "level": "critical", "msg": "ล่ม"}])
        w.tick()
        self.assertEqual(len(self.sent), 1)

    def test_debounce_no_repeat_within_gap(self):
        w = self._wd([{"key": "ollama", "level": "critical", "msg": "ล่ม"}])
        w.tick(); w.tick(); w.tick()           # เวลาไม่ขยับ → เตือนครั้งเดียว
        self.assertEqual(len(self.sent), 1)

    def test_notifies_again_after_gap(self):
        w = self._wd([{"key": "ollama", "level": "critical", "msg": "ล่ม"}])
        w.tick()
        self.clock.t = 301.0                   # เลย min_notify_gap → เตือนซ้ำได้
        w.tick()
        self.assertEqual(len(self.sent), 2)

    def test_no_findings_no_notify(self):
        w = self._wd([])
        w.tick()
        self.assertEqual(self.sent, [])

    def test_notify_failure_does_not_crash_tick(self):
        def boom(lvl, msg): raise RuntimeError("notify พัง")
        w = wd.Watchdog(check_fn=lambda: [{"key": "x", "level": "warning", "msg": "y"}],
                        notify_fn=boom, clock=self.clock)
        # tick ต้องไม่โยน error ออกมา (การเตือนล้ม ต้องไม่ล้ม watchdog)
        self.assertEqual(w.tick()[0]["key"], "x")

    def test_last_findings_recorded(self):
        w = self._wd([{"key": "ram", "level": "warning", "msg": "ตึง"}])
        w.tick()
        self.assertEqual(w.last_findings[0]["key"], "ram")


if __name__ == "__main__":
    unittest.main()
