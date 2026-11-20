"""
test_dataset_store.py — unittest สำหรับ dataset store (เก็บตัวอย่าง fine-tune, SQLite)
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import dataset_store  # noqa: E402


class DatasetStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_count(self):
        s = dataset_store.add_sample(self.root, "สวัสดี", "ดีจ้า", model="m1", rating=5)
        self.assertEqual(s["prompt"], "สวัสดี")
        self.assertEqual(s["rating"], 5)
        self.assertEqual(dataset_store.count(self.root), 1)

    def test_add_validates(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "", "x")        # prompt ว่าง
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "x", "  ")      # response ว่าง
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "x", "y", rating=9)   # rating เกิน
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "x" * 20001, "y")     # ยาวเกิน

    def test_list_newest_first_and_min_rating(self):
        dataset_store.add_sample(self.root, "a", "1", rating=2)
        dataset_store.add_sample(self.root, "b", "2", rating=4)
        rows = dataset_store.list_samples(self.root)
        self.assertEqual(rows[0]["prompt"], "b")          # ใหม่สุดก่อน
        self.assertEqual(len(dataset_store.list_samples(self.root, min_rating=3)), 1)

    def test_delete(self):
        s = dataset_store.add_sample(self.root, "del", "y")
        self.assertTrue(dataset_store.delete_sample(self.root, s["id"]))
        self.assertFalse(dataset_store.delete_sample(self.root, 99999))
        self.assertEqual(dataset_store.count(self.root), 0)

    def test_export_messages_format(self):
        dataset_store.add_sample(self.root, "hi", "hello")
        out = dataset_store.export_jsonl(self.root, fmt="messages")
        line = json.loads(out.splitlines()[0])
        self.assertIn("messages", line)
        roles = [m["role"] for m in line["messages"]]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_export_alpaca_format_and_order(self):
        dataset_store.add_sample(self.root, "q", "a", rating=5)
        out = dataset_store.export_jsonl(self.root, fmt="alpaca")
        line = json.loads(out.splitlines()[0])
        self.assertIn("instruction", line)
        self.assertIn("output", line)

    def test_export_min_rating_and_bad_fmt(self):
        dataset_store.add_sample(self.root, "q", "a", rating=2)
        dataset_store.add_sample(self.root, "q2", "a2", rating=4)
        out = dataset_store.export_jsonl(self.root, min_rating=3)
        self.assertEqual(len(out.strip().splitlines()), 1)
        with self.assertRaises(ValueError):
            dataset_store.export_jsonl(self.root, fmt="unknown")

    def test_add_returns_dict(self):
        s = dataset_store.add_sample(self.root, "p", "r")
        self.assertIsInstance(s, dict)

    def test_add_has_required_keys(self):
        s = dataset_store.add_sample(self.root, "p", "r")
        for key in ("id", "prompt", "response", "source"):
            self.assertIn(key, s)

    def test_id_is_int(self):
        s = dataset_store.add_sample(self.root, "p", "r")
        self.assertIsInstance(s["id"], int)

    def test_count_returns_int(self):
        self.assertIsInstance(dataset_store.count(self.root), int)
        self.assertEqual(dataset_store.count(self.root), 0)

    def test_list_returns_list(self):
        result = dataset_store.list_samples(self.root)
        self.assertIsInstance(result, list)

    def test_delete_returns_bool(self):
        s = dataset_store.add_sample(self.root, "p", "r")
        result = dataset_store.delete_sample(self.root, s["id"])
        self.assertIsInstance(result, bool)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
