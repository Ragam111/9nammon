"""Four cooperating agents (PM, Dev, QA, Ops) coordinated through a file queue.

Stdlib only. Tasks are JSON files in state/todo, state/doing, state/done and
state/failed. A worker claims a task by renaming it from todo/ into doing/
(os.replace is atomic on one filesystem, so two workers cannot take the same task).

Guardrails:
- Agents only write text. Nothing is applied, committed, pushed or merged here.
- A dev proposal that names a forbidden path (.env, .git, secrets, keys) is rejected.
- The run stops at the deadline, when the queue is empty, or after the given hours.

Usage:
  python agents_team.py enqueue pm "goal text"    # PM splits the goal into dev/qa/ops tasks
  python agents_team.py run --hours 8              # work the queue until empty or 8 h
  python agents_team.py run --hours 0.1 --dry      # same flow, no model calls
  python agents_team.py status
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(os.environ.get("AGENTS_STATE", Path(__file__).resolve().parent / "state"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("LCA_MODEL", "qwen2.5:1.5b")
NUM_CTX = int(os.environ.get("LCA_NUM_CTX", "4096"))
LLM_TIMEOUT = int(os.environ.get("AGENTS_LLM_TIMEOUT", "300"))
CONTEXT_CHARS = 4000                      # keep prompts inside a small num_ctx
ROLES = ("pm", "dev", "qa", "ops")
SUBROLES = ("dev", "qa", "ops")
MAX_SUBTASKS = 4
STATES = ("todo", "doing", "done", "failed")
FORBIDDEN = re.compile(r"(^|/)(\.env|\.git)(/|$)|secret|\.pem$|\.key$", re.IGNORECASE)

PROMPTS = {
    "pm": (
        "You are the PM. Split the goal into at most 4 subtasks for roles dev, qa, ops. "
        "Reply ONLY with a JSON list of objects: {\"role\": \"dev|qa|ops\", \"goal\": \"...\"}."
    ),
    "dev": (
        "You are the developer. Propose the smallest code change for the goal. "
        "For each file write a line 'FILE: <path>' followed by a unified diff or the full new content. "
        "Never touch .env, .git or secret or key files."
    ),
    "qa": (
        "You are QA. Review the developer proposal in CONTEXT. Start your reply with PASS or FAIL, "
        "then list test cases and risks."
    ),
    "ops": (
        "You are Ops. List the exact commands a human should run to verify this change. "
        "Do not claim that any command was run."
    ),
}
DRY_REPLIES = {
    "pm": json.dumps([{"role": r, "goal": "(dry run)"} for r in SUBROLES]),
    "dev": "FILE: notes.md\n(dry run: no model called)",
    "qa": "PASS\n(dry run)",
    "ops": "(dry run)",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state_dir(state: str) -> Path:
    folder = BASE / state
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def enqueue(role: str, goal: str, root: str | None = None) -> dict:
    """Write a new todo task. The first task of a goal becomes the root of its tree."""
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    task_id = f"{time.time_ns()}-{os.urandom(3).hex()}"
    task = {"id": task_id, "role": role, "goal": goal, "root": root or task_id, "created": now()}
    path = state_dir("todo") / f"{task_id}.json"
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    return task


def claim_next() -> Path | None:
    """Move the oldest todo task into doing/. Returns None when nothing is left."""
    for path in sorted(state_dir("todo").glob("*.json")):
        try:
            os.replace(path, state_dir("doing") / path.name)
        except FileNotFoundError:
            continue                       # another worker claimed it first
        return state_dir("doing") / path.name
    return None


def finish(doing: Path, state: str, result: dict) -> None:
    task = json.loads(doing.read_text(encoding="utf-8"))
    task.update(result, status=state, finished=now())
    (state_dir(state) / doing.name).write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    doing.unlink(missing_ok=True)


def llm(prompt: str, role: str, dry: bool) -> str:
    """Call the local Ollama model. Dry runs return a canned reply instead."""
    if dry:
        return DRY_REPLIES[role]
    body = json.dumps({
        "model": MODEL,
        "stream": False,
        "options": {"num_ctx": NUM_CTX},
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
        return json.load(resp)["message"]["content"]


def parse_subtasks(text: str) -> list[dict]:
    """Read the PM's JSON list. Anything malformed raises ValueError."""
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("PM reply has no JSON list")
    items = json.loads(text[start:end + 1])
    if not isinstance(items, list) or len(items) > MAX_SUBTASKS:
        raise ValueError(f"PM must return a list of at most {MAX_SUBTASKS} items")
    subtasks = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"bad subtask: {item!r}")
        role, goal = item.get("role"), item.get("goal")
        if role not in SUBROLES or not isinstance(goal, str) or not goal.strip():
            raise ValueError(f"bad subtask: {item!r}")
        subtasks.append({"role": role, "goal": goal.strip()})
    return subtasks


def check_files(reply: str) -> None:
    """Reject a dev proposal that names a forbidden path."""
    for line in reply.splitlines():
        if line.startswith("FILE:"):
            path = line[len("FILE:"):].strip().replace("\\", "/")
            if FORBIDDEN.search(path):
                raise PermissionError(f"forbidden file in proposal: {path}")


def context_for(root: str) -> str:
    """Earlier non-PM replies for the same goal, newest last, trimmed to CONTEXT_CHARS."""
    parts = []
    for path in sorted(state_dir("done").glob("*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        if task.get("root") == root and task.get("role") != "pm":
            parts.append(f"[{task['role']}] {task.get('reply', '')}")
    return "\n\n".join(parts)[-CONTEXT_CHARS:]


def handle(task: dict, dry: bool) -> dict:
    role = task["role"]
    context = context_for(task["root"])
    prompt = f"{PROMPTS[role]}\n\nGOAL:\n{task['goal']}\n\nCONTEXT:\n{context or '(none)'}"
    reply = llm(prompt, role, dry)
    if role == "pm":
        subtasks = parse_subtasks(reply)
        for sub in subtasks:
            enqueue(sub["role"], sub["goal"], root=task["root"])
        return {"reply": reply, "subtasks": len(subtasks)}
    if role == "dev":
        check_files(reply)
    return {"reply": reply}


def run(hours: float, dry: bool) -> dict:
    deadline = time.monotonic() + hours * 3600
    stats = {"done": 0, "failed": 0}
    while time.monotonic() < deadline:
        doing = claim_next()
        if doing is None:
            break
        task = json.loads(doing.read_text(encoding="utf-8"))
        try:
            finish(doing, "done", handle(task, dry))
            stats["done"] += 1
        except (ValueError, OSError, KeyError) as exc:
            finish(doing, "failed", {"error": f"{type(exc).__name__}: {exc}"})
            stats["failed"] += 1
    return stats


def status() -> dict:
    return {state: len(list(state_dir(state).glob("*.json"))) for state in STATES}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    en = sub.add_parser("enqueue")
    en.add_argument("role", choices=ROLES)
    en.add_argument("goal")
    rn = sub.add_parser("run")
    rn.add_argument("--hours", type=float, default=8.0)
    rn.add_argument("--dry", action="store_true")
    rn.add_argument("--goal", help="queue a PM task for this goal before running")
    sub.add_parser("status")
    args = ap.parse_args(argv)

    if args.cmd == "enqueue":
        task = enqueue(args.role, args.goal)
        print(f"queued {task['id']} ({task['role']})")
    elif args.cmd == "run":
        if args.goal:
            enqueue("pm", args.goal)
        print(json.dumps(run(args.hours, args.dry)))
    else:
        print(json.dumps(status()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
