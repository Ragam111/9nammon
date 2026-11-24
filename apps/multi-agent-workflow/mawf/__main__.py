"""Command line: python -m mawf "<goal>" [--transcript path] [--workdir path] [--demo].

--demo runs the whole workflow offline with DemoModel, so no API key or network is needed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .demo import DEMO_GOAL, DemoModel
from .files import FileSandbox
from .models import AnthropicClient, ModelClient, ModelError
from .workflow import Harness, WorkflowError

PLANNER_MODEL = "claude-sonnet-5-5"
EXECUTOR_MODEL = "claude-haiku-5-5"
JUDGE_MODEL = "claude-sonnet-5-5"


def build_models(demo: bool) -> tuple[ModelClient, ModelClient, ModelClient]:
    """Return (planner, executor, judge). Demo mode needs no key; otherwise ANTHROPIC_API_KEY must be set."""
    if demo:
        model = DemoModel()
        return model, model, model
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return (AnthropicClient(key, PLANNER_MODEL), AnthropicClient(key, EXECUTOR_MODEL),
            AnthropicClient(key, JUDGE_MODEL))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mawf", description="Harness, Planner and Executor workflow.")
    parser.add_argument("goal", nargs="?", default=None, help="goal text; with --demo it defaults to a sample goal")
    parser.add_argument("--demo", action="store_true", help="run offline with built-in replies, no API key needed")
    parser.add_argument("--transcript", type=Path, default=None)
    parser.add_argument("--workdir", type=Path, default=None,
                        help="enable Executor file tools, confined to this folder (omit = text only)")
    args = parser.parse_args(argv)
    goal = args.goal or (DEMO_GOAL if args.demo else None)
    if not goal:
        parser.error("ต้องระบุ goal หรือใช้ --demo")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Thai output on Windows consoles
    except (AttributeError, ValueError):
        pass
    sandbox = FileSandbox(args.workdir) if args.workdir else None
    try:
        planner, executor, judge = build_models(args.demo)
        harness = Harness(planner, executor, judge, transcript=args.transcript, sandbox=sandbox)
        report = harness.run(goal)
    except (ModelError, WorkflowError) as exc:
        print(f"ผิดพลาด: {exc}", file=sys.stderr)
        return 2
    for result in report.results:
        print(f"[{result.task_id}] {result.status}: {result.output}")
    print(f"\nสถานะ: {'เสร็จ' if report.status == 'completed' else 'หยุดก่อนครบ'}")
    return 0 if report.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
