"""test_admission.py — เทสยามคุม generation พร้อมกัน (admission control)

ใช้ threading จริง + event sync ให้ deterministic (ไม่พึ่ง sleep เดา):
- รันตามลำดับได้ปกติ (ไม่บล็อกตัวเอง)
- เครื่องเต็ม + รอเกิน max_wait → Busy (timeout)
- คิวเต็ม (waiting >= max_queue) → Busy ทันที
- gate_from_config: อ่าน config, ค่าพัง/ไม่ตั้ง → default 1
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


if __name__ == "__main__":
    unittest.main()
