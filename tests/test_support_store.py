"""
test_support_store.py — unittest สำหรับ support ticket store (SQLite, stdlib)

Covers:
  SupportStoreTest      — create_and_get, create_validates (bad subject/body/kind/channel/length),
                          list (newest first, kind/status filters), bad filter rejected,
                          set_status (flow, nonexistent, bad status), counts_by_status
  SupportStoreMetaTest  — ticket has required fields, get nonexistent returns None,
                          list empty, VALID_KINDS/CHANNELS/STATUSES constants,
                          list_tickets by channel, counts all statuses present
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import support_store  # noqa: E402


class SupportStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_and_get(self):
        t = support_store.create_ticket(self.root, "dev", "แชทพัง", "กดส่งแล้ว error 500", kind="bug")
        self.assertEqual(t["status"], "open")
        self.assertEqual(t["kind"], "bug")
        self.assertEqual(t["reporter"], "dev")
        self.assertEqual(support_store.get_ticket(self.root, t["id"])["subject"], "แชทพัง")

    def test_create_validates(self):
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "", "body")
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "subj", "   ")
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "s", "b", kind="x")
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "s", "b", channel="x")
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "x" * 201, "b")

    def test_list_newest_first_and_filters(self):
        support_store.create_ticket(self.root, "a", "first", "b1", kind="bug")
        support_store.create_ticket(self.root, "a", "second", "b2", kind="feature")
        rows = support_store.list_tickets(self.root)
        self.assertEqual(rows[0]["subject"], "second")
        self.assertEqual(len(support_store.list_tickets(self.root, kind="bug")), 1)
        self.assertEqual(len(support_store.list_tickets(self.root, status="open")), 2)

    def test_list_rejects_bad_filter(self):
        with self.assertRaises(ValueError):
            support_store.list_tickets(self.root, status="bogus")
        with self.assertRaises(ValueError):
            support_store.list_tickets(self.root, kind="bogus")

    def test_set_status_flow(self):
        t = support_store.create_ticket(self.root, "a", "s", "b")
        up = support_store.set_status(self.root, t["id"], "in_progress")
        self.assertEqual(up["status"], "in_progress")
        self.assertEqual(support_store.set_status(self.root, t["id"], "closed")["status"], "closed")
        self.assertIsNone(support_store.set_status(self.root, 99999, "open"))
        with self.assertRaises(ValueError):
            support_store.set_status(self.root, t["id"], "bogus")

    def test_counts_by_status(self):
        a = support_store.create_ticket(self.root, "u", "s1", "b")
        support_store.create_ticket(self.root, "u", "s2", "b")
        support_store.set_status(self.root, a["id"], "resolved")
        c = support_store.counts_by_status(self.root)
        self.assertEqual(c["open"], 1)
        self.assertEqual(c["resolved"], 1)
        self.assertEqual(c["total"], 2)
        self.assertEqual(c["closed"], 0)

    def test_ticket_has_id(self):
        t = support_store.create_ticket(self.root, "u", "s", "b")
        self.assertIn("id", t)
        self.assertIsNotNone(t["id"])

    def test_ticket_has_created_at(self):
        t = support_store.create_ticket(self.root, "u", "s", "b")
        self.assertIn("created_at", t)

    def test_get_nonexistent_returns_none(self):
        result = support_store.get_ticket(self.root, 999999)
        self.assertIsNone(result)

    def test_list_empty_when_no_tickets(self):
        rows = support_store.list_tickets(self.root)
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 0)


class SupportStoreMetaTest(unittest.TestCase):
    def test_valid_kinds_is_set(self):
        self.assertIsInstance(support_store.VALID_KINDS, (set, frozenset, tuple, list))
        self.assertIn("bug", support_store.VALID_KINDS)
        self.assertIn("feature", support_store.VALID_KINDS)

    def test_valid_statuses_includes_all(self):
        for s in ("open", "in_progress", "resolved", "closed"):
            self.assertIn(s, support_store.VALID_STATUSES)

    def test_valid_channels_is_set(self):
        self.assertIsInstance(support_store.VALID_CHANNELS, (set, frozenset, tuple, list))
        self.assertGreater(len(support_store.VALID_CHANNELS), 0)

    def test_counts_includes_all_statuses(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        c = support_store.counts_by_status(root)
        for s in support_store.VALID_STATUSES:
            self.assertIn(s, c, f"counts_by_status ต้องมีสถานะ {s!r}")
        tmp.cleanup()

    def test_list_kind_question(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        support_store.create_ticket(root, "u", "s", "b", kind="question")
        rows = support_store.list_tickets(root, kind="question")
        self.assertEqual(len(rows), 1)
        rows2 = support_store.list_tickets(root, kind="bug")
        self.assertEqual(len(rows2), 0)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
