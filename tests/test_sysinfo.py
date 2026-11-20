"""
test_sysinfo.py — unittest สำหรับ system basics (stdlib เท่านั้น)

ทดสอบ logic ที่ deterministic (จำแนก compute GPU, format) + ยืนยันว่า
get_system_info()/detect_gpus() รันได้จริงบนเครื่องทดสอบโดยไม่ crash

Covers:
  GpuClassifyTest    — discrete compute capable, integrated not capable, unknown default
  HumanBytesTest     — 0 B, KiB, GiB scales
  DetectGpusTest     — never raises, returns list, run swallows missing command
  SystemInfoTest     — shape, cpu >= 1 core, memory > 0, gpu_note truthy,
                       to_dict has cpu/gpus, gpu_note no GPU
  SysinfoMetaTest    — SystemInfo is dataclass-like, CpuInfo has fields, MemoryInfo has fields,
                       GpuInfo has name+compute_capable, to_dict returns dict,
                       human_bytes MiB scale, human_bytes TiB scale, _run returns str
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

    def test_nvidia_quadro_compute_capable(self):
        self.assertTrue(sysinfo._guess_compute_capable("NVIDIA Quadro RTX 5000"))

    def test_empty_string_not_capable(self):
        self.assertFalse(sysinfo._guess_compute_capable(""))

    def test_classify_returns_bool(self):
        result = sysinfo._guess_compute_capable("NVIDIA GTX 1080")
        self.assertIsInstance(result, bool)


class HumanBytesTest(unittest.TestCase):
    def test_scales(self):
        self.assertEqual(sysinfo._human_bytes(0), "0.0 B")
        self.assertEqual(sysinfo._human_bytes(1024), "1.0 KiB")
        self.assertEqual(sysinfo._human_bytes(8 * 1024 ** 3), "8.0 GiB")

    def test_mib_scale(self):
        result = sysinfo._human_bytes(1024 ** 2)
        self.assertIn("MiB", result)

    def test_tib_scale(self):
        result = sysinfo._human_bytes(1024 ** 4)
        self.assertIn("TiB", result)

    def test_returns_string(self):
        result = sysinfo._human_bytes(512)
        self.assertIsInstance(result, str)


class DetectGpusTest(unittest.TestCase):
    def test_detect_gpus_never_raises_and_returns_list(self):
        result = sysinfo.detect_gpus()
        self.assertIsInstance(result, list)

    def test_run_swallows_missing_command(self):
        # คำสั่งที่ไม่มีจริง ต้องคืนสตริงว่าง ไม่ throw
        self.assertEqual(sysinfo._run(["definitely-not-a-real-command-xyz"]), "")

    def test_run_returns_string(self):
        result = sysinfo._run(["echo", "hello"])
        self.assertIsInstance(result, str)

    def test_detect_gpus_items_are_gpu_info(self):
        gpus = sysinfo.detect_gpus()
        for g in gpus:
            self.assertIsInstance(g.name, str)
            self.assertIsInstance(g.compute_capable, bool)


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

    def test_cpu_info_has_required_fields(self):
        info = get_system_info()
        self.assertIsNotNone(info.cpu.logical_cores)
        self.assertIsNotNone(info.cpu.arch)
        self.assertIsNotNone(info.cpu.model)

    def test_memory_info_human_non_empty(self):
        info = get_system_info()
        self.assertIsInstance(info.memory.total_human, str)
        self.assertGreater(len(info.memory.total_human), 0)

    def test_to_dict_has_memory(self):
        info = get_system_info()
        d = info.to_dict()
        self.assertIn("memory", d)
        self.assertIn("total", d["memory"])

    def test_hostname_is_string(self):
        info = get_system_info()
        self.assertIsInstance(info.hostname, str)
        self.assertGreater(len(info.hostname), 0)


class SysinfoMetaTest(unittest.TestCase):
    def test_system_info_has_to_dict(self):
        info = get_system_info()
        self.assertTrue(hasattr(info, "to_dict"))
        self.assertTrue(callable(info.to_dict))

    def test_to_dict_returns_dict(self):
        info = get_system_info()
        d = info.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_has_expected_keys(self):
        info = get_system_info()
        d = info.to_dict()
        for key in ("cpu", "memory", "gpus", "hostname", "platform"):
            self.assertIn(key, d, f"to_dict ต้องมี key: {key}")


if __name__ == "__main__":
    unittest.main()
