"""test_folder_trust.py — trust marker create/check"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import folder_trust  # noqa: E402


class IsTrustedTest(unittest.TestCase):
    def test_untrusted_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(folder_trust.is_trusted(Path(tmp)))

    def test_trusted_after_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.mark_trusted(p)
            self.assertTrue(folder_trust.is_trusted(p))

    def test_marker_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.mark_trusted(p)
            self.assertTrue((p / ".lca_trust").exists())

    def test_marker_has_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.mark_trusted(p)
            content = (p / ".lca_trust").read_text(encoding="utf-8")
            self.assertIn("trusted_at", content)


class EnsureTrustedTest(unittest.TestCase):
    @patch("builtins.input", return_value="y")
    def test_ensure_trusted_yes(self, _mock):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            result = folder_trust.ensure_trusted(p)
            self.assertTrue(result)
            self.assertTrue(folder_trust.is_trusted(p))

    @patch("builtins.input", return_value="n")
    def test_ensure_trusted_no(self, _mock):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            result = folder_trust.ensure_trusted(p)
            self.assertFalse(result)
            self.assertFalse(folder_trust.is_trusted(p))

    def test_already_trusted_skips_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.mark_trusted(p)
            result = folder_trust.ensure_trusted(p)
            self.assertTrue(result)


class FolderTrustExtraTest(unittest.TestCase):
    def test_trust_marker_name_constant(self):
        self.assertTrue(hasattr(folder_trust, "TRUST_MARKER_NAME"))
        self.assertIsInstance(folder_trust.TRUST_MARKER_NAME, str)

    def test_is_trusted_returns_bool(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = folder_trust.is_trusted(Path(tmp))
            self.assertIsInstance(result, bool)

    def test_mark_twice_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.mark_trusted(p)
            folder_trust.mark_trusted(p)
            self.assertTrue(folder_trust.is_trusted(p))

    def test_different_dirs_independent(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            p1, p2 = Path(t1), Path(t2)
            folder_trust.mark_trusted(p1)
            self.assertTrue(folder_trust.is_trusted(p1))
            self.assertFalse(folder_trust.is_trusted(p2))

    def test_marker_contains_trusted_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.mark_trusted(p)
            content = (p / folder_trust.TRUST_MARKER_NAME).read_text(encoding="utf-8")
            self.assertIn("trusted_at", content)

    def test_untrusted_dir_reports_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(folder_trust.is_trusted(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
