"""
test_job_queue.py — unittest สำหรับคิวงาน SQLite (stdlib เท่านั้น)

ทดสอบบน temp dir แยกทุกเคส ไม่แตะ jobs.db จริง
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import job_queue  # noqa: E402


class JobQueueTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_enqueue_and_get(self):
        job = job_queue.enqueue(self.root, "build", {"target": "x"})
        self.assertEqual(job["name"], "build")
        self.assertEqual(job["status"], "pending")
        self.assertEqual(job["payload"], {"target": "x"})
        fetched = job_queue.get_job(self.root, job["id"])
        self.assertEqual(fetched["id"], job["id"])

    def test_enqueue_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            job_queue.enqueue(self.root, "  ")

    def test_enqueue_rejects_non_json_payload(self):
        with self.assertRaises(ValueError):
            job_queue.enqueue(self.root, "x", payload=object())

    def test_list_and_filter_by_status(self):
        a = job_queue.enqueue(self.root, "a")
        job_queue.enqueue(self.root, "b")
        job_queue.set_status(self.root, a["id"], "done")
        self.assertEqual(len(job_queue.list_jobs(self.root)), 2)
        self.assertEqual(len(job_queue.list_jobs(self.root, status="pending")), 1)
        self.assertEqual(len(job_queue.list_jobs(self.root, status="done")), 1)

    def test_list_rejects_bad_status_filter(self):
        with self.assertRaises(ValueError):
            job_queue.list_jobs(self.root, status="bogus")

    def test_set_status_validates(self):
        job = job_queue.enqueue(self.root, "a")
        self.assertTrue(job_queue.set_status(self.root, job["id"], "running"))
        with self.assertRaises(ValueError):
            job_queue.set_status(self.root, job["id"], "bogus")
        self.assertFalse(job_queue.set_status(self.root, 99999, "done"))

    def test_claim_next_is_fifo_and_marks_running(self):
        first = job_queue.enqueue(self.root, "first")
        job_queue.enqueue(self.root, "second")
        claimed = job_queue.claim_next(self.root)
        self.assertEqual(claimed["id"], first["id"])
        self.assertEqual(claimed["status"], "running")
        # claim ครั้งถัดไปได้ตัวที่สอง (ตัวแรกไม่ pending แล้ว)
        claimed2 = job_queue.claim_next(self.root)
        self.assertEqual(claimed2["name"], "second")

    def test_claim_next_empty_returns_none(self):
        self.assertIsNone(job_queue.claim_next(self.root))

    def test_delete(self):
        job = job_queue.enqueue(self.root, "a")
        self.assertTrue(job_queue.delete_job(self.root, job["id"]))
        self.assertIsNone(job_queue.get_job(self.root, job["id"]))
        self.assertFalse(job_queue.delete_job(self.root, job["id"]))


class JobQueueExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_enqueue_returns_dict(self):
        job = job_queue.enqueue(self.root, "task")
        self.assertIsInstance(job, dict)

    def test_enqueue_has_required_keys(self):
        job = job_queue.enqueue(self.root, "task")
        for key in ("id", "name", "status"):
            self.assertIn(key, job)

    def test_enqueue_initial_status_is_pending(self):
        job = job_queue.enqueue(self.root, "task")
        self.assertEqual(job["status"], "pending")

    def test_get_job_returns_none_for_missing(self):
        self.assertIsNone(job_queue.get_job(self.root, 99999))

    def test_list_returns_list(self):
        self.assertIsInstance(job_queue.list_jobs(self.root), list)

    def test_multiple_enqueue_accumulates(self):
        for i in range(3):
            job_queue.enqueue(self.root, f"task{i}")
        self.assertEqual(len(job_queue.list_jobs(self.root)), 3)

    def test_set_status_valid_values(self):
        job = job_queue.enqueue(self.root, "a")
        for status in ("running", "done", "error"):
            job_queue.enqueue(self.root, "b")
        # set to running succeeds and returns True
        self.assertTrue(job_queue.set_status(self.root, job["id"], "running"))


if __name__ == "__main__":
    unittest.main()
