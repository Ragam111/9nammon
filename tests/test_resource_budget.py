"""
test_resource_budget.py — unittest สำหรับ resource_budget (เลือกโมเดล/backend ตาม RAM)

mock available_ram() เพื่อทดสอบการตัดสินใจแบบ deterministic ไม่พึ่ง RAM จริงของ runner
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import resource_budget as rb  # noqa: E402
from app import config_manager  # noqa: E402

GB = rb.GB


class PickModelTest(unittest.TestCase):
    def test_low_ram_picks_smallest(self):
        # RAM ว่าง 1GB -> ใส่ไม่ได้แม้ 0.5b (0.6+1.5 headroom) -> เล็กสุด fits=False
        r = rb.pick_model(avail=1 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:0.5b")
        self.assertFalse(r["fits"])

    def test_mid_ram_picks_0_5b(self):
        # 2.3GB: 0.5b (0.6+1.5=2.1) ใส่ได้, 1.5b (1.2+1.5=2.7) ไม่ได้
        r = rb.pick_model(avail=int(2.3 * GB))
        self.assertEqual(r["model"], "qwen2.5-coder:0.5b")
        self.assertTrue(r["fits"])

    def test_more_ram_picks_1_5b(self):
        # 3GB: 1.5b (2.7) ใส่ได้, 7b (6.5) ไม่ได้ -> เลือก 1.5b (ใหญ่สุดที่ไหว)
        r = rb.pick_model(avail=3 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:1.5b")
        self.assertTrue(r["fits"])

    def test_high_ram_picks_7b(self):
        r = rb.pick_model(avail=8 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:7b")
        self.assertTrue(r["fits"])

    def test_unknown_ram_picks_smallest_safe(self):
        r = rb.pick_model(avail=0)
        self.assertEqual(r["model"], "qwen2.5-coder:0.5b")
        self.assertTrue(r["fits"])  # best-effort ปลอดภัย

    def test_preferred_honored_when_fits(self):
        r = rb.pick_model(preferred="qwen2.5-coder:1.5b", avail=4 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:1.5b")

    def test_preferred_ignored_when_too_big(self):
        # ขอ 7b แต่ RAM 3GB ไม่พอ -> ถอยไป 1.5b
        r = rb.pick_model(preferred="qwen2.5-coder:7b", avail=3 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:1.5b")

    def test_fits_helper(self):
        self.assertTrue(rb.fits("qwen2.5-coder:0.5b", int(2.2 * GB)))
        self.assertFalse(rb.fits("qwen2.5-coder:7b", int(2.2 * GB)))
        self.assertFalse(rb.fits("unknown-model", 99 * GB))


class PickBackendTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_is_cpu(self):
        b = rb.pick_backend(self.root)
        self.assertEqual(b["backend"], "cpu")
        self.assertEqual(b["ngl"], "0")
        self.assertEqual(b["source"], "default")

    def test_reads_measured_from_config(self):
        config_manager.set_key(self.root, "COMPUTE_BACKEND", "vulkan")
        config_manager.set_key(self.root, "COMPUTE_DEVICE", "1")
        config_manager.set_key(self.root, "COMPUTE_NGL", "15")
        b = rb.pick_backend(self.root)
        self.assertEqual(b["backend"], "vulkan")
        self.assertEqual(b["device"], "1")
        self.assertEqual(b["ngl"], "15")
        self.assertEqual(b["source"], "measured")


class BudgetReportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_report_shape(self):
        rep = rb.budget_report(self.root)
        self.assertIn("available_ram", rep)
        self.assertIn("recommended_model", rep)
        self.assertIn("backend", rep)
        self.assertEqual(len(rep["models"]), 3)
        for m in rep["models"]:
            self.assertIn("fits", m)
            self.assertIn("footprint", m)


if __name__ == "__main__":
    unittest.main()
