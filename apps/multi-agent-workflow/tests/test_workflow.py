"""Multi-agent workflow tests: plan validation, the Harness loop, retries, blocks and the transcript.

All three roles are fake models with scripted replies, so no API key or network is needed.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mawf.models import ModelError
from mawf.protocol import ProtocolError, parse_executor, parse_plan, parse_verdict
from mawf.workflow import Harness, Settings, WorkflowError


class FakeModel:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.seen: list[list[dict[str, str]]] = []

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        self.seen.append(messages)
        if not self.replies:
            raise ModelError("script ran out")
        return self.replies.pop(0)


def plan(*tasks: dict[str, object]) -> str:
    return json.dumps({"tasks": list(tasks)}, ensure_ascii=False)


def task(tid: str, deps: list[str] | None = None) -> dict[str, object]:
    return {"id": tid, "title": f"งาน {tid}", "acceptance": f"ผลของ {tid} ครบ", "depends_on": deps or []}


def done(output: str) -> str:
    return json.dumps({"status": "done", "output": output}, ensure_ascii=False)


PASS = json.dumps({"pass": True, "reason": "ครบ"}, ensure_ascii=False)
FAIL = json.dumps({"pass": False, "reason": "ขาดรายละเอียด"}, ensure_ascii=False)


class PlanTest(unittest.TestCase):
    def test_valid_plan_comes_back_in_dependency_order(self) -> None:
        raw = plan(task("t2", ["t1"]), task("t1"))
        self.assertEqual([t.id for t in parse_plan(raw)], ["t1", "t2"])

    def test_cycle_unknown_dependency_self_dependency_and_duplicates_are_rejected(self) -> None:
        bad = [
            plan(task("a", ["b"]), task("b", ["a"])),
            plan(task("a", ["zzz"])),
            plan(task("a", ["a"])),
            plan(task("a"), task("a")),
        ]
        for raw in bad:
            with self.assertRaises(ProtocolError, msg=raw):
                parse_plan(raw)

    def test_too_many_tasks_and_empty_plans_are_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_plan(plan(*[task(f"t{i}") for i in range(9)]))
        with self.assertRaises(ProtocolError):
            parse_plan(json.dumps({"tasks": []}))

    def test_executor_and_judge_shapes_are_checked(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_executor('{"status": "maybe", "output": "x"}')
        with self.assertRaises(ProtocolError):
            parse_executor('{"status": "done", "output": ""}')
        with self.assertRaises(ProtocolError):
            parse_verdict('{"pass": "yes"}')
        self.assertEqual(parse_verdict(PASS), (True, "ครบ"))


class HarnessTest(unittest.TestCase):
    def test_runs_in_order_and_gives_dependency_output_to_the_next_task(self) -> None:
        planner = FakeModel([plan(task("t1"), task("t2", ["t1"]))])
        executor = FakeModel([done("ผล A"), done("ผล B")])
        judge = FakeModel([PASS, PASS])
        report = Harness(planner, executor, judge).run("เป้าหมาย")
        self.assertEqual(report.status, "completed")
        self.assertEqual([r.task_id for r in report.results], ["t1", "t2"])
        second_prompt = executor.seen[1][0]["content"]
        self.assertIn("[t1] ผล A", second_prompt)

    def test_rejected_output_is_retried_with_the_judges_reason(self) -> None:
        planner = FakeModel([plan(task("t1"))])
        executor = FakeModel([done("ร่าง"), done("ฉบับแก้")])
        judge = FakeModel([FAIL, PASS])
        report = Harness(planner, executor, judge).run("เป้าหมาย")
        self.assertEqual(report.status, "completed")
        self.assertIn("ขาดรายละเอียด", executor.seen[1][0]["content"])

    def test_task_rejected_every_time_stops_the_run(self) -> None:
        planner = FakeModel([plan(task("t1"), task("t2"))])
        executor = FakeModel([done("x")] * 3)
        judge = FakeModel([FAIL] * 3)
        report = Harness(planner, executor, judge, Settings(max_retries=2)).run("เป้าหมาย")
        self.assertEqual(report.status, "stopped")
        self.assertEqual(report.results[-1].status, "rejected")
        self.assertEqual(len(report.results), 1)  # t2 never ran

    def test_blocked_executor_stops_without_asking_the_judge(self) -> None:
        planner = FakeModel([plan(task("t1"))])
        executor = FakeModel([json.dumps({"status": "blocked", "output": "ไม่มีข้อมูลพอ"}, ensure_ascii=False)])
        judge = FakeModel([])
        report = Harness(planner, executor, judge).run("เป้าหมาย")
        self.assertEqual(report.status, "stopped")
        self.assertEqual(report.results[0].status, "blocked")

    def test_invalid_plan_gets_one_correction_then_succeeds(self) -> None:
        planner = FakeModel(["ไม่ใช่ JSON", plan(task("t1"))])
        executor = FakeModel([done("ok")])
        judge = FakeModel([PASS])
        report = Harness(planner, executor, judge).run("เป้าหมาย")
        self.assertEqual(report.status, "completed")
        self.assertIn("แผนไม่ถูกต้อง", planner.seen[1][-1]["content"])

    def test_invalid_plan_twice_is_an_error(self) -> None:
        planner = FakeModel(["x", "y"])
        with self.assertRaises(WorkflowError):
            Harness(planner, FakeModel([]), FakeModel([])).run("เป้าหมาย")

    def test_transcript_records_every_role_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            planner = FakeModel([plan(task("t1"))])
            Harness(planner, FakeModel([done("ok")]), FakeModel([PASS]), transcript=path).run("เป้าหมาย")
            roles = [json.loads(line)["role"] for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(roles, ["planner", "executor", "harness"])


if __name__ == "__main__":
    unittest.main()
