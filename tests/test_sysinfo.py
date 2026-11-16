"""
test_sysinfo.py — unittest สำหรับ system basics (stdlib เท่านั้น)

ทดสอบ logic ที่ deterministic (จำแนก compute GPU, format) + ยืนยันว่า
get_system_info()/detect_gpus() รันได้จริงบนเครื่องทดสอบโดยไม่ crash
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sysmanager import sysinfo  # noqa: E402
from sysmanager.sysinfo import SystemInfo, get_system_info  # noqa: E402


class GpuClassifyTest(unittest.TestCase):
    def test_discrete_gpus_are_compute_capable(self):
        for name in ["NVIDIA GeForce RTX 4090", "NVIDIA A100", "AMD Radeon RX 7900 XTX",
                     "AMD Instinct MI300X", "Tesla V100"]:
            self.assertTrue(sysinfo._guess_compute_capable(name), name)

    def test_integrated_gpus_not_compute_capable(self):
        for name in ["Intel HD Graphics 520", "Intel UHD Graphics 620",
                     "Intel Iris Xe", "AMD Radeon Graphics"]:
            self.assertFalse(sysinfo._guess_compute_capable(name), name)

    def test_unknown_defaults_to_not_capable(self):
        self.assertFalse(sysinfo._guess_compute_capable("Some Mystery Display 9000"))


class HumanBytesTest(unittest.TestCase):
    def test_scales(self):
        self.assertEqual(sysinfo._human_bytes(0), "0.0 B")
        self.assertEqual(sysinfo._human_bytes(1024), "1.0 KiB")
        self.assertEqual(sysinfo._human_bytes(8 * 1024 ** 3), "8.0 GiB")


class DetectGpusTest(unittest.TestCase):
    def test_detect_gpus_never_raises_and_returns_list(self):
        result = sysinfo.detect_gpus()
        self.assertIsInstance(result, list)

    def test_run_swallows_missing_command(self):
        # คำสั่งที่ไม่มีจริง ต้องคืนสตริงว่าง ไม่ throw
        self.assertEqual(sysinfo._run(["definitely-not-a-real-command-xyz"]), "")


class SystemInfoTest(unittest.TestCase):
    def test_get_system_info_shape(self):
        info = get_system_info()
        self.assertIsInstance(info, SystemInfo)
        self.assertGreaterEqual(info.cpu.logical_cores, 1)
        self.assertGreater(info.memory.total, 0)
        self.assertTrue(info.gpu_note)  # ต้องมีหมายเหตุเสมอ
        # serialisable
        d = info.to_dict()
        self.assertIn("cpu", d)
        self.assertIn("gpus", d)

    def test_gpu_note_reflects_detection(self):
        # ไม่มี GPU -> note บอกว่า best-effort / ไม่พบ
        info = get_system_info()
        if not info.gpus:
            self.assertIn("best-effort", info.gpu_note)


if __name__ == "__main__":
    unittest.main()
