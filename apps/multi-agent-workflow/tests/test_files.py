"""File sandbox and Executor tool-loop tests. Paths outside the folder must be refused in every form."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from mawf.files import MAX_FILE_BYTES, FileSandbox
from mawf.protocol import ProtocolError, parse_executor_step
from mawf.workflow import Harness, Settings, WorkflowError

from .test_workflow import PASS, FakeModel, done, plan, task


class SandboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.box = FileSandbox(base / "work")
        (base / "secret.txt").write_text("outside", encoding="utf-8")
        self.base = base

    def test_write_then_read_inside_the_folder(self) -> None:
        self.assertTrue(self.box.run({"action": "write_file", "path": "a/b.md", "content": "สวัสดี"})["ok"])
        res = self.box.run({"action": "read_file", "path": "a/b.md"})
        self.assertEqual(res["text"], "สวัสดี")
        self.assertIn("b.md", self.box.run({"action": "list_dir", "path": "a"})["entries"][0])

    def test_traversal_absolute_and_drive_paths_are_refused(self) -> None:
        for path in ("../secret.txt", "a/../../secret.txt", str(self.base / "secret.txt"), "C:/x.txt", "/etc/x"):
            res = self.box.run({"action": "read_file", "path": path})
            self.assertFalse(res["ok"], path)

    def test_writing_outside_the_folder_is_refused(self) -> None:
        res = self.box.run({"action": "write_file", "path": "../escape.txt", "content": "x"})
        self.assertFalse(res["ok"])
        self.assertFalse((self.base / "escape.txt").exists())

    def test_symlink_pointing_out_is_refused(self) -> None:
        link = self.box.root / "link.txt"
        try:
            os.symlink(self.base / "secret.txt", link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks need extra rights on this machine")
        self.assertFalse(self.box.run({"action": "read_file", "path": "link.txt"})["ok"])
        self.assertFalse(self.box.run({"action": "write_file", "path": "link.txt", "content": "x"})["ok"])

    def test_no_delete_or_unknown_actions(self) -> None:
        self.assertFalse(self.box.run({"action": "delete_file", "path": "a.txt"})["ok"])
        self.assertFalse(self.box.run({"action": "run_shell", "path": "x"})["ok"])

    def test_size_limit_on_write(self) -> None:
        big = "x" * (MAX_FILE_BYTES + 1)
        self.assertFalse(self.box.run({"action": "write_file", "path": "big.txt", "content": big})["ok"])

    def test_executor_step_parsing(self) -> None:
        step = parse_executor_step('{"tool": {"action": "list_dir", "path": "."}}')
        self.assertEqual(step.call, {"action": "list_dir", "path": "."})
        self.assertEqual(parse_executor_step('{"status": "done", "output": "ok"}').output, "ok")
        with self.assertRaises(ProtocolError):
            parse_executor_step('{"tool": "write"}')


class ExecutorToolLoopTest(unittest.TestCase):
    def test_executor_writes_a_file_then_reports_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            box = FileSandbox(Path(tmp) / "out")
            planner = FakeModel([plan(task("t1"))])
            executor = FakeModel([
                json.dumps({"tool": {"action": "write_file", "path": "t1.md", "content": "ผล"}}),
                done("เขียนไฟล์ t1.md แล้ว"),
            ])
            report = Harness(planner, executor, FakeModel([PASS]), sandbox=box).run("เป้าหมาย")
            self.assertEqual(report.status, "completed")
            self.assertEqual((box.root / "t1.md").read_text(encoding="utf-8"), "ผล")
            self.assertIn("ผลจากเครื่องมือ", executor.seen[1][-1]["content"])

    def test_tool_step_limit_turns_into_a_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            box = FileSandbox(Path(tmp) / "out")
            call = json.dumps({"tool": {"action": "list_dir", "path": "."}})
            executor = FakeModel([call] * 10)
            report = Harness(FakeModel([plan(task("t1"))]), executor, FakeModel([]), sandbox=box,
                             settings=Settings(max_tool_steps=2)).run("เป้าหมาย")
            self.assertEqual(report.status, "stopped")
            self.assertEqual(report.results[0].status, "blocked")

    def test_without_a_sandbox_the_executor_gets_no_file_tools(self) -> None:
        planner = FakeModel([plan(task("t1"))])
        executor = FakeModel([done("ข้อความอย่างเดียว")])
        report = Harness(planner, executor, FakeModel([PASS])).run("เป้าหมาย")
        self.assertEqual(report.status, "completed")

    def test_bad_tool_reply_is_a_workflow_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            box = FileSandbox(Path(tmp) / "out")
            executor = FakeModel(["ไม่ใช่ JSON"])
            with self.assertRaises(WorkflowError):
                Harness(FakeModel([plan(task("t1"))]), executor, FakeModel([]), sandbox=box).run("เป้าหมาย")


if __name__ == "__main__":
    unittest.main()
