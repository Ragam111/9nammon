"""test_todo_store.py — CRUD for todo items + corrupted file handling"""

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


class TodoStoreExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_todo_returns_dict(self):
        result = todo_store.add_todo(self.tmp, "task")
        self.assertIsInstance(result, dict)

    def test_add_todo_id_is_int(self):
        result = todo_store.add_todo(self.tmp, "task")
        self.assertIsInstance(result["id"], int)

    def test_add_todo_has_text_key(self):
        result = todo_store.add_todo(self.tmp, "task text")
        self.assertIn("text", result)
        self.assertEqual(result["text"], "task text")

    def test_load_todos_returns_list(self):
        todo_store.add_todo(self.tmp, "t1")
        todos = todo_store.load_todos(self.tmp)
        self.assertIsInstance(todos, list)

    def test_toggle_returns_bool(self):
        t = todo_store.add_todo(self.tmp, "toggle me")
        result = todo_store.toggle_todo(self.tmp, t["id"])
        self.assertIsInstance(result, bool)

    def test_delete_returns_bool(self):
        t = todo_store.add_todo(self.tmp, "delete me")
        result = todo_store.delete_todo(self.tmp, t["id"])
        self.assertIsInstance(result, bool)
        self.assertTrue(result)

    def test_delete_missing_returns_false(self):
        result = todo_store.delete_todo(self.tmp, 99999)
        self.assertIsInstance(result, bool)
        self.assertFalse(result)

    def test_add_multiple_ids_unique(self):
        t1 = todo_store.add_todo(self.tmp, "first")
        t2 = todo_store.add_todo(self.tmp, "second")
        self.assertNotEqual(t1["id"], t2["id"])


if __name__ == "__main__":
    unittest.main()
