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
        # RAM ว่าง 1GB -> ใส่ไม่ได้แม้ 0.5b (0.6+1.2 headroom=1.8) -> เล็กสุด fits=False
        r = rb.pick_model(avail=1 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:0.5b")
        self.assertFalse(r["fits"])

    def test_low_mid_ram_picks_0_5b(self):
        # 2.0GB: 0.5b (0.6+1.2=1.8) ใส่ได้, 1.5b (1.0+1.2=2.2) ไม่ได้ -> 0.5b
        r = rb.pick_model(avail=2 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:0.5b")
        self.assertTrue(r["fits"])

    def test_netbook_ram_picks_1_5b(self):
        # 2.6GB (เครื่อง netbook จริง): 1.5b (1.0+1.2=2.2) ใส่ได้แล้ว หลังจูน footprint
        # ตามของจริง — เดิม (1.2+1.5=2.7) จะตก 0.5b ทั้งที่วัดแล้ว 1.5b รันไหว
        r = rb.pick_model(avail=int(2.6 * GB))
        self.assertEqual(r["model"], "qwen2.5-coder:1.5b")
        self.assertTrue(r["fits"])

    def test_more_ram_picks_1_5b(self):
        # 3GB: 1.5b (2.2) ใส่ได้, 7b (6.2) ไม่ได้ -> เลือก 1.5b (ใหญ่สุดที่ไหว)
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

    def test_quality_floor_prefers_1_5b_over_7b(self):
        # "พื้นเชิงคุณภาพ": มี project_root + RAM เยอะ -> เล็ง 1.5b (ตัวที่แก้โค้ดได้จริง)
        # ไม่กระโดดไป 7b แม้ใส่ได้ (1.5b คือ sweet spot ของ LCA)
        with tempfile.TemporaryDirectory() as tmp:
            r = rb.pick_model(project_root=Path(tmp), avail=8 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:1.5b")

    def test_quality_floor_falls_back_to_0_5b_under_pressure(self):
        # RAM ตึง (2.0GB): 1.5b ไม่ไหว -> ถอยไป 0.5b เอง (floor ไม่ฝืน)
        with tempfile.TemporaryDirectory() as tmp:
            r = rb.pick_model(project_root=Path(tmp), avail=2 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:0.5b")

    def test_config_can_override_preferred_floor(self):
        # ตั้ง PREFERRED_MODEL=0.5b ผ่าน config -> เคารพตามนั้น (ไม่ hardcode 1.5b)
        with tempfile.TemporaryDirectory() as tmp:
            config_manager.set_key(Path(tmp), "PREFERRED_MODEL", "qwen2.5-coder:0.5b")
            r = rb.pick_model(project_root=Path(tmp), avail=8 * GB)
        self.assertEqual(r["model"], "qwen2.5-coder:0.5b")

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
