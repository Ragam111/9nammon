"""Offline demo: the whole workflow runs with no API key, and the CLI exits with the right codes."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mawf.__main__ import main
from mawf.demo import DEMO_GOAL, NOTE_PATH, NOTE_TEXT, DemoModel
from mawf.files import FileSandbox
from mawf.workflow import Harness


class DemoWorkflowTests(unittest.TestCase):
    def test_demo_model_completes_with_file_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = FileSandbox(Path(tmp))
            model = DemoModel()
            report = Harness(model, model, model, sandbox=sandbox).run(DEMO_GOAL)
            self.assertEqual(report.status, "completed")
            self.assertEqual([r.task_id for r in report.results], ["t1", "t2"])
            self.assertTrue(all(r.status == "accepted" for r in report.results))
            self.assertEqual((Path(tmp) / NOTE_PATH).read_text(encoding="utf-8"), NOTE_TEXT)
            self.assertIn(NOTE_TEXT, report.results[1].output)

    def test_demo_model_completes_text_only(self) -> None:
        model = DemoModel()
        report = Harness(model, model, model).run(DEMO_GOAL)
        self.assertEqual(report.status, "completed")
        self.assertEqual(report.results[0].output, NOTE_TEXT)


class DemoCliTests(unittest.TestCase):
    def run_cli(self, argv: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=True), contextlib.redirect_stdout(out):
            code = main(argv)
        return code, out.getvalue()

    def test_demo_runs_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, text = self.run_cli(["--demo", "--workdir", tmp])
            self.assertEqual(code, 0)
            self.assertIn("สถานะ: เสร็จ", text)
            self.assertTrue((Path(tmp) / NOTE_PATH).is_file())

    def test_real_run_without_key_is_a_setup_error(self) -> None:
        code, _ = self.run_cli(["เป้าหมายทดสอบ"])
        self.assertEqual(code, 2)

    def test_missing_goal_is_a_usage_error(self) -> None:
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(io.StringIO()):
            self.run_cli([])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
