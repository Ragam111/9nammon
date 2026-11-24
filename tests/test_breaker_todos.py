"""test_breaker_todos.py — adversarial probes for app/todo_store.py (expected to FAIL until fixed).

1. A failed write must not be reported as success.
2. Concurrent add_todo calls must not lose items (read-modify-write has no lock).
"""

import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import todo_store  # noqa: E402


def _remove_tree(path):
    """Delete a temp tree, clearing read-only bits first (Windows refuses to unlink them)."""
    def _clear_readonly(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_clear_readonly)


class BreakerTodoStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_remove_tree, self.tmp)

    def test_write_failure_is_not_reported_as_success(self):
        # todos.json occupied by a directory -> the write must fail, and the caller must hear about it.
        (self.tmp / todo_store.TODOS_FILE_NAME).mkdir()
        with self.assertRaises(OSError):
            todo_store.add_todo(self.tmp, "should not be silently dropped")

    def test_concurrent_adds_do_not_lose_items(self):
        n = 20
        errors = []

        def add(i):
            try:
                todo_store.add_todo(self.tmp, f"item {i}")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=add, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(todo_store.load_todos(self.tmp)), n)


if __name__ == "__main__":
    unittest.main()
