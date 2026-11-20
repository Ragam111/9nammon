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


# ---------------------------------------------------------------------------
# TodoStoreExtraTest
# ---------------------------------------------------------------------------

class TodoStoreExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_empty_initially(self):
        self.assertEqual(todo_store.load_todos(self.tmp), [])

    def test_add_todo_has_text_field(self):
        todo_store.add_todo(self.tmp, "Test item")
        todos = todo_store.load_todos(self.tmp)
        self.assertEqual(todos[0]["text"], "Test item")

    def test_add_todo_done_is_false(self):
        todo_store.add_todo(self.tmp, "New task")
        todos = todo_store.load_todos(self.tmp)
        self.assertFalse(todos[0]["done"])

    def test_toggle_changes_done_state(self):
        todo_store.add_todo(self.tmp, "Toggle test")
        todos = todo_store.load_todos(self.tmp)
        tid = todos[0]["id"]
        todo_store.toggle_todo(self.tmp, tid)
        todos = todo_store.load_todos(self.tmp)
        self.assertTrue(todos[0]["done"])

    def test_delete_removes_item(self):
        todo_store.add_todo(self.tmp, "To delete")
        todos = todo_store.load_todos(self.tmp)
        tid = todos[0]["id"]
        todo_store.delete_todo(self.tmp, tid)
        self.assertEqual(len(todo_store.load_todos(self.tmp)), 0)

    def test_corrupted_json_returns_empty_list(self):
        (self.tmp / "todos.json").write_text("{bad json", encoding="utf-8")
        self.assertEqual(todo_store.load_todos(self.tmp), [])


if __name__ == "__main__":
    unittest.main()
