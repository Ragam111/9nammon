"""Command line: python -m mawf "<goal>" [--transcript path]."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .models import AnthropicClient, ModelError
from .workflow import Harness, WorkflowError

PLANNER_MODEL = "claude-sonnet-5-5"
EXECUTOR_MODEL = "claude-haiku-5-5"
JUDGE_MODEL = "claude-sonnet-5-5"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mawf", description="Harness, Planner and Executor workflow.")
    parser.add_argument("goal")
    parser.add_argument("--transcript", type=Path, default=None)
    args = parser.parse_args(argv)
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    try:
        harness = Harness(AnthropicClient(key, PLANNER_MODEL), AnthropicClient(key, EXECUTOR_MODEL),
                          AnthropicClient(key, JUDGE_MODEL), transcript=args.transcript)
        report = harness.run(args.goal)
    except (ModelError, WorkflowError) as exc:
        print(f"ผิดพลาด: {exc}", file=sys.stderr)
        return 2
    for result in report.results:
        print(f"[{result.task_id}] {result.status}: {result.output}")
    print(f"\nสถานะ: {'เสร็จ' if report.status == 'completed' else 'หยุดก่อนครบ'}")
    return 0 if report.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
