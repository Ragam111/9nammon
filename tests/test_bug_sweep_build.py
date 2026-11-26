"""Static regression checks for release/build scripts (B8-1, B8-2, B8-3)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import installer_pin  # noqa: E402


class BuildRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.yml = (ROOT / ".github" / "workflows" / "build-exe.yml").read_text(encoding="utf-8")

    def test_b8_1_release_attaches_lcalocalai(self) -> None:
        release = self.yml[self.yml.index("Attach .exe to GitHub Release"):]
        self.assertEqual(release.count("dist/lcalocalai.exe"), 2)

    def test_b8_2_ci_verifies_pin(self) -> None:
        self.assertIn("installer_pin.py sha256", self.yml)
        self.assertIn("merge-base --is-ancestor", self.yml)
        self.assertRegex(installer_pin.read_pin("PINNED_COMMIT"), r"^[0-9a-f]{40}$")
        self.assertRegex(installer_pin.read_pin("ZIP_SHA256"), r"^[0-9a-f]{64}$")

    def test_b8_3_datadir_defaults_to_user_profile(self) -> None:
        ps = (ROOT / "scripts" / "node_setup_server.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn("$DataDir = $env:USERPROFILE", ps)
        self.assertIn("if (-not $DataDir) { $DataDir = Get-UserProfileDir $User }", ps)


if __name__ == "__main__":
    unittest.main()
