"""test_agent_approvals.py — P6: agent เสนอ → คนอนุมัติ → ลงมือจริง (เขียนไฟล์/รันคำสั่ง)"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import approvals, core, tools  # noqa: E402
from app import model_backend  # noqa: E402
from unittest import mock  # noqa: E402


class ApprovalsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)       # เก็บคำขอ + เป็น workspace

    def tearDown(self):
        self._tmp.cleanup()

    def test_request_is_pending_and_does_nothing_yet(self):
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                                {"path": "out.txt", "content": "ของจริง"})
        self.assertEqual(rec["status"], "pending")
        self.assertFalse((self.root / "out.txt").exists())   # ยังไม่เขียนจริง

    def test_approve_executes_write(self):
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                                {"path": "out.txt", "content": "เขียนเมื่ออนุมัติ"})
        res = approvals.decide(self.root, rec["id"], "approve")
        self.assertEqual(res["status"], "approved")
        self.assertTrue((self.root / "out.txt").exists())    # เขียนจริงหลังอนุมัติ
        self.assertIn("เขียนเมื่ออนุมัติ", (self.root / "out.txt").read_text(encoding="utf-8"))

    def test_reject_does_not_execute(self):
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                                {"path": "no.txt", "content": "x"})
        res = approvals.decide(self.root, rec["id"], "reject")
        self.assertEqual(res["status"], "rejected")
        self.assertFalse((self.root / "no.txt").exists())

    def test_cannot_decide_twice(self):
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                                {"path": "a.txt", "content": "1"})
        approvals.decide(self.root, rec["id"], "approve")
        again = approvals.decide(self.root, rec["id"], "approve")
        self.assertIn("error", again)

    def test_approve_write_outside_workspace_fails_safely(self):
        # confine: เสนอเขียนนอก workspace → อนุมัติแล้วต้อง FAILED ไม่ใช่เขียนทะลุ
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                                {"path": "../../evil.txt", "content": "x"})
        res = approvals.decide(self.root, rec["id"], "approve")
        self.assertEqual(res["status"], "failed")
        self.assertFalse((self.root.parent.parent / "evil.txt").exists())

    def test_bad_decision_raises(self):
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root), {"path": "a", "content": ""})
        with self.assertRaises(ValueError):
            approvals.decide(self.root, rec["id"], "maybe")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            approvals.request(self.root, "delete_everything", str(self.root), {})


class ProposeToolTest(unittest.TestCase):
    """ส agent loop ที่เปิด approvals → propose_write_file ต้องสร้างคำขอ ไม่เขียนเอง"""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_agent_propose_creates_pending_not_file(self):
        replies = [
            '{"tool":"propose_write_file","args":{"path":"new.py","content":"print(1)"}}',
            '{"final":"เสนอแล้ว รออนุมัติ"}',
        ]
        seq = iter(replies)
        with mock.patch.object(model_backend, "generate",
                               lambda *a, **k: next(seq)):
            res = core.run(self.root, "เขียนไฟล์ใหม่", workspace=self.root,
                           approvals_root=self.root)
        self.assertEqual(res["stopped_reason"], "final")
        self.assertIn("รออนุมัติ", res["steps"][0]["observation"])
        self.assertFalse((self.root / "new.py").exists())    # ยังไม่เขียนจนกว่าจะอนุมัติ
        self.assertEqual(len(approvals.list_pending(self.root)), 1)

    def test_propose_tools_hidden_when_approvals_off(self):
        # ไม่เปิด approvals → ไม่มี tool propose_* (agent เสนอไม่ได้)
        reg = tools.build_registry(tools.Sandbox(self.root))
        self.assertNotIn("propose_write_file", reg)
        reg2 = tools.build_registry(tools.Sandbox(self.root), approvals_root=self.root)
        self.assertIn("propose_write_file", reg2)


class AgentApprovalsExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_kind_write_is_string_constant(self):
        self.assertIsInstance(approvals.KIND_WRITE, str)
        self.assertTrue(len(approvals.KIND_WRITE) > 0)

    def test_request_returns_dict_with_id(self):
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                                {"path": "test.txt", "content": "hello"})
        self.assertIsInstance(rec, dict)
        self.assertIn("id", rec)

    def test_request_initial_status_is_pending(self):
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                                {"path": "f.txt", "content": "data"})
        self.assertEqual(rec["status"], "pending")

    def test_list_pending_contains_new_request(self):
        approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                          {"path": "p.txt", "content": "x"})
        pending = approvals.list_pending(self.root)
        self.assertIsInstance(pending, list)
        self.assertGreater(len(pending), 0)

    def test_approve_returns_approved_status(self):
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                                {"path": "approved.txt", "content": "ok"})
        result = approvals.decide(self.root, rec["id"], "approve")
        self.assertEqual(result["status"], "approved")

    def test_reject_returns_rejected_status(self):
        rec = approvals.request(self.root, approvals.KIND_WRITE, str(self.root),
                                {"path": "rejected.txt", "content": "no"})
        result = approvals.decide(self.root, rec["id"], "reject")
        self.assertEqual(result["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
