"""test_hw_profile.py — เทส "สมอง" จัดระดับเครื่อง + แนะนำ config (ขั้น 1 สู่ HPC)

ฉีด sysinfo + mem_result เข้าไป (ไม่วัดจริง = เร็ว, deterministic) แล้วตรวจว่า:
- จัดระดับถูก: netbook (เป้าหมาย i3/8GB/HDD), workstation, server
- แนะนำ config สมเหตุผล (netbook → cpu/ngl0)
- next_upgrade ชี้ SSD ก่อนเมื่อเป็น HDD (คอขวด data movement)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import hw_profile as hp  # noqa: E402

GB = 1024 ** 3


def _sysinfo(cores, ram_gb, gpus=None):
    return {
        "cpu": {"model": "test-cpu", "physical_cores": cores},
        "memory": {"total": int(ram_gb * GB)},
        "gpus": gpus or [],
    }


class ClassifyTierTest(unittest.TestCase):
    def test_netbook_i3_8gb_hdd(self):
        # เป้าหมายจริง: i3-6006U 2C, 8GB, HDD (เขียน ~80 MB/s)
        t = hp.classify_tier(2, 8 * GB, disk_write_mbps=80.0, has_compute_gpu=False)
        self.assertEqual(t["tier"], "netbook")
        self.assertTrue(t["is_hdd"])

    def test_workstation_needs_ssd(self):
        # 4 core + 16GB + SSD (เขียนเร็ว) = workstation
        t = hp.classify_tier(4, 16 * GB, disk_write_mbps=800.0, has_compute_gpu=False)
        self.assertEqual(t["tier"], "workstation")
        self.assertFalse(t["is_hdd"])

    def test_same_specs_but_hdd_is_not_workstation(self):
        # 4 core + 16GB แต่ HDD → ตกชั้นเป็น netbook (I/O คือคอขวด)
        t = hp.classify_tier(4, 16 * GB, disk_write_mbps=90.0, has_compute_gpu=False)
        self.assertEqual(t["tier"], "netbook")

    def test_server_by_cores(self):
        t = hp.classify_tier(16, 32 * GB, disk_write_mbps=1000.0, has_compute_gpu=False)
        self.assertEqual(t["tier"], "server")

    def test_compute_gpu_makes_server(self):
        # มี compute GPU จริง → server แม้ core/RAM ไม่ถึงเกณฑ์
        t = hp.classify_tier(4, 16 * GB, disk_write_mbps=800.0, has_compute_gpu=True)
        self.assertEqual(t["tier"], "server")

    def test_unknown_disk_not_flagged_hdd(self):
        # ไม่วัด disk (None) → ไม่ฟันธงว่า HDD
        t = hp.classify_tier(2, 8 * GB, disk_write_mbps=None, has_compute_gpu=False)
        self.assertFalse(t["is_hdd"])


class NextUpgradeTest(unittest.TestCase):
    def test_hdd_recommends_ssd_first(self):
        t = hp.classify_tier(2, 8 * GB, disk_write_mbps=80.0, has_compute_gpu=False)
        self.assertIn("SSD", hp.next_upgrade(t, has_compute_gpu=False))

    def test_low_ram_recommends_ram(self):
        # SSD แล้ว แต่ RAM น้อย → แนะนำเพิ่ม RAM
        t = hp.classify_tier(2, 8 * GB, disk_write_mbps=800.0, has_compute_gpu=False)
        self.assertIn("RAM", hp.next_upgrade(t, has_compute_gpu=False))

    def test_no_gpu_recommends_gpu_or_cloud(self):
        t = hp.classify_tier(8, 32 * GB, disk_write_mbps=800.0, has_compute_gpu=False)
        msg = hp.next_upgrade(t, has_compute_gpu=False)
        self.assertTrue("GPU" in msg or "cloud" in msg)


class RecommendConcurrencyTest(unittest.TestCase):
    def _rec(self, cores, ram_gb, disk, gpu=False):
        t = hp.classify_tier(cores, ram_gb * GB, disk, gpu)
        return hp.recommend_config(t)

    def test_netbook_one_concurrent(self):
        rec = self._rec(2, 8, 80.0)                      # i3/8GB/HDD
        self.assertEqual(rec["MAX_CONCURRENT_GENERATIONS"], "1")

    def test_workstation_two_concurrent(self):
        rec = self._rec(4, 16, 800.0)                    # 4C/16GB/SSD
        self.assertEqual(rec["MAX_CONCURRENT_GENERATIONS"], "2")

    def test_server_four_concurrent(self):
        rec = self._rec(16, 64, 1000.0)
        self.assertEqual(rec["MAX_CONCURRENT_GENERATIONS"], "4")

    def test_value_is_string(self):
        # เขียนลง config เป็น string — admission.gate_from_config อ่าน int() เองได้
        rec = self._rec(2, 8, 80.0)
        self.assertIsInstance(rec["MAX_CONCURRENT_GENERATIONS"], str)


class ProfileTest(unittest.TestCase):
    def test_profile_netbook_injected(self):
        with tempfile.TemporaryDirectory() as d:
            p = hp.profile(
                project_root=Path(d),
                sysinfo=_sysinfo(2, 8),
                mem_result={"disk_write_mbps": 80.0, "disk_read_mbps": 90.0,
                            "ram_mbps": 3000.0, "net_loopback_mbps": 1000.0,
                            "bottleneck": "Disk write", "size_mb": 32},
            )
        self.assertEqual(p["tier"], "netbook")
        self.assertTrue(p["is_hdd"])
        self.assertEqual(p["recommended_config"]["COMPUTE_BACKEND"], "cpu")
        self.assertEqual(p["recommended_config"]["COMPUTE_NGL"], "0")
        self.assertIn("SSD", p["next_upgrade"])

    def test_profile_detects_compute_gpu(self):
        gpus = [{"name": "NVIDIA RTX 3060", "compute_capable": True}]
        with tempfile.TemporaryDirectory() as d:
            p = hp.profile(
                project_root=Path(d),
                sysinfo=_sysinfo(8, 32, gpus=gpus),
                mem_result={"disk_write_mbps": 1500.0, "bottleneck": "Network", "size_mb": 32},
            )
        self.assertTrue(p["has_compute_gpu"])
        self.assertEqual(p["tier"], "server")

    def test_report_mentions_tier(self):
        with tempfile.TemporaryDirectory() as d:
            p = hp.profile(
                project_root=Path(d),
                sysinfo=_sysinfo(2, 8),
                mem_result={"disk_write_mbps": 80.0, "bottleneck": "Disk write", "size_mb": 32},
            )
        text = hp.format_report(p)
        self.assertIn("NETBOOK", text)
        self.assertIn("อัปเกรด", text)


if __name__ == "__main__":
    unittest.main()
