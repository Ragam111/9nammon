"""WP-A: scripts/stage_app.py builds the per-edition app/ bundle dir for pyinstaller."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import stage_app  # noqa: E402
from app import edition  # noqa: E402

ADMIN_FILES = ("console.html", "console-keys.html", "console-keys.js", "db-admin.html",
               "dev.html", "admin.html", "admin.js")


class StageAppTest(unittest.TestCase):
    def test_customer_strips_admin_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "app_customer"
            stage_app.stage(ROOT / "app", out, "customer")
            for name in ADMIN_FILES:
                self.assertFalse((out / name).exists(), name)
            self.assertEqual([], stage_app.find_admin_files(out))
            for name in ("chat.html", "models.html", "app.js", "org_store.py", "edition.py"):
                self.assertTrue((out / name).exists(), name)
            self.assertEqual(edition.read_edition_file(out), "customer")
            self.assertFalse(list(out.rglob("__pycache__")))

    def test_admin_keeps_everything(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "app_admin"
            stage_app.stage(ROOT / "app", out, "admin")
            for name in ADMIN_FILES:
                self.assertTrue((out / name).exists(), name)
            self.assertEqual(edition.read_edition_file(out), "admin")
            self.assertEqual((out / "EDITION").read_text(encoding="utf-8").strip(),
                             "EDITION=admin")

    def test_restage_replaces_old_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "app_x"
            stage_app.stage(ROOT / "app", out, "admin")
            stage_app.stage(ROOT / "app", out, "customer")
            self.assertFalse((out / "admin.html").exists())

    def test_rejects_bad_edition_and_unsafe_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                stage_app.stage(ROOT / "app", Path(tmp) / "o", "root")
            with self.assertRaises(ValueError):
                stage_app.stage(ROOT / "app", ROOT / "app", "customer")

    def test_cli_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "app_customer"
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "stage_app.py"),
                                "--edition", "customer", "--out", str(out), "--verify"],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            (out / "dev.html").write_text("x", encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "stage_app.py"),
                                "--check", str(out)], capture_output=True, text=True, timeout=60)
            self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
