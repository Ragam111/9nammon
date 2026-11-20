"""test_todo_store.py — CRUD for todo items + corrupted file handling

Covers:
  TodoStoreTest      — load_empty, add_and_load, add_multiple, ids_auto_increment,
                       toggle, delete, delete_nonexistent, corrupted_file_returns_empty
  TodoStoreMetaTest  — add returns dict, item has id, text is str, done is bool,
                       load returns list, toggle returns bool, delete returns bool,
                       id increments on delete, text preserved exactly, done starts false,
                       toggle twice restores original, non-list file returns empty
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import todo_store  # noqa: E402


class TodoStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_load_empty(self):
        todos = todo_store.load_todos(self.tmp)
        self.assertEqual(todos, [])

    def test_add_and_load(self):
        todo_store.add_todo(self.tmp, "Buy milk")
        todos = todo_store.load_todos(self.tmp)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]["text"], "Buy milk")
        self.assertFalse(todos[0]["done"])

    def test_add_multiple(self):
        todo_store.add_todo(self.tmp, "Task 1")
        todo_store.add_todo(self.tmp, "Task 2")
        todo_store.add_todo(self.tmp, "Task 3")
        todos = todo_store.load_todos(self.tmp)
        self.assertEqual(len(todos), 3)

    def test_ids_auto_increment(self):
        todo_store.add_todo(self.tmp, "A")
        todo_store.add_todo(self.tmp, "B")
        todos = todo_store.load_todos(self.tmp)
        self.assertNotEqual(todos[0]["id"], todos[1]["id"])

    def test_toggle(self):
        todo_store.add_todo(self.tmp, "Toggle me")
        todos = todo_store.load_todos(self.tmp)
        tid = todos[0]["id"]
        self.assertFalse(todos[0]["done"])
        todo_store.toggle_todo(self.tmp, tid)
        todos = todo_store.load_todos(self.tmp)
        self.assertTrue(todos[0]["done"])
        todo_store.toggle_todo(self.tmp, tid)
        todos = todo_store.load_todos(self.tmp)
        self.assertFalse(todos[0]["done"])

    def test_delete(self):
        todo_store.add_todo(self.tmp, "Delete me")
        todos = todo_store.load_todos(self.tmp)
        tid = todos[0]["id"]
        todo_store.delete_todo(self.tmp, tid)
        todos = todo_store.load_todos(self.tmp)
        self.assertEqual(len(todos), 0)

    def test_delete_nonexistent(self):
        todo_store.delete_todo(self.tmp, 9999)
        todos = todo_store.load_todos(self.tmp)
        self.assertEqual(len(todos), 0)

    def test_corrupted_file_returns_empty(self):
        (self.tmp / "todos.json").write_text("NOT JSON!!!", encoding="utf-8")
        todos = todo_store.load_todos(self.tmp)
        self.assertEqual(todos, [])


class TodoStoreMetaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_add_returns_dict(self):
        item = todo_store.add_todo(self.tmp, "Meta task")
        self.assertIsInstance(item, dict)

    def test_item_has_id(self):
        item = todo_store.add_todo(self.tmp, "id test")
        self.assertIn("id", item)
        self.assertIsNotNone(item["id"])

    def test_item_text_is_str(self):
        item = todo_store.add_todo(self.tmp, "text check")
        self.assertIsInstance(item["text"], str)

    def test_item_done_is_bool(self):
        item = todo_store.add_todo(self.tmp, "bool check")
        self.assertIsInstance(item["done"], bool)

    def test_load_returns_list(self):
        result = todo_store.load_todos(self.tmp)
        self.assertIsInstance(result, list)

    def test_toggle_returns_bool(self):
        item = todo_store.add_todo(self.tmp, "toggle bool")
        result = todo_store.toggle_todo(self.tmp, item["id"])
        self.assertIsInstance(result, bool)

    def test_delete_returns_bool(self):
        item = todo_store.add_todo(self.tmp, "delete bool")
        result = todo_store.delete_todo(self.tmp, item["id"])
        self.assertIsInstance(result, bool)

    def test_text_preserved_exactly(self):
        text = "สวัสดี World! 123 @#$"
        item = todo_store.add_todo(self.tmp, text)
        self.assertEqual(item["text"], text)

    def test_done_starts_false(self):
        item = todo_store.add_todo(self.tmp, "new task")
        self.assertFalse(item["done"])

    def test_id_no_clash_after_middle_delete(self):
        a = todo_store.add_todo(self.tmp, "A")
        b = todo_store.add_todo(self.tmp, "B")
        todo_store.delete_todo(self.tmp, a["id"])
        c = todo_store.add_todo(self.tmp, "C")
        # C's id must not clash with B's still-existing id
        self.assertNotEqual(c["id"], b["id"])

    def test_non_list_json_returns_empty(self):
        (self.tmp / "todos.json").write_text('{"not": "a list"}', encoding="utf-8")
        todos = todo_store.load_todos(self.tmp)
        self.assertEqual(todos, [])


if __name__ == "__main__":
    unittest.main()
