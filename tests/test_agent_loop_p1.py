"""test_agent_loop_p1.py — เกณฑ์ P1 ข้อ 2 และ 5: finish, max_steps, schema ของ step, parse error, echo offline"""

import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import core  # noqa: E402

REQUIRED_KEYS = {"step", "action", "input", "observation", "thought"}


class LoopP1Test(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "a.txt").write_text("เนื้อไฟล์ 42", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, actions, **kw):
        return core.run(Path("/tmp"), "งานทดสอบ", workspace=self.root,
                        generate_fn=core.EchoBackend(actions), **kw)

    def test_a_finish_ends_loop(self):
        res = self._run([{"thought": "เสร็จ", "action": "finish", "final": "เสร็จแล้ว"}])
        self.assertEqual(res["stopped_reason"], "final")
        self.assertEqual(res["final"], "เสร็จแล้ว")
        self.assertEqual(res["steps"][0]["action"], "finish")

    def test_final_alias_still_ends_loop(self):
        # alias เดิม: ใช้ในเทสต์/โค้ดเก่า ยังต้องจบได้
        res = self._run(['{"thought":"x","final":"ตามเดิม"}'])
        self.assertEqual(res["stopped_reason"], "final")
        self.assertEqual(res["final"], "ตามเดิม")

    def test_b_max_steps_reports_stopped_reason(self):
        loop = {"thought": "วน", "tool": "list_dir", "args": {"path": "."}}
        res = self._run([loop] * 20, max_steps=3)
        self.assertEqual(res["stopped_reason"], "max_steps")
        self.assertIsNone(res["final"])
        self.assertEqual(len(res["steps"]), 3)

    def test_c_tool_then_finish_has_two_complete_steps(self):
        res = self._run([
            {"thought": "อ่าน", "tool": "read_file", "args": {"path": "a.txt"}},
            {"thought": "จบ", "action": "finish", "final": "42"},
        ])
        self.assertEqual(res["stopped_reason"], "final")
        self.assertEqual(len(res["steps"]), 2)
        for i, s in enumerate(res["steps"]):
            self.assertTrue(REQUIRED_KEYS <= s.keys(), s)
            self.assertEqual(s["step"], i)
        self.assertIn("42", res["steps"][0]["observation"])
        self.assertEqual(res["steps"][0]["action"], "read_file")
        self.assertEqual(res["steps"][0]["input"], {"path": "a.txt"})

    def test_d_parse_error_step_has_required_fields(self):
        res = self._run(["ไม่ใช่ JSON เลย", {"action": "finish", "final": "กู้คืนได้"}])
        self.assertEqual(len(res["steps"]), 2)
        err = res["steps"][0]
        self.assertTrue(REQUIRED_KEYS <= err.keys(), err)
        self.assertEqual(err["step"], 0)
        self.assertEqual(err["error"], "parse")
        self.assertEqual(err["action"], core.PARSE_ERROR)
        self.assertEqual(res["final"], "กู้คืนได้")

    def test_e_echo_backend_runs_without_network(self):
        # ปิดเครือข่ายทั้งหมด: ถ้ามีการเรียก socket จะ error ทันที
        def no_net(*a, **k):
            raise AssertionError("ห้ามเรียกเครือข่ายใน echo backend")
        with mock.patch.object(socket, "socket", side_effect=no_net), \
                mock.patch.object(socket, "create_connection", side_effect=no_net), \
                mock.patch.object(socket, "getaddrinfo", side_effect=no_net):
            res = self._run([
                {"action": "list_dir", "input": {"path": "."}},
                {"action": "finish", "final": "ออฟไลน์ครบ"},
            ])
        self.assertEqual(res["stopped_reason"], "final")
        self.assertEqual(res["final"], "ออฟไลน์ครบ")
        self.assertIn("a.txt", res["steps"][0]["observation"])

    def test_echo_backend_exhausted_finishes(self):
        backend = core.EchoBackend([])
        res = core.run(Path("/tmp"), "งาน", workspace=self.root, generate_fn=backend)
        self.assertEqual(res["stopped_reason"], "final")
        self.assertEqual(res["final"], core.EchoBackend.EXHAUSTED_TEXT)
        self.assertEqual(backend.calls, 1)


if __name__ == "__main__":
    unittest.main()
