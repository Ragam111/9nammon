"""
test_support_store.py — unittest สำหรับ support ticket store (SQLite, stdlib)

Covers:
  create_ticket() — happy path, all validation cases (empty subject/body, too-long,
                    invalid kind/channel), return shape, None reporter
  list_tickets()  — newest first, status/kind filters, combined filter, limit, bad filter
  get_ticket()    — found, not found (None)
  set_status()    — status transitions, invalid status, unknown id returns None
  counts_by_status() — empty db all-zero, all statuses present, total key, correct counts
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import support_store  # noqa: E402


class _TmpRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _ticket(self, **kwargs):
        defaults = {"reporter": "dev", "subject": "subj", "body": "body text"}
        defaults.update(kwargs)
        return support_store.create_ticket(self.root, **defaults)


# ---------------------------------------------------------------------------
# create_ticket — validation
# ---------------------------------------------------------------------------

class TestCreateTicketValidation(_TmpRoot):
    def test_empty_subject_raises(self):
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "", "body")

    def test_blank_body_raises(self):
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "subj", "   ")

    def test_subject_too_long_raises(self):
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "x" * 201, "body")

    def test_body_too_long_raises(self):
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "subj", "y" * 5001)

    def test_invalid_kind_raises(self):
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "s", "b", kind="unknown")

    def test_invalid_channel_raises(self):
        with self.assertRaises(ValueError):
            support_store.create_ticket(self.root, "a", "s", "b", channel="telegram")


# ---------------------------------------------------------------------------
# create_ticket — happy path and return shape
# ---------------------------------------------------------------------------

class TestCreateTicketShape(_TmpRoot):
    def test_returns_dict(self):
        self.assertIsInstance(self._ticket(), dict)

    def test_return_has_all_expected_fields(self):
        t = self._ticket()
        for field in ("id", "created_at", "updated_at", "channel", "reporter",
                      "kind", "subject", "body", "status"):
            self.assertIn(field, t)

    def test_default_status_is_open(self):
        self.assertEqual(self._ticket()["status"], "open")

    def test_default_kind_is_bug(self):
        self.assertEqual(self._ticket()["kind"], "bug")

    def test_default_channel_is_web(self):
        self.assertEqual(self._ticket()["channel"], "web")

    def test_none_reporter_stored_as_none(self):
        t = support_store.create_ticket(self.root, None, "s", "b")
        self.assertIsNone(t["reporter"])

    def test_custom_kind_stored(self):
        t = self._ticket(kind="feature")
        self.assertEqual(t["kind"], "feature")

    def test_custom_channel_stored(self):
        t = self._ticket(channel="api")
        self.assertEqual(t["channel"], "api")


# ---------------------------------------------------------------------------
# list_tickets
# ---------------------------------------------------------------------------

class TestListTickets(_TmpRoot):
    def test_empty_db_returns_empty_list(self):
        self.assertEqual(support_store.list_tickets(self.root), [])

    def test_newest_first_ordering(self):
        self._ticket(subject="first")
        self._ticket(subject="second")
        rows = support_store.list_tickets(self.root)
        self.assertEqual(rows[0]["subject"], "second")

    def test_status_filter(self):
        t = self._ticket()
        support_store.set_status(self.root, t["id"], "resolved")
        self._ticket()
        self.assertEqual(len(support_store.list_tickets(self.root, status="open")), 1)
        self.assertEqual(len(support_store.list_tickets(self.root, status="resolved")), 1)

    def test_kind_filter(self):
        self._ticket(kind="bug")
        self._ticket(kind="feature")
        self.assertEqual(len(support_store.list_tickets(self.root, kind="bug")), 1)

    def test_combined_status_and_kind_filter(self):
        self._ticket(kind="bug")
        t2 = self._ticket(kind="bug")
        support_store.set_status(self.root, t2["id"], "closed")
        rows = support_store.list_tickets(self.root, status="open", kind="bug")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "open")

    def test_limit_parameter(self):
        for i in range(5):
            self._ticket(subject=f"s{i}")
        rows = support_store.list_tickets(self.root, limit=2)
        self.assertEqual(len(rows), 2)

    def test_invalid_status_filter_raises(self):
        with self.assertRaises(ValueError):
            support_store.list_tickets(self.root, status="bogus")

    def test_invalid_kind_filter_raises(self):
        with self.assertRaises(ValueError):
            support_store.list_tickets(self.root, kind="bogus")


# ---------------------------------------------------------------------------
# get_ticket
# ---------------------------------------------------------------------------

class TestGetTicket(_TmpRoot):
    def test_returns_matching_ticket(self):
        t = self._ticket(subject="hello world")
        result = support_store.get_ticket(self.root, t["id"])
        self.assertEqual(result["subject"], "hello world")

    def test_unknown_id_returns_none(self):
        self.assertIsNone(support_store.get_ticket(self.root, 99999))


# ---------------------------------------------------------------------------
# set_status
# ---------------------------------------------------------------------------

class TestSetStatus(_TmpRoot):
    def test_status_transitions(self):
        t = self._ticket()
        up = support_store.set_status(self.root, t["id"], "in_progress")
        self.assertEqual(up["status"], "in_progress")
        up2 = support_store.set_status(self.root, t["id"], "closed")
        self.assertEqual(up2["status"], "closed")

    def test_unknown_id_returns_none(self):
        self.assertIsNone(support_store.set_status(self.root, 99999, "open"))

    def test_invalid_status_raises(self):
        t = self._ticket()
        with self.assertRaises(ValueError):
            support_store.set_status(self.root, t["id"], "bogus")


# ---------------------------------------------------------------------------
# counts_by_status
# ---------------------------------------------------------------------------

class TestCountsByStatus(_TmpRoot):
    def test_empty_db_all_zeros(self):
        c = support_store.counts_by_status(self.root)
        for s in support_store.VALID_STATUSES:
            self.assertEqual(c[s], 0)

    def test_has_total_key(self):
        c = support_store.counts_by_status(self.root)
        self.assertIn("total", c)

    def test_total_zero_when_empty(self):
        self.assertEqual(support_store.counts_by_status(self.root)["total"], 0)

    def test_all_valid_statuses_present(self):
        c = support_store.counts_by_status(self.root)
        for s in support_store.VALID_STATUSES:
            self.assertIn(s, c)

    def test_counts_correct_after_set_status(self):
        a = self._ticket()
        self._ticket()
        support_store.set_status(self.root, a["id"], "resolved")
        c = support_store.counts_by_status(self.root)
        self.assertEqual(c["open"], 1)
        self.assertEqual(c["resolved"], 1)
        self.assertEqual(c["total"], 2)
        self.assertEqual(c["closed"], 0)


if __name__ == "__main__":
    unittest.main()
