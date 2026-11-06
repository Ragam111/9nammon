"""
test_support_store.py — unittest สำหรับ support ticket store (SQLite, stdlib)
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
            support_store.create_ticket(self.root, "a", "", "body")        # subject ว่าง
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "subj", "   ")     # body ว่าง
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "s", "b", kind="x")      # kind ผิด
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "s", "b", channel="x")   # channel ผิด
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "x" * 201, "b")   # subject ยาวเกิน

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
        self.assertEqual(c["closed"], 0)  # สถานะที่ไม่มีก็ต้องเป็น 0 ไม่ใช่หาย


if __name__ == "__main__":
    unittest.main()


class SupportStoreExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_ticket_returns_dict_with_id(self):
        t = support_store.create_ticket(self.root, "user1", "Issue title", "Issue body")
        self.assertIsInstance(t, dict)
        self.assertIn("id", t)

    def test_get_ticket_returns_none_for_unknown(self):
        result = support_store.get_ticket(self.root, 999999)
        self.assertIsNone(result)

    def test_list_tickets_empty_returns_list(self):
        result = support_store.list_tickets(self.root)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_counts_by_status_empty(self):
        c = support_store.counts_by_status(self.root)
        self.assertEqual(c["total"], 0)
        self.assertEqual(c["open"], 0)

    def test_created_ticket_status_is_open(self):
        t = support_store.create_ticket(self.root, "reporter", "subj", "body")
        self.assertEqual(t["status"], "open")

    def test_set_status_to_resolved(self):
        t = support_store.create_ticket(self.root, "u", "s", "b")
        updated = support_store.set_status(self.root, t["id"], "resolved")
        self.assertEqual(updated["status"], "resolved")
