"""test_storage_backend.py — Local + Memory backends, path traversal guard"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage_backend import (  # noqa: E402
    LocalStorageBackend, MemoryStorageBackend, StorageError,
    _safe_key, get_storage,
)


class SafeKeyTest(unittest.TestCase):
    def test_normal_key(self):
        self.assertEqual(_safe_key("data.json"), "data.json")

    def test_nested_key(self):
        self.assertEqual(_safe_key("sub/data.json"), "sub/data.json")

    def test_empty_key_rejected(self):
        with self.assertRaises(StorageError):
            _safe_key("")

    def test_whitespace_key_rejected(self):
        with self.assertRaises(StorageError):
            _safe_key("   ")

    def test_absolute_path_rejected(self):
        with self.assertRaises(StorageError):
            _safe_key("/etc/passwd")

    def test_dotdot_rejected(self):
        with self.assertRaises(StorageError):
            _safe_key("../secret")

    def test_dotdot_in_middle_rejected(self):
        with self.assertRaises(StorageError):
            _safe_key("sub/../../../etc/passwd")


class MemoryStorageTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStorageBackend()

    def test_write_and_read(self):
        self.store.write_text("k1", "hello")
        self.assertEqual(self.store.read_text("k1"), "hello")

    def test_read_nonexistent_returns_none(self):
        self.assertIsNone(self.store.read_text("nope"))

    def test_exists(self):
        self.assertFalse(self.store.exists("k"))
        self.store.write_text("k", "v")
        self.assertTrue(self.store.exists("k"))

    def test_delete(self):
        self.store.write_text("k", "v")
        self.assertTrue(self.store.delete("k"))
        self.assertFalse(self.store.exists("k"))

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(self.store.delete("nope"))

    def test_list_keys(self):
        self.store.write_text("a/1.json", "")
        self.store.write_text("a/2.json", "")
        self.store.write_text("b/3.json", "")
        self.assertEqual(self.store.list_keys("a/"), ["a/1.json", "a/2.json"])

    def test_list_keys_empty(self):
        self.assertEqual(self.store.list_keys(), [])

    def test_overwrite(self):
        self.store.write_text("k", "old")
        self.store.write_text("k", "new")
        self.assertEqual(self.store.read_text("k"), "new")


class LocalStorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = LocalStorageBackend(self.tmp)

    def test_write_and_read(self):
        self.store.write_text("data.json", '{"a":1}')
        self.assertEqual(self.store.read_text("data.json"), '{"a":1}')

    def test_read_nonexistent(self):
        self.assertIsNone(self.store.read_text("nope"))

    def test_exists(self):
        self.assertFalse(self.store.exists("file.txt"))
        self.store.write_text("file.txt", "hi")
        self.assertTrue(self.store.exists("file.txt"))

    def test_delete(self):
        self.store.write_text("del.txt", "bye")
        self.assertTrue(self.store.delete("del.txt"))
        self.assertFalse(self.store.exists("del.txt"))

    def test_delete_nonexistent(self):
        self.assertFalse(self.store.delete("nope"))

    def test_nested_key(self):
        self.store.write_text("sub/deep/file.txt", "deep")
        self.assertEqual(self.store.read_text("sub/deep/file.txt"), "deep")

    def test_list_keys_with_prefix(self):
        self.store.write_text("logs/a.log", "")
        self.store.write_text("logs/b.log", "")
        self.store.write_text("data/c.json", "")
        keys = self.store.list_keys("logs/")
        self.assertEqual(len(keys), 2)
        self.assertTrue(all(k.startswith("logs/") for k in keys))

    def test_path_traversal_rejected(self):
        with self.assertRaises(StorageError):
            self.store.write_text("../escape.txt", "pwned")


class GetStorageTest(unittest.TestCase):
    def test_default_is_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = get_storage(Path(tmp))
            self.assertIsInstance(s, LocalStorageBackend)

    def test_memory_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cfg = {"STORAGE_BACKEND": "memory"}
            (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            s = get_storage(p)
            self.assertIsInstance(s, MemoryStorageBackend)


if __name__ == "__main__":
    unittest.main()
