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

    def test_enqueue_returns_dict_with_id(self):
        job = job_queue.enqueue(self.root, "deploy")
        self.assertIsInstance(job, dict)
        self.assertIn("id", job)

    def test_list_jobs_empty_initially(self):
        self.assertEqual(job_queue.list_jobs(self.root), [])

    def test_enqueue_default_payload_is_none_or_empty(self):
        job = job_queue.enqueue(self.root, "sync")
        self.assertIn(job["payload"], (None, {}, ""))

    def test_set_status_done_reflects_in_list(self):
        job = job_queue.enqueue(self.root, "task")
        job_queue.set_status(self.root, job["id"], "done")
        done_jobs = job_queue.list_jobs(self.root, status="done")
        self.assertEqual(len(done_jobs), 1)
        self.assertEqual(done_jobs[0]["id"], job["id"])

    def test_get_job_missing_returns_none(self):
        self.assertIsNone(job_queue.get_job(self.root, 99999))

    def test_multiple_enqueue_increases_list(self):
        for i in range(3):
            job_queue.enqueue(self.root, f"job_{i}")
        self.assertEqual(len(job_queue.list_jobs(self.root)), 3)


if __name__ == "__main__":
    unittest.main()
