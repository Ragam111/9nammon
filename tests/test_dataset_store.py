"""
test_dataset_store.py — unittest สำหรับ dataset store (เก็บตัวอย่าง fine-tune, SQLite)

Covers:
  Module constants    — DATASET_DB_NAME, VALID_FORMATS, _MAX_LEN
  add_sample()        — validation (empty, too-long, bad rating, rating range),
                        return shape (all 7 fields, None model/source, rating coerce)
  list_samples()      — empty [], newest-first, min_rating, limit
  count()             — empty 0, after inserts, after delete
  delete_sample()     — returns True/False, count decrements
  export_jsonl()      — empty "", messages/alpaca structure, ASC order,
                        min_rating filter, bad fmt raises, case-insensitive fmt
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import dataset_store  # noqa: E402


class _TmpRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _add(self, prompt="hello", response="world", **kwargs):
        return dataset_store.add_sample(self.root, prompt, response, **kwargs)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants(unittest.TestCase):
    def test_dataset_db_name_is_string(self):
        self.assertIsInstance(dataset_store.DATASET_DB_NAME, str)

    def test_dataset_db_name_ends_with_db(self):
        self.assertTrue(dataset_store.DATASET_DB_NAME.endswith(".db"))

    def test_valid_formats_contains_messages(self):
        self.assertIn("messages", dataset_store.VALID_FORMATS)

    def test_valid_formats_contains_alpaca(self):
        self.assertIn("alpaca", dataset_store.VALID_FORMATS)

    def test_max_len_positive(self):
        self.assertGreater(dataset_store._MAX_LEN, 0)


# ---------------------------------------------------------------------------
# add_sample — validation
# ---------------------------------------------------------------------------

class TestAddSampleValidation(_TmpRoot):
    def test_empty_prompt_raises(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "", "resp")

    def test_whitespace_prompt_raises(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "   ", "resp")

    def test_empty_response_raises(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "prompt", "")

    def test_whitespace_response_raises(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "prompt", "  ")

    def test_prompt_at_max_len_ok(self):
        s = dataset_store.add_sample(self.root, "x" * dataset_store._MAX_LEN, "resp")
        self.assertEqual(len(s["prompt"]), dataset_store._MAX_LEN)

    def test_prompt_over_max_len_raises(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "x" * (dataset_store._MAX_LEN + 1), "resp")

    def test_response_over_max_len_raises(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "prompt", "y" * (dataset_store._MAX_LEN + 1))

    def test_bad_rating_string_raises(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "p", "r", rating="bad")

    def test_rating_zero_raises(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "p", "r", rating=0)

    def test_rating_six_raises(self):
        with self.assertRaises(ValueError):
            dataset_store.add_sample(self.root, "p", "r", rating=6)


# ---------------------------------------------------------------------------
# add_sample — return shape
# ---------------------------------------------------------------------------

class TestAddSampleShape(_TmpRoot):
    def test_returns_dict(self):
        self.assertIsInstance(self._add(), dict)

    def test_has_all_expected_fields(self):
        s = self._add()
        for field in ("id", "created_at", "model", "prompt", "response", "rating", "source"):
            self.assertIn(field, s)

    def test_default_source_is_manual(self):
        s = self._add()
        self.assertEqual(s["source"], "manual")

    def test_empty_model_stored_as_none(self):
        s = dataset_store.add_sample(self.root, "p", "r", model="")
        self.assertIsNone(s["model"])

    def test_none_model_stored_as_none(self):
        s = dataset_store.add_sample(self.root, "p", "r", model=None)
        self.assertIsNone(s["model"])

    def test_model_stored_when_given(self):
        s = dataset_store.add_sample(self.root, "p", "r", model="gpt4")
        self.assertEqual(s["model"], "gpt4")

    def test_none_rating_stored_as_none(self):
        s = dataset_store.add_sample(self.root, "p", "r", rating=None)
        self.assertIsNone(s["rating"])

    def test_rating_string_coerced_to_int(self):
        s = dataset_store.add_sample(self.root, "p", "r", rating="3")
        self.assertEqual(s["rating"], 3)

    def test_custom_source_stored(self):
        s = dataset_store.add_sample(self.root, "p", "r", source="chatlog")
        self.assertEqual(s["source"], "chatlog")

    def test_empty_source_stored_as_none(self):
        s = dataset_store.add_sample(self.root, "p", "r", source="")
        self.assertIsNone(s["source"])


# ---------------------------------------------------------------------------
# list_samples
# ---------------------------------------------------------------------------

class TestListSamples(_TmpRoot):
    def test_empty_db_returns_empty_list(self):
        self.assertEqual(dataset_store.list_samples(self.root), [])

    def test_newest_first_ordering(self):
        self._add(prompt="first")
        self._add(prompt="second")
        rows = dataset_store.list_samples(self.root)
        self.assertEqual(rows[0]["prompt"], "second")

    def test_min_rating_filter(self):
        self._add(rating=2)
        self._add(rating=5)
        rows = dataset_store.list_samples(self.root, min_rating=4)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rating"], 5)

    def test_min_rating_no_match_returns_empty(self):
        self._add(rating=2)
        self.assertEqual(dataset_store.list_samples(self.root, min_rating=5), [])

    def test_limit_parameter(self):
        for i in range(5):
            self._add(prompt=f"p{i}")
        rows = dataset_store.list_samples(self.root, limit=3)
        self.assertEqual(len(rows), 3)


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------

class TestCount(_TmpRoot):
    def test_empty_db_returns_zero(self):
        self.assertEqual(dataset_store.count(self.root), 0)

    def test_count_after_adds(self):
        self._add()
        self._add()
        self.assertEqual(dataset_store.count(self.root), 2)

    def test_count_decrements_after_delete(self):
        s = self._add()
        dataset_store.delete_sample(self.root, s["id"])
        self.assertEqual(dataset_store.count(self.root), 0)


# ---------------------------------------------------------------------------
# delete_sample
# ---------------------------------------------------------------------------

class TestDeleteSample(_TmpRoot):
    def test_returns_true_on_success(self):
        s = self._add()
        self.assertTrue(dataset_store.delete_sample(self.root, s["id"]))

    def test_returns_false_for_unknown_id(self):
        self.assertFalse(dataset_store.delete_sample(self.root, 99999))

    def test_double_delete_returns_false(self):
        s = self._add()
        dataset_store.delete_sample(self.root, s["id"])
        self.assertFalse(dataset_store.delete_sample(self.root, s["id"]))


# ---------------------------------------------------------------------------
# export_jsonl
# ---------------------------------------------------------------------------

class TestExportJsonl(_TmpRoot):
    def test_empty_db_returns_empty_string(self):
        self.assertEqual(dataset_store.export_jsonl(self.root), "")

    def test_bad_fmt_raises(self):
        self._add()
        with self.assertRaises(ValueError):
            dataset_store.export_jsonl(self.root, fmt="bogus")

    def test_case_insensitive_fmt(self):
        self._add()
        out = dataset_store.export_jsonl(self.root, fmt="MESSAGES")
        self.assertTrue(out)

    def test_messages_format_structure(self):
        self._add(prompt="ask", response="ans")
        obj = json.loads(dataset_store.export_jsonl(self.root, fmt="messages"))
        msgs = obj["messages"]
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["content"], "ask")
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertEqual(msgs[1]["content"], "ans")

    def test_alpaca_format_structure(self):
        self._add(prompt="instr", response="out")
        obj = json.loads(dataset_store.export_jsonl(self.root, fmt="alpaca"))
        self.assertEqual(obj["instruction"], "instr")
        self.assertEqual(obj["input"], "")
        self.assertEqual(obj["output"], "out")

    def test_export_order_oldest_first(self):
        self._add(prompt="first")
        self._add(prompt="second")
        lines = dataset_store.export_jsonl(self.root).splitlines()
        first_obj = json.loads(lines[0])
        self.assertEqual(first_obj["messages"][0]["content"], "first")

    def test_min_rating_filters_export(self):
        self._add(rating=2)
        self._add(rating=5)
        lines = dataset_store.export_jsonl(self.root, min_rating=4).splitlines()
        self.assertEqual(len(lines), 1)

    def test_multiple_items_produce_multiple_lines(self):
        self._add(prompt="a")
        self._add(prompt="b")
        self._add(prompt="c")
        lines = dataset_store.export_jsonl(self.root).splitlines()
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
