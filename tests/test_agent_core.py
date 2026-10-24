"""test_agent_core.py — sandbox (ความปลอดภัย) + agent loop (think→tool→observe→final)"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import model_backend  # noqa: E402
from app.agent import core, tools  # noqa: E402


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "hello.txt").write_text("สวัสดี world", encoding="utf-8")
        (self.root / "sub").mkdir()
        self.sb = tools.Sandbox(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_read_file_in_workspace(self):
        self.assertIn("world", self.sb.read_file("hello.txt"))

    def test_read_file_outside_workspace_denied(self):
        # แก่นความปลอดภัย: ../ หลุดออกนอก workspace ต้องถูกปฏิเสธ
        with self.assertRaises(tools.ToolError):
            self.sb.read_file("../../../etc/passwd")

    def test_list_dir(self):
        out = self.sb.list_dir(".")
        self.assertIn("hello.txt", out)
        self.assertIn("sub/", out)

    def test_run_command_allowed(self):
        out = self.sb.run_command("ls")
        self.assertIn("hello.txt", out)

    def test_run_command_denied_not_in_allowlist(self):
        with self.assertRaises(tools.ToolError):
            self.sb.run_command("rm -rf /")

    def test_run_command_fullpath_bypass_denied(self):
        # กันเลี่ยง allowlist ด้วย path เต็ม
        with self.assertRaises(tools.ToolError):
            self.sb.run_command("/bin/rm hello.txt")

    def test_run_command_no_shell_injection(self):
        # ; และ && ไม่ถูกตีความ (ไม่ผ่าน shell) — ถูกส่งเป็น args ของ echo เฉย ๆ
        out = self.sb.run_command("echo hi ; rm hello.txt")
        self.assertTrue((self.root / "hello.txt").exists())   # ไฟล์ยังอยู่ = rm ไม่ทำงาน


class _ScriptedLLM:
    """LLM ปลอม: ตอบตามสคริปต์ทีละรอบ (เทส loop แบบ deterministic)"""
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, root, model, messages, num_ctx=8192, options=None):
        self.seen.append(messages)
        return self.replies.pop(0) if self.replies else '{"final":"หมดสคริปต์"}'


class AgentLoopTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "a.txt").write_text("เนื้อไฟล์ลับ 42", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, replies, **kw):
        llm = _ScriptedLLM(replies)
        with mock.patch.object(model_backend, "generate", llm):
            return core.run(Path("/tmp"), "อ่าน a.txt", workspace=self.root, **kw), llm

    def test_tool_then_final(self):
        replies = [
            '{"thought":"อ่านไฟล์","tool":"read_file","args":{"path":"a.txt"}}',
            '{"thought":"เจอแล้ว","final":"ไฟล์มีเลข 42"}',
        ]
        res, _ = self._run(replies)
        self.assertEqual(res["stopped_reason"], "final")
        self.assertEqual(res["final"], "ไฟล์มีเลข 42")
        # step แรกต้องมี observation จาก read_file ที่เห็นเนื้อจริง
        self.assertIn("42", res["steps"][0]["observation"])

    def test_unknown_tool_feeds_error_back(self):
        replies = [
            '{"tool":"delete_everything","args":{}}',
            '{"final":"จบ"}',
        ]
        res, _ = self._run(replies)
        self.assertIn("ไม่รู้จักเครื่องมือ", res["steps"][0]["observation"])
        self.assertEqual(res["final"], "จบ")

    def test_non_json_reply_recovers(self):
        replies = [
            "ขอโทษครับ ผมไม่เข้าใจ",            # ไม่ใช่ JSON
            '{"final":"โอเคแก้แล้ว"}',
        ]
        res, _ = self._run(replies)
        self.assertEqual(res["steps"][0].get("error"), "parse")
        self.assertEqual(res["final"], "โอเคแก้แล้ว")

    def test_max_steps_stop(self):
        # ตอบเรียก tool ไปเรื่อย ไม่ final → ต้องหยุดที่ max_steps ไม่วนไม่จบ
        loop_reply = '{"tool":"list_dir","args":{"path":"."}}'
        res, _ = self._run([loop_reply] * 20, max_steps=3)
        self.assertEqual(res["stopped_reason"], "max_steps")
        self.assertIsNone(res["final"])
        self.assertEqual(len(res["steps"]), 3)

    def test_tool_error_is_observation_not_crash(self):
        replies = [
            '{"tool":"read_file","args":{"path":"../../etc/passwd"}}',   # โดน sandbox ปฏิเสธ
            '{"final":"เข้าไม่ได้"}',
        ]
        res, _ = self._run(replies)
        self.assertIn("[tool error]", res["steps"][0]["observation"])
        self.assertEqual(res["final"], "เข้าไม่ได้")


if __name__ == "__main__":
    unittest.main()
