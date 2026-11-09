"""install.ps1 / update.ps1 / release-asset download / scripts/migrate.py.

No network: downloads are mocked. PowerShell parse checks run only when
``pwsh`` is on PATH (CI ubuntu has it; Windows has powershell.exe).
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import installer_gui  # noqa: E402

# uninstall.ps1 was removed on main; installers skip a listed file that is absent.
PS_FILES = ["install.ps1", "update.ps1", "lca-tray.ps1", "scripts/setup-ollama.ps1"]
BEGIN = "# >>> lca-release-download"
END = "# <<< lca-release-download"


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8-sig")


def _shared_block(name: str) -> str:
    text = _read(name)
    start = text.index(BEGIN)
    return text[start:text.index(END, start) + len(END)]


class ScriptLayoutTest(unittest.TestCase):
    def test_download_block_is_identical_in_install_and_update(self):
        self.assertEqual(_shared_block("install.ps1"), _shared_block("update.ps1"))

    def test_download_block_verifies_sha256_from_release(self):
        block = _shared_block("install.ps1")
        self.assertIn("releases/latest/download", block)
        self.assertIn("lca-source.zip.sha256", block)
        self.assertIn("Get-FileHash -Algorithm SHA256", block)

    def test_no_pinned_commit_left(self):
        for name in ("installer_gui.py", "install.ps1", "update.ps1"):
            text = _read(name)
            self.assertNotIn("93f1ca8", text, name)
            self.assertNotIn("PINNED_COMMIT", text, name)

    def test_powershell_scripts_have_utf8_bom(self):
        # Windows PowerShell 5.1 reads a .ps1 without BOM as ANSI, which breaks Thai text
        for name in ["install.ps1", "update.ps1", "scripts/setup-ollama.ps1"]:
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_install_copies_every_program_file_that_exists(self):
        text = _read("install.ps1")
        for name in ("server.py", "local_coder.py", "lca_app.py", "VERSION", "requirements.txt",
                     "update.ps1", "lca-update.bat", "lca-tray.ps1"):
            with self.subTest(name=name):
                self.assertIn(f'"{name}"', text)
                self.assertTrue((ROOT / name).exists())
        self.assertIn('@("app", "sysmanager", "scripts")', text)

    def test_gui_installer_copies_the_same_program_files(self):
        for name in ("lca_app.py", "VERSION", "update.ps1", "lca-update.bat"):
            self.assertIn(name, installer_gui.COPY_FILES)
        self.assertIn("scripts", installer_gui.COPY_DIRS)
        for name in installer_gui.COPY_FILES:
            if name == "uninstall.ps1":
                continue
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).exists(), name)

    def test_install_never_copies_user_data(self):
        text = _read("install.ps1")
        dirs = text[text.index("$ProgramDirs"):text.index("\n", text.index("$ProgramDirs"))]
        self.assertNotIn('"data"', dirs)
        self.assertNotIn("Remove-Item $InstallDir", text + _read("update.ps1"))

    def test_update_runs_migrations_and_restart(self):
        text = _read("update.ps1")
        self.assertIn('"migrate.py"', text)
        self.assertIn("install.ps1\") -Update", text)
        self.assertIn("lca-tray.bat", text)
        self.assertIn("start-lca.bat", text)

    def test_update_bat_is_a_single_line_with_exit(self):
        lines = [ln for ln in (ROOT / "lca-update.bat").read_text(encoding="ascii").splitlines()
                 if ln.strip() and not ln.lower().startswith(("@echo", "rem"))]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].rstrip().endswith("& exit /b"))

    def test_release_assets_script_builds_zip_and_sha256(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import release_assets
        import zipfile
        if not (ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        with tempfile.TemporaryDirectory() as tmp:
            zip_path, sha_path, version = release_assets.build(Path(tmp))
            digest = installer_gui.parse_sha256_file(sha_path.read_text(encoding="ascii"))
            self.assertEqual(digest, hashlib.sha256(zip_path.read_bytes()).hexdigest())
            self.assertTrue(sha_path.read_text(encoding="ascii").endswith("  lca-source.zip\n"))
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
            prefix = f"LocalCodeAssistant-{version}/"
            self.assertIn(prefix + "server.py", names)
            self.assertIn(prefix + "install.ps1", names)
            self.assertFalse(any(n.startswith(prefix + "tests/") for n in names))

    def test_release_upload_refuses_tag_that_does_not_match_version(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import release_assets
        with self.assertRaises(SystemExit):
            release_assets.upload("v9.9.9", "0.2.0", [])

    def test_version_matches_changelog_release(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        first = next(ln for ln in changelog.splitlines() if ln.startswith("## ["))
        self.assertTrue(first.startswith(f"## [{version}]"), first)


@unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
class PowerShellParseTest(unittest.TestCase):
    def test_scripts_parse(self):
        for name in PS_FILES:
            with self.subTest(name=name):
                path = str(ROOT / name)
                cmd = ("$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseFile("
                       f"'{path}',[ref]$t,[ref]$e)|Out-Null; $e.Count")
                out = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd],
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(out.stdout.strip(), "0", out.stdout + out.stderr)


class ReleaseChecksumTest(unittest.TestCase):
    def test_parse_sha256sum_format(self):
        digest = "ab" * 32
        self.assertEqual(installer_gui.parse_sha256_file(f"{digest.upper()}  lca-source.zip\n"), digest)
        self.assertEqual(installer_gui.parse_sha256_file(digest), digest)

    def test_parse_rejects_garbage(self):
        for bad in ("", "not-a-hash  lca-source.zip", "<html>404</html>"):
            with self.subTest(bad=bad):
                with self.assertRaises(installer_gui.ChecksumMismatch):
                    installer_gui.parse_sha256_file(bad)

    def test_urls_point_at_latest_release_assets(self):
        self.assertTrue(installer_gui.ZIP_URL.endswith("/releases/latest/download/lca-source.zip")
                        or "LCA_RELEASE_URL" in __import__("os").environ)
        self.assertEqual(installer_gui.SHA256_URL, installer_gui.ZIP_URL + ".sha256")

    def _serve(self, payload: bytes, sha_text: str):
        class Resp:
            def __init__(self, data):
                self.data, self.pos = data, 0

            def read(self, n=-1):
                if n is None or n < 0:
                    n = len(self.data) - self.pos
                chunk = self.data[self.pos:self.pos + n]
                self.pos += len(chunk)
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(url, timeout=60):
            if url.endswith(".sha256"):
                return Resp(sha_text.encode())
            return Resp(payload)
        return urlopen

    def test_download_uses_release_sidecar_checksum(self):
        payload = b"PK\x03\x04release"
        sha = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "lca-source.zip"
            with mock.patch.object(installer_gui.urllib.request, "urlopen",
                                   self._serve(payload, f"{sha}  lca-source.zip\n")):
                self.assertEqual(installer_gui._download_zip("https://h/x/lca-source.zip", dest), "urllib")
            self.assertEqual(dest.read_bytes(), payload)

    def test_download_rejects_mismatching_release_checksum(self):
        payload = b"PK\x03\x04tampered"
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "lca-source.zip"
            with mock.patch.object(installer_gui.urllib.request, "urlopen",
                                   self._serve(payload, "0" * 64 + "  lca-source.zip\n")):
                with self.assertRaises(installer_gui.ChecksumMismatch):
                    installer_gui._download_zip("https://h/x/lca-source.zip", dest)
            self.assertFalse(dest.exists())


class MigrateScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        sys.path.insert(0, str(ROOT / "scripts"))
        import migrate  # noqa: F401
        self.migrate = sys.modules["migrate"]

    def tearDown(self):
        self.tmp.cleanup()

    def _make_db(self, root: Path) -> Path:
        path = root / "data" / "lca.db"
        path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE keep_me (a TEXT)")
        conn.execute("INSERT INTO keep_me VALUES ('user data')")
        conn.commit()
        conn.close()
        return path

    def test_missing_database_is_not_created(self):
        lines, failures = self.migrate.migrate_roots([self.base / "none"])
        self.assertEqual(failures, 0)
        self.assertIn("skip", lines[0])
        self.assertFalse((self.base / "none" / "data" / "lca.db").exists())

    def test_existing_database_is_migrated_and_keeps_rows(self):
        from app import db
        path = self._make_db(self.base / "root")
        lines, failures = self.migrate.migrate_roots([self.base / "root"])
        self.assertEqual(failures, 0, lines)
        conn = sqlite3.connect(str(path))
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], db.code_version())
            self.assertEqual(conn.execute("SELECT a FROM keep_me").fetchall(), [("user data",)])
        finally:
            conn.close()
        lines, failures = self.migrate.migrate_roots([self.base / "root"])
        self.assertIn("up to date", lines[0])

    def test_failure_sets_exit_code(self):
        self._make_db(self.base / "bad")
        with mock.patch("app.db.ensure_migrated", side_effect=RuntimeError("boom")):
            self.assertEqual(self.migrate.main([str(self.base / "bad")]), 1)

    def test_default_roots_include_desktop_data_dir(self):
        with mock.patch.dict("os.environ", {"LOCALAPPDATA": str(self.base)}):
            roots = self.migrate.default_roots()
        self.assertIn(self.base / "LocalCodeAssistant" / "data", roots)


if __name__ == "__main__":
    unittest.main()
