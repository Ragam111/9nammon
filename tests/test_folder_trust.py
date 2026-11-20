"""test_folder_trust.py — trust marker create/check

Covers:
  IsTrustedTest         — untrusted by default, trusted after mark, marker file exists,
                          marker has timestamp
  EnsureTrustedTest     — yes prompt, no prompt, already trusted skips prompt
  FolderTrustMetaTest   — is_trusted returns bool, mark_trusted idempotent,
                          marker content is text, trusted_at in content, lca_trust filename,
                          ensure_trusted yes uppercase Y (only 'y' accepted per source)
"""

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


class FolderTrustMetaTest(unittest.TestCase):
    def test_is_trusted_returns_bool(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = folder_trust.is_trusted(Path(tmp))
            self.assertIsInstance(result, bool)

    def test_mark_trusted_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.mark_trusted(p)
            folder_trust.mark_trusted(p)
            self.assertTrue(folder_trust.is_trusted(p))

    def test_marker_content_is_valid_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.mark_trusted(p)
            content = (p / ".lca_trust").read_text(encoding="utf-8")
            self.assertIsInstance(content, str)
            self.assertGreater(len(content), 0)

    def test_ensure_trusted_returns_bool(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.mark_trusted(p)
            result = folder_trust.ensure_trusted(p)
            self.assertIsInstance(result, bool)

    @patch("builtins.input", return_value="n")
    def test_ensure_trusted_no_does_not_create_marker(self, _mock):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            folder_trust.ensure_trusted(p)
            self.assertFalse((p / ".lca_trust").exists())

    @patch("builtins.input", side_effect=EOFError)
    def test_ensure_trusted_eof_returns_false(self, _mock):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            result = folder_trust.ensure_trusted(p)
            self.assertFalse(result)

    @patch("builtins.input", return_value="Y")
    def test_ensure_trusted_uppercase_Y_accepted(self, _mock):
        # source ทำ .strip().lower() ก่อนเทียบ → Y ถูกยอมรับเหมือน y
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            result = folder_trust.ensure_trusted(p)
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
