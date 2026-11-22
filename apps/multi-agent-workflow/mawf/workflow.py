"""Agent 1 (Harness): asks the Planner for a plan, runs each task through the Executor in dependency order,
has the judge check each result, retries a failed task a limited number of times, and stops on a block.

The Harness is the only role that decides whether work is accepted. The Planner and Executor only report.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ModelClient, ModelError
from .protocol import ProtocolError, Task, parse_executor, parse_plan, parse_verdict
from .roles import EXECUTOR_SYSTEM, HARNESS_JUDGE_SYSTEM, PLANNER_SYSTEM


class WorkflowError(RuntimeError):
    """A role replied with an invalid shape after the retry, or a model call failed."""


@dataclass(frozen=True)
class Settings:
    max_retries: int = 2  # extra Executor attempts for a task the judge rejects
    plan_retries: int = 1  # extra Planner attempts when the plan is not a valid graph


@dataclass
class TaskResult:
    task_id: str
    status: str  # "accepted" | "rejected" | "blocked"
    output: str = ""
    reason: str = ""


@dataclass
class Report:
    status: str  # "completed" | "stopped"
    goal: str
    results: list[TaskResult] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


class Harness:
    def __init__(self, planner: ModelClient, executor: ModelClient, judge: ModelClient,
                 settings: Settings | None = None, transcript: Path | None = None) -> None:
        self.planner = planner
        self.executor = executor
        self.judge = judge
        self.settings = settings or Settings()
        self.transcript = transcript
        self.events: list[dict[str, Any]] = []

    def run(self, goal: str) -> Report:
        tasks = self._plan(goal)
        self._log("planner", "plan", json.dumps([t.id for t in tasks], ensure_ascii=False))
        outputs: dict[str, str] = {}
        results: list[TaskResult] = []
        for task in tasks:
            result = self._run_task(task, goal, outputs)
            results.append(result)
            if result.status != "accepted":
                return Report("stopped", goal, results, list(self.events))
            outputs[task.id] = result.output
        return Report("completed", goal, results, list(self.events))

    def _plan(self, goal: str) -> list[Task]:
        """Ask for a plan. An invalid graph gets the error fed back, up to plan_retries times."""
        messages = [{"role": "user", "content": f"เป้าหมาย:\n{goal}"}]
        for attempt in range(self.settings.plan_retries + 1):
            raw = self._call(self.planner, PLANNER_SYSTEM, messages)
            try:
                return parse_plan(raw)
            except ProtocolError as exc:
                if attempt == self.settings.plan_retries:
                    raise WorkflowError(f"Planner ให้แผนที่ใช้ไม่ได้: {exc}") from exc
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": f"แผนไม่ถูกต้อง: {exc}. ส่งแผนใหม่เป็น JSON เดียว"}]
        raise WorkflowError("unreachable")

    def _run_task(self, task: Task, goal: str, outputs: dict[str, str]) -> TaskResult:
        context = {dep: outputs[dep] for dep in task.depends_on}
        feedback = ""
        for attempt in range(self.settings.max_retries + 1):
            prompt = self._executor_prompt(goal, task, context, feedback)
            status, output = self._execute(prompt)
            self._log("executor", task.id, output)
            if status == "blocked":
                return TaskResult(task.id, "blocked", output, output)
            passed, reason = self._judge(task, output)
            self._log("harness", task.id, f"pass={passed} {reason}")
            if passed:
                return TaskResult(task.id, "accepted", output, reason)
            feedback = f"ผู้ตรวจไม่ผ่านรอบที่ {attempt + 1}: {reason}. แก้ให้ตรง acceptance"
        return TaskResult(task.id, "rejected", output, reason)

    @staticmethod
    def _executor_prompt(goal: str, task: Task, context: dict[str, str], feedback: str) -> str:
        parts = [f"เป้าหมาย: {goal}", f"งาน {task.id}: {task.title}", f"acceptance: {task.acceptance}"]
        if context:
            parts.append("ผลของงานที่งานนี้พึ่ง:\n" + "\n".join(f"[{k}] {v}" for k, v in context.items()))
        if feedback:
            parts.append(feedback)
        return "\n\n".join(parts)

    def _execute(self, prompt: str) -> tuple[str, str]:
        raw = self._call(self.executor, EXECUTOR_SYSTEM, [{"role": "user", "content": prompt}])
        try:
            return parse_executor(raw)
        except ProtocolError as exc:
            raise WorkflowError(f"Executor ตอบรูปแบบไม่ถูกต้อง: {exc}") from exc

    def _judge(self, task: Task, output: str) -> tuple[bool, str]:
        content = f"acceptance: {task.acceptance}\n\nผลของ Executor:\n{output}"
        raw = self._call(self.judge, HARNESS_JUDGE_SYSTEM, [{"role": "user", "content": content}])
        try:
            return parse_verdict(raw)
        except ProtocolError as exc:
            raise WorkflowError(f"ผู้ตรวจตอบรูปแบบไม่ถูกต้อง: {exc}") from exc

    @staticmethod
    def _call(client: ModelClient, system: str, messages: list[dict[str, str]]) -> str:
        try:
            return client.complete(system, messages)
        except ModelError as exc:
            raise WorkflowError(str(exc)) from exc

    def _log(self, role: str, kind: str, content: str) -> None:
        event = {"ts": round(time.time(), 3), "role": role, "kind": kind, "content": content}
        self.events.append(event)
        if self.transcript is not None:
            self.transcript.parent.mkdir(parents=True, exist_ok=True)
            with self.transcript.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
