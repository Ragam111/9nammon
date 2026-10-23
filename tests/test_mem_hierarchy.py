"""test_mem_hierarchy.py — เทสเครื่องมือวัดการเดินทางของข้อมูลข้ามชั้นหน่วยความจำ

วัดของจริง (RAM/disk/network loopback) ด้วยขนาดเล็กให้เร็ว — ยืนยันว่า:
- คืนค่าเป็นบวก (วัดติดจริง)
- disk เขียนไฟล์ชั่วคราวแล้ว "ลบทิ้งเสมอ" (ไม่ทิ้งขยะ)
- measure_all คืนคีย์ครบ + ชี้คอขวดได้
- format_report แสดงคอขวด
ไม่ผูกกับสเปกเครื่อง (ไม่ assert ตัวเลขตายตัว — เครื่องต่างกันเลขต่างกัน)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import mem_hierarchy as mh  # noqa: E402


class HelperTest(unittest.TestCase):
    def test_mbps_normal(self):
        self.assertAlmostEqual(mh._mbps(mh.MB, 1.0), 1.0, places=3)

    def test_mbps_zero_seconds_no_divzero(self):
        # เร็วจนวัดไม่ติด (seconds<=0) ต้องคืน 0.0 ไม่ระเบิด
        self.assertEqual(mh._mbps(mh.MB, 0.0), 0.0)
        self.assertEqual(mh._mbps(mh.MB, -1.0), 0.0)


class RamBenchTest(unittest.TestCase):
    def test_returns_positive(self):
        self.assertGreater(mh.bench_ram(size_mb=4, repeat=2), 0.0)


class DiskBenchTest(unittest.TestCase):
    def test_write_read_positive(self):
        with tempfile.TemporaryDirectory() as d:
            r = mh.bench_disk(d, size_mb=4)
        self.assertGreater(r["write_mbps"], 0.0)
        self.assertGreater(r["read_mbps"], 0.0)

    def test_cleans_up_temp_file(self):
        with tempfile.TemporaryDirectory() as d:
            mh.bench_disk(d, size_mb=4)
            # ไฟล์ .memh_*.tmp ต้องถูกลบหมด ไม่ค้าง
            leftovers = list(Path(d).glob(".memh_*.tmp"))
        self.assertEqual(leftovers, [])

    def test_creates_missing_dir(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "new" / "nested"
            r = mh.bench_disk(sub, size_mb=2)      # dir ยังไม่มี → ต้องสร้างให้
        self.assertGreater(r["write_mbps"], 0.0)


class NetworkBenchTest(unittest.TestCase):
    def test_loopback_positive(self):
        self.assertGreater(mh.bench_network_loopback(size_mb=4), 0.0)


class MeasureAllTest(unittest.TestCase):
    def test_keys_and_bottleneck(self):
        with tempfile.TemporaryDirectory() as d:
            r = mh.measure_all(target_dir=d, size_mb=4)
        for k in ("ram_mbps", "disk_write_mbps", "disk_read_mbps",
                  "net_loopback_mbps", "bottleneck", "size_mb"):
            self.assertIn(k, r)
        # คอขวดต้องเป็นหนึ่งในชั้นที่วัด (ไม่ใช่ None เพราะทุกชั้นวัดติด)
        self.assertIn(r["bottleneck"],
                      ("RAM (copy)", "Disk write", "Disk read", "Network (loopback)"))

    def test_report_mentions_bottleneck(self):
        with tempfile.TemporaryDirectory() as d:
            r = mh.measure_all(target_dir=d, size_mb=4)
        text = mh.format_report(r)
        self.assertIn("คอขวด", text)
        self.assertIn(r["bottleneck"], text)


if __name__ == "__main__":
    unittest.main()
