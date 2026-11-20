"""
test_sha256_verify.py — unittest สำหรับ installer_gui (stdlib เท่านั้น)

Covers:
  ChecksumMismatch         — is RuntimeError, carries message
  _normalize_sha256        — lowercase/uppercase/whitespace/invalid
  default_install_dir()    — LOCALAPPDATA env var present/absent
  _discard()               — removes file, silent on missing
  _find_src_root()         — server.py at root, in subdir, missing raises
  _ensure_start_launcher() — creates bat when absent, keeps existing
  verify_sha256()          — match (keep file), mismatch (delete+raise),
                             invalid hash format, unreadable file
  Module constants         — APP_NAME, COPY_DIRS, COPY_FILES,
                             MIN_FREE_DISK_BYTES, ZIP_SHA256
"""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import installer_gui  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _hex64(data: bytes = b"test") -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants(unittest.TestCase):
    def test_app_name(self):
        self.assertEqual(installer_gui.APP_NAME, "Local Code Assistant")

    def test_copy_dirs_contains_app(self):
        self.assertIn("app", installer_gui.COPY_DIRS)

    def test_copy_files_contains_server_py(self):
        self.assertIn("server.py", installer_gui.COPY_FILES)

    def test_min_free_disk_at_least_100_mb(self):
        self.assertGreaterEqual(installer_gui.MIN_FREE_DISK_BYTES, 100 * 1024 * 1024)

    def test_zip_sha256_is_64_hex_chars(self):
        h = installer_gui.ZIP_SHA256
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))


# ---------------------------------------------------------------------------
# ChecksumMismatch
# ---------------------------------------------------------------------------

class TestChecksumMismatch(unittest.TestCase):
    def test_is_runtime_error(self):
        self.assertIsInstance(installer_gui.ChecksumMismatch("x"), RuntimeError)

    def test_carries_message(self):
        exc = installer_gui.ChecksumMismatch("boom")
        self.assertIn("boom", str(exc))


# ---------------------------------------------------------------------------
# _normalize_sha256
# ---------------------------------------------------------------------------

class TestNormalizeSha256(unittest.TestCase):
    def _norm(self, s):
        return installer_gui._normalize_sha256(s)

    def test_valid_lowercase_accepted(self):
        h = _hex64()
        self.assertEqual(self._norm(h), h)

    def test_valid_uppercase_normalized_to_lower(self):
        h = _hex64()
        self.assertEqual(self._norm(h.upper()), h)

    def test_whitespace_stripped(self):
        h = _hex64()
        self.assertEqual(self._norm("  " + h + " "), h)

    def test_too_short_raises(self):
        with self.assertRaises(installer_gui.ChecksumMismatch):
            self._norm("abc")

    def test_non_hex_char_raises(self):
        h = "z" * 64
        with self.assertRaises(installer_gui.ChecksumMismatch):
            self._norm(h)

    def test_empty_raises(self):
        with self.assertRaises(installer_gui.ChecksumMismatch):
            self._norm("")


# ---------------------------------------------------------------------------
# default_install_dir
# ---------------------------------------------------------------------------

class TestDefaultInstallDir(unittest.TestCase):
    def test_uses_localappdata_when_set(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": "/mock/AppData/Local"}):
            d = installer_gui.default_install_dir()
        self.assertIn("LocalCodeAssistant", d)
        self.assertIn("mock", d)

    def test_falls_back_to_home_when_unset(self):
        env = {k: v for k, v in os.environ.items() if k != "LOCALAPPDATA"}
        with patch.dict(os.environ, env, clear=True):
            d = installer_gui.default_install_dir()
        self.assertIn("LocalCodeAssistant", d)


# ---------------------------------------------------------------------------
# _discard
# ---------------------------------------------------------------------------

class TestDiscard(unittest.TestCase):
    def test_removes_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "junk.bin"
            p.write_bytes(b"data")
            installer_gui._discard(p)
            self.assertFalse(p.exists())

    def test_silent_on_missing_file(self):
        p = Path("/tmp/nonexistent_lca_discard_test_xyz.bin")
        installer_gui._discard(p)  # must not raise


# ---------------------------------------------------------------------------
# _find_src_root
# ---------------------------------------------------------------------------

class TestFindSrcRoot(unittest.TestCase):
    def test_server_py_at_top_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "server.py").write_text("# server")
            self.assertEqual(installer_gui._find_src_root(p), p)

    def test_server_py_in_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            sub = p / "9nammon-abc"
            sub.mkdir()
            (sub / "server.py").write_text("# server")
            self.assertEqual(installer_gui._find_src_root(p), sub)

    def test_raises_when_no_server_py(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                installer_gui._find_src_root(Path(tmp))


# ---------------------------------------------------------------------------
# _ensure_start_launcher
# ---------------------------------------------------------------------------

class TestEnsureStartLauncher(unittest.TestCase):
    def test_creates_bat_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            installer_gui._ensure_start_launcher(p)
            self.assertTrue((p / "start-lca.bat").exists())

    def test_bat_content_has_server_py(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            installer_gui._ensure_start_launcher(p)
            content = (p / "start-lca.bat").read_text(encoding="utf-8")
            self.assertIn("server.py", content)

    def test_no_overwrite_when_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            bat = p / "start-lca.bat"
            bat.write_text("ORIGINAL", encoding="utf-8")
            installer_gui._ensure_start_launcher(p)
            self.assertEqual(bat.read_text(encoding="utf-8"), "ORIGINAL")


# ---------------------------------------------------------------------------
# verify_sha256 (original tests preserved + new edge cases)
# ---------------------------------------------------------------------------

class VerifySha256Test(unittest.TestCase):
    def test_match_returns_digest_and_keeps_file(self):
        payload = b"lca-artifact" * 50
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.bin"
            path.write_bytes(payload)
            got = installer_gui.verify_sha256(path, expected.upper(), chunk_size=16)
            self.assertEqual(got, expected)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), payload)

    def test_mismatch_raises_and_removes_file(self):
        payload = b"good-bytes"
        actual = hashlib.sha256(payload).hexdigest()
        wrong = hashlib.sha256(b"other-bytes").hexdigest()
        self.assertNotEqual(actual, wrong)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial.bin"
            path.write_bytes(payload)
            with self.assertRaises(installer_gui.ChecksumMismatch) as cm:
                installer_gui.verify_sha256(path, wrong)
            self.assertFalse(path.exists())
            message = str(cm.exception)
            self.assertIn(wrong, message)
            self.assertIn(actual, message)
            self.assertIn("ลบไฟล์", message)

    def test_invalid_sha256_format_raises_without_touching_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.bin"
            path.write_bytes(b"data")
            with self.assertRaises(installer_gui.ChecksumMismatch):
                installer_gui.verify_sha256(path, "not-a-hash")
            self.assertTrue(path.exists())

    def test_missing_file_raises_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gone.bin"
            with self.assertRaises(installer_gui.ChecksumMismatch):
                installer_gui.verify_sha256(path, _hex64())


if __name__ == "__main__":
    unittest.main()
