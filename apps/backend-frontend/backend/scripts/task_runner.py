"""Run project tasks one batch at a time, with a concurrency cap, timeouts, retries and a free-RAM gate.

Usage (from the backend folder):
  python -m scripts.task_runner scripts/tasks.json --concurrency 1
  python -m scripts.task_runner scripts/tasks.json --only backend-unit,eval-fake --out-dir task-runs/try1

Stdlib only. Each task in the JSON file has: name, cmd (list = run directly, string = run through the shell),
cwd (relative to the tasks file), timeout_s, retries (extra attempts), min_free_mb (RAM needed to start).
Exit code: 0 when every task passed, 1 when any task failed, timed out or was skipped.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_MIN_FREE_MB = 800
DEFAULT_GATE_WAIT_S = 120.0
DEFAULT_TIMEOUT_S = 600.0
MAX_CONCURRENCY = 2
MB = 1024 * 1024


@dataclass(frozen=True)
class Task:
    """One unit of work, already validated and resolved against the tasks file."""

    name: str
    cmd: list[str] | str
    cwd: Path
    timeout_s: float
    retries: int
    min_free_mb: int


@dataclass
class Result:
    """Outcome of one task after all attempts."""

    name: str
    status: str
    exit_code: int | None
    duration_s: float
    attempts: int
    free_mb_at_start: int | None
    log: str
    reason: str = ""


class _MemoryStatus(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 - ctypes layout, must match MEMORYSTATUSEX
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_mb() -> int | None:
    """Return available physical RAM in MB, or None when the platform does not report it."""
    if sys.platform == "win32":
        stat = _MemoryStatus()
        stat.dwLength = ctypes.sizeof(_MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
            return None
        return int(stat.ullAvailPhys // MB)
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // MB)
    except (ValueError, OSError, AttributeError):
        return None


def wait_for_memory(min_free: int, wait_s: float) -> int | None:
    """Poll free RAM until it reaches min_free MB or wait_s seconds pass. Returns the last reading."""
    deadline = time.monotonic() + wait_s
    while True:
        now = free_mb()
        if now is None or now >= min_free or time.monotonic() >= deadline:
            return now
        time.sleep(5)


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _resolve_argv(cmd: list[str] | str) -> list[str] | str:
    """Replace a leading bare 'python' with the interpreter running this runner."""
    if isinstance(cmd, list) and cmd and cmd[0] == "python":
        return [sys.executable, *cmd[1:]]
    return cmd


def load_tasks(path: Path) -> list[Task]:
    """Read and validate the tasks file. Raises ValueError with a readable message on bad input."""
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("tasks")
    if not isinstance(items, list) or not items:
        raise ValueError("tasks file needs a non-empty 'tasks' list")
    names: set[str] = set()
    tasks: list[Task] = []
    for item in items:
        name = str(item["name"])
        if name in names:
            raise ValueError(f"duplicate task name: {name}")
        names.add(name)
        cmd = item["cmd"]
        if not isinstance(cmd, (list, str)) or not cmd:
            raise ValueError(f"task {name}: cmd must be a non-empty list or string")
        tasks.append(
            Task(
                name=name,
                cmd=_resolve_argv(cmd),
                cwd=(path.parent / item.get("cwd", ".")).resolve(),
                timeout_s=float(item.get("timeout_s", DEFAULT_TIMEOUT_S)),
                retries=int(item.get("retries", 0)),
                min_free_mb=int(item.get("min_free_mb", DEFAULT_MIN_FREE_MB)),
            )
        )
    return tasks


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Stop a process and, on Windows, every child it started (npm, node, playwright)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        proc.kill()


def run_once(task: Task, log_path: Path) -> tuple[str, int | None, float]:
    """Run the task once, writing combined output to log_path. Returns (status, exit_code, seconds)."""
    start = time.monotonic()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        try:
            proc = subprocess.Popen(  # noqa: S603 - commands come from the project's own tasks file
                task.cmd,
                cwd=task.cwd,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=isinstance(task.cmd, str),
            )
        except OSError as exc:
            log.write(f"could not start: {exc}\n")
            return "error", None, time.monotonic() - start
        try:
            code = proc.wait(timeout=task.timeout_s)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            proc.wait()
            return "timeout", None, time.monotonic() - start
    return ("passed" if code == 0 else "failed"), code, time.monotonic() - start


def run_task(task: Task, log_dir: Path, gate_wait_s: float) -> Result:
    """Run one task with its retries, after the RAM gate. Never raises for task failures."""
    free = wait_for_memory(task.min_free_mb, gate_wait_s)
    log_path = log_dir / f"{_safe_name(task.name)}.log"
    if free is not None and free < task.min_free_mb:
        reason = f"low memory: {free} MB free, needs {task.min_free_mb} MB"
        return Result(task.name, "skipped", None, 0.0, 0, free, str(log_path), reason)
    total = 0.0
    status, code, attempts = "failed", None, 0
    for attempts in range(1, task.retries + 2):
        status, code, seconds = run_once(task, log_path)
        total += seconds
        if status == "passed":
            break
    return Result(task.name, status, code, round(total, 2), attempts, free, str(log_path))


def run_all(tasks: list[Task], concurrency: int, log_dir: Path, gate_wait_s: float) -> list[Result]:
    """Run tasks with at most `concurrency` at once. Results come back in the input order."""
    if not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ValueError(f"concurrency must be 1..{MAX_CONCURRENCY}")
    with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run_task, t, log_dir, gate_wait_s): t.name for t in tasks}
        done = {futures[f]: f.result() for f in cf.as_completed(futures)}
    return [done[t.name] for t in tasks]


def build_report(results: list[Result], concurrency: int, wall_s: float) -> dict[str, Any]:
    """Summarise results for the JSON report."""
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {
        "concurrency": concurrency,
        "wall_s": round(wall_s, 2),
        "free_mb_end": free_mb(),
        "counts": counts,
        "results": [asdict(r) for r in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tasks_file", type=Path)
    parser.add_argument("--concurrency", type=int, default=1, help=f"1..{MAX_CONCURRENCY}, default 1")
    parser.add_argument("--only", default="", help="comma-separated task names to run")
    parser.add_argument("--gate-wait-s", type=float, default=DEFAULT_GATE_WAIT_S)
    parser.add_argument("--out-dir", type=Path, default=Path("task-runs") / time.strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args(argv)

    tasks = load_tasks(args.tasks_file)
    wanted = {n for n in args.only.split(",") if n}
    if wanted:
        tasks = [t for t in tasks if t.name in wanted]
        if not tasks:
            raise SystemExit(f"no tasks match --only {args.only}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    results = run_all(tasks, args.concurrency, args.out_dir, args.gate_wait_s)
    report = build_report(results, args.concurrency, time.monotonic() - start)
    (args.out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        print(f"{r.status:8} {r.name:20} {r.duration_s:8.1f}s  attempts={r.attempts}  {r.reason}")
    print(json.dumps({"wall_s": report["wall_s"], "counts": report["counts"]}, ensure_ascii=False))
    return 0 if all(r.status == "passed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
