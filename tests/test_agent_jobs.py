"""test_agent_jobs.py — คิวงาน agent (enqueue/claim/complete/get) ให้ n8n ป้อนงานได้

Covers:
  AgentJobsTest      — enqueue_then_get, enqueue_empty_rejected, claim_marks_running_fifo,
                       claim_none_when_no_queued, complete_done_and_error, stats_counts,
                       complete_unknown_id
  AgentJobsMetaTest  — enqueue returns required fields, whitespace-only task rejected,
                       get nonexistent returns None, list_jobs returns list, stats has keys,
                       job has created_at, constants (QUEUED/RUNNING/DONE/ERROR)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import jobs  # noqa: E402


class AgentJobsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_enqueue_then_get(self):
        j = jobs.enqueue(self.root, "วิเคราะห์ server.py", source="n8n")
        self.assertEqual(j["status"], jobs.QUEUED)
        self.assertEqual(jobs.get(self.root, j["id"])["source"], "n8n")

    def test_enqueue_empty_rejected(self):
        with self.assertRaises(ValueError):
            jobs.enqueue(self.root, "   ")

    def test_claim_marks_running_fifo(self):
        a = jobs.enqueue(self.root, "งาน A")
        jobs.enqueue(self.root, "งาน B")
        claimed = jobs.claim(self.root)
        self.assertEqual(claimed["id"], a["id"])
        self.assertEqual(jobs.get(self.root, a["id"])["status"], jobs.RUNNING)

    def test_claim_none_when_no_queued(self):
        j = jobs.enqueue(self.root, "x")
        jobs.claim(self.root)
        self.assertIsNone(jobs.claim(self.root))

    def test_complete_done_and_error(self):
        a = jobs.enqueue(self.root, "a"); jobs.claim(self.root)
        jobs.complete(self.root, a["id"], {"ok": True, "final": "เสร็จ", "steps": 2, "duration_s": 1.0})
        ja = jobs.get(self.root, a["id"])
        self.assertEqual(ja["status"], jobs.DONE)
        self.assertEqual(ja["result"]["final"], "เสร็จ")
        b = jobs.enqueue(self.root, "b"); jobs.claim(self.root)
        jobs.complete(self.root, b["id"], {"ok": False, "error": "พัง"})
        self.assertEqual(jobs.get(self.root, b["id"])["status"], jobs.ERROR)

    def test_stats_counts(self):
        a = jobs.enqueue(self.root, "a"); jobs.enqueue(self.root, "b")
        jobs.claim(self.root)
        jobs.complete(self.root, a["id"], {"ok": True})
        st = jobs.stats(self.root)
        self.assertEqual(st["total"], 2)
        self.assertEqual(st["done"], 1)
        self.assertEqual(st["queued"], 1)

    def test_complete_unknown_id(self):
        self.assertFalse(jobs.complete(self.root, "job-nope", {"ok": True}))


class AgentJobsMetaTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_enqueue_returns_required_fields(self):
        j = jobs.enqueue(self.root, "task test")
        for field in ("id", "status", "task", "source", "created_at"):
            self.assertIn(field, j, f"missing field: {field}")

    def test_enqueue_whitespace_only_rejected(self):
        for bad in ("   ", "\t", "\n", ""):
            with self.assertRaises(ValueError, msg=f"ต้อง reject task={bad!r}"):
                jobs.enqueue(self.root, bad)

    def test_get_nonexistent_returns_none(self):
        result = jobs.get(self.root, "job-nonexistent-id")
        self.assertIsNone(result)

    def test_list_jobs_returns_list(self):
        jobs.enqueue(self.root, "task 1")
        jobs.enqueue(self.root, "task 2")
        result = jobs.list_jobs(self.root)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_stats_has_required_keys(self):
        st = jobs.stats(self.root)
        for key in ("total", "queued", "running", "done", "error"):
            self.assertIn(key, st, f"stats ต้องมี key: {key}")

    def test_job_has_created_at(self):
        j = jobs.enqueue(self.root, "task with time")
        self.assertIn("created_at", j)
        self.assertIsNotNone(j["created_at"])

    def test_constants_are_strings(self):
        for const in (jobs.QUEUED, jobs.RUNNING, jobs.DONE, jobs.ERROR):
            self.assertIsInstance(const, str)
            self.assertGreater(len(const), 0)

    def test_stats_all_zero_when_empty(self):
        st = jobs.stats(self.root)
        self.assertEqual(st["total"], 0)
        self.assertEqual(st["queued"], 0)
        self.assertEqual(st["done"], 0)


if __name__ == "__main__":
    unittest.main()
