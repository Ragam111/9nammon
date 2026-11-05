"""test_admission.py — เทสยามคุม generation พร้อมกัน (admission control)

ใช้ threading จริง + event sync ให้ deterministic (ไม่พึ่ง sleep เดา):
- รันตามลำดับได้ปกติ (ไม่บล็อกตัวเอง)
- เครื่องเต็ม + รอเกิน max_wait → Busy (timeout)
- คิวเต็ม (waiting >= max_queue) → Busy ทันที
- gate_from_config: อ่าน config, ค่าพัง/ไม่ตั้ง → default 1

Covers:
  AdmissionGateTest    — sequential OK, concurrent timeout, queue full immediate,
                         busy no waiting leak, stats waiting zero after bust
  GateFromConfigTest   — default when unset, reads config value, bad value fallback,
                         zero clamped to 1
  AdmissionMetaTest    — Busy is Exception, stats returns dict with keys, max_concurrent
                         stored, stats waiting zero at start, max_queue stored,
                         large max_concurrent accepted, negative max_wait no crash
"""

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import admission  # noqa: E402


class AdmissionGateTest(unittest.TestCase):
    def test_sequential_acquire_release_ok(self):
        g = admission.AdmissionGate(max_concurrent=1)
        for _ in range(5):
            with g.slot():
                pass  # ปล่อยแล้วรอบถัดไปต้องเข้าได้ ไม่บล็อกตัวเอง
        self.assertEqual(g.stats()["waiting"], 0)

    def test_concurrent_over_limit_times_out_busy(self):
        # max_concurrent=1: ถือสล็อตไว้ 1 ตัว อีกตัวต้อง Busy เพราะรอเกิน max_wait
        g = admission.AdmissionGate(max_concurrent=1, max_wait=0.2, max_queue=8)
        acquired = threading.Event()
        release = threading.Event()

        def holder():
            with g.slot():
                acquired.set()
                release.wait(2)

        t = threading.Thread(target=holder, daemon=True)
        t.start()
        self.assertTrue(acquired.wait(2), "holder ควรได้สล็อตแรก")
        with self.assertRaises(admission.Busy):
            with g.slot():     # สล็อตเต็ม รอ 0.2s แล้ว Busy
                pass
        release.set()
        t.join(2)

    def test_queue_full_rejects_immediately(self):
        # max_queue=1: ถือสล็อต + มีคนรอ 1 แล้ว คนที่ 3 ต้อง Busy ทันที (ไม่ต่อแถว)
        g = admission.AdmissionGate(max_concurrent=1, max_wait=5.0, max_queue=1)
        acquired = threading.Event()
        release = threading.Event()

        def holder():
            with g.slot():
                acquired.set()
                release.wait(3)

        def waiter():
            try:
                with g.slot():
                    pass
            except admission.Busy:
                pass

        th = threading.Thread(target=holder, daemon=True)
        th.start()
        self.assertTrue(acquired.wait(2))
        tw = threading.Thread(target=waiter, daemon=True)
        tw.start()
        # รอให้ waiter เข้าไปนั่งในคิว (waiting==1) ก่อน — poll ไม่เดาเวลา
        for _ in range(200):
            if g.stats()["waiting"] == 1:
                break
            time.sleep(0.01)
        self.assertEqual(g.stats()["waiting"], 1, "waiter ควรอยู่ในคิว")
        with self.assertRaises(admission.Busy):
            with g.slot():     # คิวเต็ม → Busy ทันที
                pass
        release.set()
        th.join(2)
        tw.join(2)

    def test_busy_does_not_leak_waiting_count(self):
        # หลัง Busy (timeout) ตัวนับ waiting ต้องกลับเป็น 0 (ไม่รั่ว)
        g = admission.AdmissionGate(max_concurrent=1, max_wait=0.1)
        acquired = threading.Event()
        release = threading.Event()

        def holder():
            with g.slot():
                acquired.set()
                release.wait(2)

        t = threading.Thread(target=holder, daemon=True)
        t.start()
        self.assertTrue(acquired.wait(2))
        with self.assertRaises(admission.Busy):
            with g.slot():
                pass
        self.assertEqual(g.stats()["waiting"], 0)
        release.set()
        t.join(2)

    def test_stats_waiting_zero_after_all_released(self):
        g = admission.AdmissionGate(max_concurrent=2, max_wait=0.1, max_queue=4)
        for _ in range(3):
            try:
                with g.slot():
                    pass
            except admission.Busy:
                pass
        self.assertEqual(g.stats()["waiting"], 0)


class GateFromConfigTest(unittest.TestCase):
    def test_default_when_unset(self):
        g = admission.gate_from_config(None, config_get=lambda root, k: None)
        self.assertEqual(g.max_concurrent, 1)

    def test_reads_config_value(self):
        g = admission.gate_from_config(None, config_get=lambda root, k: "3")
        self.assertEqual(g.max_concurrent, 3)

    def test_bad_value_falls_back_to_1(self):
        g = admission.gate_from_config(None, config_get=lambda root, k: "abc")
        self.assertEqual(g.max_concurrent, 1)

    def test_zero_or_negative_clamped_to_1(self):
        g = admission.gate_from_config(None, config_get=lambda root, k: "0")
        self.assertEqual(g.max_concurrent, 1)

    def test_negative_clamped_to_1(self):
        g = admission.gate_from_config(None, config_get=lambda root, k: "-5")
        self.assertEqual(g.max_concurrent, 1)

    def test_large_value_accepted(self):
        g = admission.gate_from_config(None, config_get=lambda root, k: "16")
        self.assertEqual(g.max_concurrent, 16)


class AdmissionMetaTest(unittest.TestCase):
    def test_busy_is_exception_subclass(self):
        self.assertTrue(issubclass(admission.Busy, Exception))

    def test_stats_returns_dict(self):
        g = admission.AdmissionGate()
        st = g.stats()
        self.assertIsInstance(st, dict)

    def test_stats_has_required_keys(self):
        g = admission.AdmissionGate()
        st = g.stats()
        for key in ("max_concurrent", "waiting", "max_queue"):
            self.assertIn(key, st, f"stats ต้องมี key: {key}")

    def test_max_concurrent_stored(self):
        g = admission.AdmissionGate(max_concurrent=4)
        self.assertEqual(g.max_concurrent, 4)

    def test_stats_waiting_zero_at_start(self):
        g = admission.AdmissionGate()
        self.assertEqual(g.stats()["waiting"], 0)

    def test_max_queue_stored(self):
        g = admission.AdmissionGate(max_queue=5)
        self.assertEqual(g.stats()["max_queue"], 5)

    def test_slot_context_manager_works(self):
        g = admission.AdmissionGate(max_concurrent=1)
        entered = []
        with g.slot():
            entered.append(True)
        self.assertEqual(entered, [True])


if __name__ == "__main__":
    unittest.main()
