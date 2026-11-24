"""เทสหน้า Admin Dashboard — ฟิลด์ที่ต้องมี และสถานะ up/down/degraded/unknown

ไม่เปิดเซิร์ฟเวอร์. ต้องมี node บน PATH (ชุด node:test ตรวจลอจิกของไคลเอนต์)
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "admin" / "index.html"
CLIENT = ROOT / "web" / "admin" / "admin.js"
SUITE = ROOT / "tests" / "admin_dashboard.test.mjs"

REQUIRED_IDS = (
    "api-base",
    "refresh",
    "service-version",
    "uptime",
    "backend-health",
    "frontend-health",
    "last-updated",
)

REQUIRED_LABELS = (
    "API base",
    "Refresh",
    "Service version",
    "Uptime",
    "Backend health",
    "Frontend health",
    "Last updated",
)


class AdminDashboardPageTest(unittest.TestCase):
    def test_page_includes_required_fields(self):
        html = PAGE.read_text(encoding="utf-8")
        for field_id in REQUIRED_IDS:
            self.assertIn(f'id="{field_id}"', html)
        for label in REQUIRED_LABELS:
            self.assertIn(label, html)
        self.assertIn('value="http://127.0.0.1:8765"', html)
        self.assertIn("./admin.js", html)
        client = CLIENT.read_text(encoding="utf-8")
        self.assertIn("function attachLiveStatus", client)
        self.assertIn("/api/v1/status", client)
        self.assertIn("/api/v1/admin/overview", client)
        self.assertIn('HEALTH_PATH = "/health"', client)
        self.assertNotIn("WebSocket", client)

    def test_client_treats_health_states(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "ต้องมี node เพื่อตรวจแดชบอร์ด")
        syntax = subprocess.run(
            [node, "--check", str(CLIENT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        suite = subprocess.run(
            [node, "--test", str(SUITE)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(
            suite.returncode,
            0,
            suite.stdout + "\n" + suite.stderr,
        )


if __name__ == "__main__":
    unittest.main()
