"""Command-line entry point for the system manager.

Usage::

    python -m sysmanager snapshot            # one diagnosis
    python -m sysmanager snapshot --json     # machine-readable
    python -m sysmanager watch -n 2          # refresh every 2s

The CLI is the first slice of the AI-engine layer: it is what a human runs
today and what the agent controller will call under the hood later.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional

from . import __version__
from .monitor import Analyzer, Report, Severity, collect
from .sysinfo import get_system_info

_COLORS = {
    Severity.OK: "\033[32m",        # green
    Severity.INFO: "\033[36m",      # cyan
    Severity.WARNING: "\033[33m",   # yellow
    Severity.CRITICAL: "\033[31m",  # red
}
_RESET = "\033[0m"


def _fmt_bytes(n: float) -> str:
    step = 1024.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < step:
            return f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} PiB"


def _color(sev: Severity, text: str, use_color: bool) -> str:
    if not use_color:
        return text
    return f"{_COLORS.get(sev, '')}{text}{_RESET}"


def render_report(report: Report, use_color: bool = True) -> str:
    snap = report.snapshot
    lines: list[str] = []
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap.timestamp))
    lines.append(f"System Manager — {snap.hostname}  ({ts}, window {snap.interval:g}s)")
    lines.append(snap.platform)
    lines.append("")

    # Verdict banner first — the headline answer.
    worst = report.worst
    lines.append(_color(worst, f"VERDICT: {report.verdict}", use_color))
    lines.append("")

    # Findings, worst first.
    lines.append("Findings:")
    for f in sorted(report.findings, key=lambda x: x.severity, reverse=True):
        lines.append("  " + _color(f.severity, str(f), use_color))
    lines.append("")

    # Top consumers.
    lines.append("Top processes by CPU:")
    for p in snap.top_by_cpu:
        lines.append(f"  {p.cpu_percent:5.1f}%  pid {p.pid:<7} {p.name}")
    lines.append("Top processes by memory:")
    for p in snap.top_by_memory:
        lines.append(
            f"  {p.memory_percent:5.1f}%  {_fmt_bytes(p.memory_rss):>10}  "
            f"pid {p.pid:<7} {p.name}"
        )
    return "\n".join(lines)


def _run_once(args: argparse.Namespace) -> Report:
    snap = collect(interval=args.interval, top_n=args.top)
    return Analyzer().analyze(snap)


def _cmd_snapshot(args: argparse.Namespace) -> int:
    report = _run_once(args)
    if args.json:
        print(json.dumps(_report_to_dict(report), indent=2))
    else:
        print(render_report(report, use_color=_use_color(args)))
    # Exit code reflects severity so scripts/schedulers can react.
    return min(int(report.worst), 2)


def _cmd_watch(args: argparse.Namespace) -> int:
    use_color = _use_color(args)
    try:
        while True:
            report = _run_once(args)
            if args.json:
                print(json.dumps(_report_to_dict(report)), flush=True)
            else:
                # Clear screen for a live dashboard feel.
                sys.stdout.write("\033[2J\033[H" if use_color else "\n")
                print(render_report(report, use_color=use_color), flush=True)
            if args.count and args.count > 0:
                args.count -= 1
                if args.count == 0:
                    break
    except KeyboardInterrupt:
        print("\nstopped.", file=sys.stderr)
    return 0


def _cmd_sysinfo(args: argparse.Namespace) -> int:
    info = get_system_info()
    if args.json:
        print(json.dumps(info.to_dict(), indent=2, ensure_ascii=False))
        return 0
    c = info.cpu
    print(f"System — {info.hostname}")
    print(f"  OS       : {info.platform}  (Python {info.python})")
    print(f"  CPU      : {c.model}")
    cores = f"{c.physical_cores}P/{c.logical_cores}L" if c.physical_cores else f"{c.logical_cores}L"
    freq = f" @ {c.max_freq_mhz:.0f} MHz" if c.max_freq_mhz else ""
    print(f"             {cores} cores{freq}  [{c.arch}]")
    print(f"  Memory   : {info.memory.total_human}")
    print("  Storage  :")
    for s in info.storage:
        print(f"             {s.mountpoint:<12} {s.total_human:>10}  ({s.fstype})")
    print("  GPU      :")
    if info.gpus:
        for g in info.gpus:
            tag = "compute-capable" if g.compute_capable else "integrated/display-only"
            print(f"             {g.name}  [{tag}]")
    else:
        print("             (none detected)")
    print(f"  Note     : {info.gpu_note}")
    return 0


def _report_to_dict(report: Report) -> dict:
    return {
        "snapshot": report.snapshot.to_dict(),
        "verdict": report.verdict,
        "worst_severity": report.worst.label,
        "findings": [
            {
                "resource": f.resource,
                "severity": f.severity.label,
                "value": f.value,
                "message": f.message,
                "suggestion": f.suggestion,
            }
            for f in report.findings
        ],
    }


def _use_color(args: argparse.Namespace) -> bool:
    if args.no_color:
        return False
    return sys.stdout.isatty()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sysmanager",
        description="windows-package system manager: find the real bottleneck.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "-i", "--interval", type=float, default=1.0,
            help="sampling window in seconds (default: 1.0)",
        )
        p.add_argument(
            "-t", "--top", type=int, default=5,
            help="number of top processes to show (default: 5)",
        )
        p.add_argument("--json", action="store_true", help="output JSON")
        p.add_argument("--no-color", action="store_true", help="disable ANSI colors")

    p_snap = sub.add_parser("snapshot", help="one-shot diagnosis")
    add_common(p_snap)
    p_snap.set_defaults(func=_cmd_snapshot)

    p_watch = sub.add_parser("watch", help="continuous monitoring")
    add_common(p_watch)
    p_watch.add_argument(
        "-n", "--count", type=int, default=0,
        help="stop after N samples (default: 0 = run forever)",
    )
    p_watch.set_defaults(func=_cmd_watch)

    p_info = sub.add_parser("sysinfo", help="static machine spec (CPU/RAM/storage/GPU)")
    p_info.add_argument("--json", action="store_true", help="output JSON")
    p_info.add_argument("--no-color", action="store_true", help="(accepted for consistency)")
    p_info.set_defaults(func=_cmd_sysinfo)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
