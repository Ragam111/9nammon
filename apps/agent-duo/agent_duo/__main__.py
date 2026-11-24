"""Command line: python -m agent_duo "<task>" [--rounds N] [--transcript path]."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .models import AnthropicClient, ModelError
from .orchestrator import Orchestrator, OrchestratorError, Settings

DEFAULT_SCOUT_MODEL = "claude-haiku-5-5"
DEFAULT_CRITIC_MODEL = "claude-sonnet-5-5"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent_duo", description="Scout and Critic research via agent-reach.")
    parser.add_argument("task", help="what to research, in plain words or with a link")
    parser.add_argument("--rounds", type=int, default=6, help="max Critic replies (default 6)")
    parser.add_argument("--bin", default=os.environ.get("AGENT_REACH_BIN", "agent-reach"), help="agent-reach binary")
    parser.add_argument("--scout-model", default=DEFAULT_SCOUT_MODEL)
    parser.add_argument("--critic-model", default=DEFAULT_CRITIC_MODEL)
    parser.add_argument("--transcript", type=Path, default=None, help="append every message to this JSONL file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    try:
        scout = AnthropicClient(key, args.scout_model)
        critic = AnthropicClient(key, args.critic_model)
        settings = Settings(max_rounds=args.rounds, binary=args.bin)
        result = Orchestrator(scout, critic, settings, transcript_path=args.transcript).run(args.task)
    except (ModelError, OrchestratorError) as exc:
        print(f"ผิดพลาด: {exc}", file=sys.stderr)
        return 2
    if result.status != "final":
        print(f"ยังไม่ได้คำตอบสุดท้ายภายใน {args.rounds} รอบ", file=sys.stderr)
        return 1
    print(result.answer)
    print("\nแหล่งอ้างอิง:")
    for url in result.sources:
        print(f"- {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
