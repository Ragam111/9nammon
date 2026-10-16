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
        dataset_store.add_sample(self.root, "b", "2", rating=5)
        rows = dataset_store.list_samples(self.root)
        self.assertEqual(rows[0]["prompt"], "b")  # ใหม่สุดก่อน
        self.assertEqual(len(dataset_store.list_samples(self.root, min_rating=4)), 1)

    def test_delete(self):
        s = dataset_store.add_sample(self.root, "a", "1")
        self.assertTrue(dataset_store.delete_sample(self.root, s["id"]))
        self.assertFalse(dataset_store.delete_sample(self.root, s["id"]))
        self.assertEqual(dataset_store.count(self.root), 0)

    def test_export_messages_format(self):
        dataset_store.add_sample(self.root, "เขียน for loop", "for i in range(10): ...")
        out = dataset_store.export_jsonl(self.root, fmt="messages")
        obj = json.loads(out.splitlines()[0])
        self.assertEqual(obj["messages"][0]["role"], "user")
        self.assertEqual(obj["messages"][0]["content"], "เขียน for loop")
        self.assertEqual(obj["messages"][1]["role"], "assistant")

    def test_export_alpaca_format_and_order(self):
        dataset_store.add_sample(self.root, "first", "o1")
        dataset_store.add_sample(self.root, "second", "o2")
        lines = dataset_store.export_jsonl(self.root, fmt="alpaca").splitlines()
        self.assertEqual(json.loads(lines[0])["instruction"], "first")  # export เรียงเก่า→ใหม่
        self.assertEqual(json.loads(lines[1])["output"], "o2")

    def test_export_min_rating_and_bad_fmt(self):
        dataset_store.add_sample(self.root, "a", "1", rating=2)
        dataset_store.add_sample(self.root, "b", "2", rating=5)
        self.assertEqual(len(dataset_store.export_jsonl(self.root, min_rating=4).splitlines()), 1)
        with self.assertRaises(ValueError):
            dataset_store.export_jsonl(self.root, fmt="bogus")


if __name__ == "__main__":
    unittest.main()
