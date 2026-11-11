"""เทสบาง ๆ ของ local_dashboard — ไวยากรณ์ JS และชุด node:test

ไม่เปิดเซิร์ฟเวอร์. ต้องมี node บน PATH (CI ของ GitHub มีอยู่แล้ว)
"""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DashboardFrontendTest(unittest.TestCase):
    def test_js_syntax_and_unit_suite(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "ต้องมี node เพื่อตรวจแดชบอร์ด")
        scripts = list((ROOT / "local_dashboard").rglob("*.js"))
        self.assertGreaterEqual(len(scripts), 8)
        for script in scripts:
            proc = subprocess.run(
                [node, "--check", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, f"{script}\n{proc.stderr}")
        suite = subprocess.run(
            [node, "--test", str(ROOT / "tests" / "dashboard_frontend.test.mjs")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            suite.returncode,
            0,
            suite.stdout + "\n" + suite.stderr,
        )

    def test_version_file_unchanged(self):
        # VERSION ต้องยังเป็น SemVer บรรทัดเดียว (dashboard ไม่แก้ไฟล์นี้) — ไม่ pin เลขเวอร์ชัน
        # เพราะ release PR อื่น bump ได้ตามปกติ
        import re
        value = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(value, r"^\d+\.\d+\.\d+$")
