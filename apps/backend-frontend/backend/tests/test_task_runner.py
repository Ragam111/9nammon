"""The task runner: config checks, pass/fail/timeout, retries, RAM gate, and result order."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts import task_runner as tr


def _task(name: str, code: str, cwd: Path, **extra: object) -> tr.Task:
    values: dict[str, object] = {"timeout_s": 30.0, "retries": 0, "min_free_mb": 0}
    values.update(extra)
    return tr.Task(
        name=name,
        cmd=[sys.executable, "-c", code],
        cwd=cwd,
        timeout_s=float(values["timeout_s"]),  # type: ignore[arg-type]
        retries=int(values["retries"]),  # type: ignore[call-overload]
        min_free_mb=int(values["min_free_mb"]),  # type: ignore[call-overload]
    )


class LoadTasksTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, data: object) -> Path:
        path = self.dir / "tasks.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_defaults_and_python_is_replaced(self) -> None:
        path = self._write({"tasks": [{"name": "a", "cmd": ["python", "-V"]}]})
        (task,) = tr.load_tasks(path)
        self.assertEqual(task.cmd, [sys.executable, "-V"])
        self.assertEqual(task.cwd, self.dir.resolve())
        self.assertEqual(task.retries, 0)
        self.assertEqual(task.min_free_mb, tr.DEFAULT_MIN_FREE_MB)

    def test_string_cmd_stays_a_string(self) -> None:
        path = self._write({"tasks": [{"name": "a", "cmd": "npm run lint", "cwd": "sub"}]})
        (task,) = tr.load_tasks(path)
        self.assertEqual(task.cmd, "npm run lint")
        self.assertEqual(task.cwd, (self.dir / "sub").resolve())

    def test_duplicate_names_are_rejected(self) -> None:
        path = self._write({"tasks": [{"name": "a", "cmd": ["x"]}, {"name": "a", "cmd": ["y"]}]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            tr.load_tasks(path)

    def test_empty_task_list_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty"):
            tr.load_tasks(self._write({"tasks": []}))

    def test_bad_cmd_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cmd"):
            tr.load_tasks(self._write({"tasks": [{"name": "a", "cmd": []}]}))

    def test_concurrency_out_of_range_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            tr.run_all([], tr.MAX_CONCURRENCY + 1, self.dir, 0)


class RunOnceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pass_and_fail_report_exit_code(self) -> None:
        ok = tr.run_once(_task("ok", "pass", self.dir), self.dir / "ok.log")
        bad = tr.run_once(_task("bad", "raise SystemExit(3)", self.dir), self.dir / "bad.log")
        self.assertEqual((ok[0], ok[1]), ("passed", 0))
        self.assertEqual((bad[0], bad[1]), ("failed", 3))

    def test_output_goes_to_log(self) -> None:
        tr.run_once(_task("p", "print('hello-log')", self.dir), self.dir / "p.log")
        self.assertIn("hello-log", (self.dir / "p.log").read_text(encoding="utf-8"))

    def test_missing_cwd_is_an_error_not_a_crash(self) -> None:
        task = _task("gone", "pass", self.dir / "does-not-exist")
        status, code, _ = tr.run_once(task, self.dir / "gone.log")
        self.assertEqual((status, code), ("error", None))

    def test_timeout_stops_the_child(self) -> None:
        start = time.monotonic()
        status, code, _ = tr.run_once(
            _task("slow", "import time; time.sleep(60)", self.dir, timeout_s=1.0), self.dir / "s.log"
        )
        self.assertEqual((status, code), ("timeout", None))
        self.assertLess(time.monotonic() - start, 30)


class RunTaskTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_retry_until_a_later_attempt_passes(self) -> None:
        flag = (self.dir / "flag").as_posix()
        code = (
            "import os, sys\n"
            f"p = {flag!r}\n"
            "if os.path.exists(p):\n"
            "    sys.exit(0)\n"
            "open(p, 'w').close()\n"
            "sys.exit(1)\n"
        )
        result = tr.run_task(_task("flaky", code, self.dir, retries=2), self.dir, gate_wait_s=0)
        self.assertEqual((result.status, result.attempts), ("passed", 2))

    def test_gives_up_after_retries(self) -> None:
        result = tr.run_task(_task("never", "raise SystemExit(1)", self.dir, retries=1), self.dir, gate_wait_s=0)
        self.assertEqual((result.status, result.attempts, result.exit_code), ("failed", 2, 1))

    def test_low_memory_skips_without_running(self) -> None:
        marker = self.dir / "ran.txt"
        code = f"open({marker.as_posix()!r}, 'w').close()"
        with mock.patch.object(tr, "free_mb", return_value=100):
            result = tr.run_task(_task("big", code, self.dir, min_free_mb=800), self.dir, gate_wait_s=0)
        self.assertEqual(result.status, "skipped")
        self.assertIn("low memory", result.reason)
        self.assertFalse(marker.exists())

    def test_unknown_memory_does_not_block(self) -> None:
        with mock.patch.object(tr, "free_mb", return_value=None):
            result = tr.run_task(_task("unknown", "pass", self.dir, min_free_mb=800), self.dir, gate_wait_s=0)
        self.assertEqual(result.status, "passed")


class RunAllTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_results_keep_input_order_with_two_workers(self) -> None:
        tasks = [
            _task("first", "import time; time.sleep(0.5)", self.dir),
            _task("second", "pass", self.dir),
            _task("third", "raise SystemExit(2)", self.dir),
        ]
        results = tr.run_all(tasks, 2, self.dir, gate_wait_s=0)
        self.assertEqual([r.name for r in results], ["first", "second", "third"])
        self.assertEqual([r.status for r in results], ["passed", "passed", "failed"])

    def test_report_counts(self) -> None:
        results = tr.run_all([_task("a", "pass", self.dir), _task("b", "raise SystemExit(1)", self.dir)], 1,
                             self.dir, gate_wait_s=0)
        report = tr.build_report(results, 1, 1.5)
        self.assertEqual(report["counts"], {"passed": 1, "failed": 1})
        self.assertEqual(report["concurrency"], 1)


if __name__ == "__main__":
    unittest.main()
