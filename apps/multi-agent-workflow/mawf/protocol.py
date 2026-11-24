"""JSON messages between the three roles, and validation of the Planner's task graph.

The plan must be a DAG: every dependency exists, no task depends on itself, and there are no cycles.
Anything else is rejected before any Executor runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

MAX_TASKS = 8
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class ProtocolError(ValueError):
    """A reply was not the JSON shape the role must return, or the plan is not a valid graph."""


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    acceptance: str
    depends_on: tuple[str, ...]


def parse_object(raw: str) -> dict[str, Any]:
    text = _FENCE.sub("", raw.strip()).strip()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProtocolError("ตอบเป็น JSON object เดียว ไม่มีข้อความอื่นนอก JSON") from exc
    if not isinstance(data, dict):
        raise ProtocolError("ต้องเป็น JSON object")
    return data


def parse_plan(raw: str) -> list[Task]:
    """Parse {"tasks": [...]} and check it is a valid dependency graph. Returns tasks in a valid run order."""
    data = parse_object(raw)
    items = data.get("tasks")
    if not isinstance(items, list) or not items:
        raise ProtocolError("tasks ต้องเป็นรายการที่ไม่ว่าง")
    if len(items) > MAX_TASKS:
        raise ProtocolError(f"แบ่งได้ไม่เกิน {MAX_TASKS} งาน")
    tasks = [_task(item) for item in items]
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise ProtocolError("id ของงานต้องไม่ซ้ำ")
    return _topological_order(tasks)


def _task(item: Any) -> Task:
    if not isinstance(item, dict):
        raise ProtocolError("แต่ละงานต้องเป็น object")
    fields = {k: str(item.get(k, "")).strip() for k in ("id", "title", "acceptance")}
    if not all(fields.values()):
        raise ProtocolError("แต่ละงานต้องมี id, title และ acceptance")
    deps = item.get("depends_on", [])
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise ProtocolError("depends_on ต้องเป็นรายการ id")
    return Task(fields["id"], fields["title"], fields["acceptance"], tuple(d.strip() for d in deps))


def _topological_order(tasks: list[Task]) -> list[Task]:
    by_id = {t.id: t for t in tasks}
    for task in tasks:
        unknown = [d for d in task.depends_on if d not in by_id]
        if unknown:
            raise ProtocolError(f"งาน {task.id} อ้าง id ที่ไม่มี: {unknown}")
        if task.id in task.depends_on:
            raise ProtocolError(f"งาน {task.id} พึ่งตัวเอง")
    order: list[Task] = []
    done: set[str] = set()
    while len(order) < len(tasks):
        ready = [t for t in tasks if t.id not in done and set(t.depends_on) <= done]
        if not ready:
            raise ProtocolError("ลำดับงานมีวงวน (cycle)")
        for task in ready:
            order.append(task)
            done.add(task.id)
    return order


def parse_executor(raw: str) -> tuple[str, str]:
    """Executor reply: {"status": "done"|"blocked", "output": "..."}."""
    data = parse_object(raw)
    status = data.get("status")
    output = str(data.get("output", "")).strip()
    if status not in ("done", "blocked"):
        raise ProtocolError('status ต้องเป็น "done" หรือ "blocked"')
    if not output:
        raise ProtocolError("output ต้องไม่ว่าง")
    return str(status), output


@dataclass(frozen=True)
class ExecutorStep:
    """Either a tool call to run, or the final status and output of the task."""

    call: dict[str, Any] | None = None
    status: str = ""
    output: str = ""


def parse_executor_step(raw: str) -> ExecutorStep:
    """Executor reply when file tools are enabled: {"tool": {...}} or {"status": ..., "output": ...}."""
    data = parse_object(raw)
    if "tool" in data:
        call = data["tool"]
        if not isinstance(call, dict) or not isinstance(call.get("action"), str):
            raise ProtocolError('tool ต้องเป็น object ที่มี "action"')
        return ExecutorStep(call=call)
    status, output = parse_executor(raw)
    return ExecutorStep(status=status, output=output)


def parse_verdict(raw: str) -> tuple[bool, str]:
    """Harness judge reply: {"pass": true|false, "reason": "..."}."""
    data = parse_object(raw)
    passed = data.get("pass")
    if not isinstance(passed, bool):
        raise ProtocolError('pass ต้องเป็น true หรือ false')
    return passed, str(data.get("reason", "")).strip()
