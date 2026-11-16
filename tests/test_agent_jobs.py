"""test_agent_jobs.py — คิวงาน agent (enqueue/claim/complete/get) ให้ n8n ป้อนงานได้"""

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
        self.assertEqual(claimed["id"], a["id"])           # เก่าสุดก่อน
        self.assertEqual(jobs.get(self.root, a["id"])["status"], jobs.RUNNING)

    def test_claim_none_when_no_queued(self):
        j = jobs.enqueue(self.root, "x")
        jobs.claim(self.root)                              # งานเดียว → running
        self.assertIsNone(jobs.claim(self.root))           # ไม่เหลือ queued

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
        jobs.claim(self.root)                               # a → running
        jobs.complete(self.root, a["id"], {"ok": True})     # a → done
        st = jobs.stats(self.root)
        self.assertEqual(st["total"], 2)
        self.assertEqual(st["done"], 1)
        self.assertEqual(st["queued"], 1)

    def test_complete_unknown_id(self):
        self.assertFalse(jobs.complete(self.root, "job-nope", {"ok": True}))


if __name__ == "__main__":
    unittest.main()
