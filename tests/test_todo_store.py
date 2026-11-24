"""test_todo_store.py — CRUD for todo items + corrupted file handling"""

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import todo_store  # noqa: E402


def _remove_tree(path):
    """Delete a temp tree, clearing read-only bits first (Windows refuses to unlink them)."""
    def _clear_readonly(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_clear_readonly)


class TodoStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_remove_tree, self.tmp)

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

    def test_truncated_file_is_preserved_before_add(self):
        # todos.json ที่ถูกตัดกลางคัน (เช่นดิสก์เต็ม/โปรแกรมดับ) ต้องไม่ถูกทิ้งเมื่อ add ครั้งถัดไป
        truncated = '[{"id": 1, "text": "สำคัญ", "done": fa'
        (self.tmp / "todos.json").write_text(truncated, encoding="utf-8")
        item = todo_store.add_todo(self.tmp, "ใหม่")
        self.assertEqual(item["id"], 1)
        self.assertEqual([t["text"] for t in todo_store.load_todos(self.tmp)], ["ใหม่"])
        backups = sorted(self.tmp.glob("todos.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), truncated)

    def test_repeated_load_of_corrupt_file_does_not_multiply_backups(self):
        (self.tmp / "todos.json").write_text("{broken", encoding="utf-8")
        for _ in range(3):
            todo_store.load_todos(self.tmp)
        self.assertEqual(len(list(self.tmp.glob("todos.json.corrupt-*"))), 1)

    def test_non_list_json_is_preserved(self):
        (self.tmp / "todos.json").write_text('{"oops": true}', encoding="utf-8")
        self.assertEqual(todo_store.load_todos(self.tmp), [])
        backups = list(self.tmp.glob("todos.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), '{"oops": true}')


class TodoReadFailureTest(unittest.TestCase):
    """อ่าน todos.json ด้วย OSError → write ต้องถูกปฏิเสธ และไฟล์เดิมต้องไม่ถูกแตะ"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_remove_tree, self.tmp)
        self.path = self.tmp / todo_store.TODOS_FILE_NAME

    def test_add_refused_when_file_cannot_be_read(self):
        # todos.json เป็นโฟลเดอร์ → อ่านไม่ได้ (OSError) แต่ path ยัง exists()
        self.path.mkdir()
        with self.assertRaises(todo_store.TodoReadError):
            todo_store.add_todo(self.tmp, "must be refused")
        self.assertTrue(self.path.is_dir(), "ไฟล์/โฟลเดอร์เดิมต้องไม่ถูกแทนที่")
        self.assertEqual(list(self.tmp.glob(".todos-*.tmp")), [])

    def test_permission_error_on_read_keeps_file_unchanged(self):
        original = b'[{"id": 1, "text": "keep me", "done": false}]'
        self.path.write_bytes(original)
        with patch.object(Path, "read_bytes", side_effect=PermissionError("locked")):
            for op in (
                lambda: todo_store.add_todo(self.tmp, "new"),
                lambda: todo_store.toggle_todo(self.tmp, 1),
                lambda: todo_store.delete_todo(self.tmp, 1),
            ):
                with self.assertRaises(todo_store.TodoReadError):
                    op()
        self.assertEqual(self.path.read_bytes(), original)

    def test_read_error_is_not_reported_as_empty(self):
        with patch.object(Path, "read_bytes", side_effect=PermissionError("locked")):
            self.path.write_bytes(b"[]")
            with self.assertRaises(OSError):
                todo_store.load_todos(self.tmp)

    def test_parse_error_still_backed_up_and_treated_as_empty(self):
        self.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(todo_store.load_todos(self.tmp), [])
        self.assertEqual(len(list(self.tmp.glob("todos.json.corrupt-*"))), 1)


if __name__ == "__main__":
    unittest.main()
