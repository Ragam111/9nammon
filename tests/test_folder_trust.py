"""test_folder_trust.py — trust marker create/check"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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

    @patch("builtins.input", side_effect=EOFError)
    def test_eof_on_prompt_exits_nonzero_with_message(self, _mock):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            with patch("sys.stderr") as err:
                with self.assertRaises(SystemExit) as cm:
                    folder_trust.ensure_trusted(p)
            self.assertEqual(cm.exception.code, 1)
            written = "".join(c.args[0] for c in err.write.call_args_list)
            self.assertIn("stdin", written)
            self.assertFalse(folder_trust.is_trusted(p))

    def test_empty_stdin_subprocess_exits_nonzero_with_message(self):
        """จริงกว่า mock: รันในโปรเซสลูกที่ stdin ว่าง (EOF ทันที) แล้วตรวจ rc และ stderr"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            code = (
                "import sys\n"
                f"sys.path.insert(0, {str(ROOT)!r})\n"
                "from pathlib import Path\n"
                "from app import folder_trust\n"
                f"folder_trust.ensure_trusted(Path({str(p)!r}))\n"
                "print('CONTINUED')\n"
            )
            env = dict(os.environ, PYTHONUTF8="1")
            proc = subprocess.run(
                [sys.executable, "-c", code],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=60,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("stdin", proc.stderr)
            self.assertNotIn("CONTINUED", proc.stdout)
            self.assertFalse(folder_trust.is_trusted(p))


if __name__ == "__main__":
    unittest.main()
