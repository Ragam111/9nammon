"""test_atomic_write.py — atomic write for config_manager and storage_backend

Checks: write then read back, no leftover temp files, and the original file
survives when os.replace fails midway. Uses temp dirs only.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config_manager  # noqa: E402
from app.storage_backend import LocalStorageBackend, StorageError  # noqa: E402


def _leftover_tmp(directory: Path) -> list:
    """Return every *.tmp file left in ``directory``."""
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


class ConfigAtomicWriteTest(unittest.TestCase):
    def test_write_then_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_manager._write_config(root, {"STORAGE_BACKEND": "local"})
            data = json.loads((root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(data, {"STORAGE_BACKEND": "local"})

    def test_no_tmp_left_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_manager._write_config(root, {"A": "1"})
            config_manager._write_config(root, {"A": "2"})
            self.assertEqual(_leftover_tmp(root), [])

    def test_original_survives_failed_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "config.json"
            target.write_text('{"A": "old"}', encoding="utf-8")
            with mock.patch("os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    config_manager._write_config(root, {"A": "new"})
            self.assertEqual(target.read_text(encoding="utf-8"), '{"A": "old"}')
            self.assertEqual(_leftover_tmp(root), [])


class StorageAtomicWriteTest(unittest.TestCase):
    def test_write_then_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalStorageBackend(Path(tmp))
            backend.write_text("sub/data.json", "ภาษาไทย 123")
            self.assertEqual(backend.read_text("sub/data.json"), "ภาษาไทย 123")

    def test_no_tmp_left_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalStorageBackend(Path(tmp))
            backend.write_text("data.json", "v1")
            backend.write_text("data.json", "v2")
            self.assertEqual(_leftover_tmp(Path(tmp)), [])

    def test_original_survives_failed_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = LocalStorageBackend(root)
            backend.write_text("data.json", "old")
            with mock.patch("os.replace", side_effect=OSError("boom")):
                with self.assertRaises(StorageError):
                    backend.write_text("data.json", "new")
            self.assertEqual(backend.read_text("data.json"), "old")
            self.assertEqual(_leftover_tmp(root), [])


if __name__ == "__main__":
    unittest.main()
