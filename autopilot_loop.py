"""Autopilot loop: runs the jobs in autopilot_jobs.json every 2 hours on Thai time.

Runs happen at 00:00, 02:00, 04:00 ... 22:00 Thailand time (UTC+7, no daylight saving),
no matter what timezone the PC is set to. Pure standard library, no pip install.

  python autopilot_loop.py            # stay running, run jobs at every even Thai hour
  python autopilot_loop.py --once     # run all enabled jobs now, then exit
  python autopilot_loop.py --list     # show enabled jobs and the next 4 run times

Alternative to keeping a window open (Windows Task Scheduler, every 2 hours):
  schtasks /Create /TN "LCA-Autopilot" /SC HOURLY /MO 2 /ST 00:00 ^
           /TR "python C:\\path\\to\\autopilot_loop.py --once"
(Task Scheduler uses the PC's clock; set Windows to "SE Asia Standard Time" to match Thai time.)

Notes
- The PC must be on and awake. After sleep/hibernate the loop runs a missed slot once, late.
- Logs: logs/autopilot-YYYY-MM-DD.log (Thai date), status of the last run: logs/last_run.json
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ICT = timezone(timedelta(hours=7))          # Thailand: fixed UTC+7
BASE = Path(__file__).resolve().parent
CONFIG = BASE / "autopilot_jobs.json"
LOGS = BASE / "logs"
LOCK = LOGS / ".autopilot.lock"
MAX_LOG_CHARS = 2000                         # keep the tail of each job's output


def now_ict() -> datetime:
    return datetime.now(ICT)


def next_run(after: datetime, interval_h: int) -> datetime:
    """First slot strictly after `after`, on a multiple of interval_h Thai hours."""
    base = after.replace(minute=0, second=0, microsecond=0)
    midnight = base.replace(hour=0)
    slot_hour = (base.hour // interval_h + 1) * interval_h
    return midnight + timedelta(hours=slot_hour)      # slot_hour == 24 rolls to next day


def log(msg: str) -> None:
    LOGS.mkdir(exist_ok=True)
    stamp = now_ict()
    line = f"[{stamp:%Y-%m-%d %H:%M:%S} ICT] {msg}"
    print(line, flush=True)
    with open(LOGS / f"autopilot-{stamp:%Y-%m-%d}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def run_job(job: dict) -> dict:
    cmd = [sys.executable if part == "{python}" else part for part in job["cmd"]]
    cwd = BASE / job.get("cwd", ".")
    started = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=job.get("timeout_sec", 300), env=os.environ.copy())
        ok = r.returncode == 0
        output = (r.stdout + r.stderr).strip()
        status = "OK" if ok else f"FAIL(rc={r.returncode})"
    except subprocess.TimeoutExpired:
        ok, output, status = False, "", f"TIMEOUT({job.get('timeout_sec', 300)}s)"
    except Exception as e:                      # e.g. command not found
        ok, output, status = False, repr(e), "ERROR"
    took = time.time() - started
    log(f"job={job['name']} {status} {took:.1f}s")
    if output:
        log("  output: " + output[-MAX_LOG_CHARS:].replace("\n", "\n          "))
    return {"name": job["name"], "ok": ok, "status": status, "seconds": round(took, 1)}


def run_all(cfg: dict) -> bool:
    LOGS.mkdir(exist_ok=True)
    try:                                         # one runner at a time
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        age = time.time() - LOCK.stat().st_mtime
        if age < 3 * 3600:
            log("previous run still active (lock file present), skipping this slot")
            return True
        log("stale lock file (>3h), taking over")
        LOCK.unlink(missing_ok=True)
        return run_all(cfg)
    try:
        results = [run_job(j) for j in cfg["jobs"] if j.get("enabled", True)]
        summary = {"finished_at": now_ict().isoformat(timespec="seconds"), "jobs": results}
        (LOGS / "last_run.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        bad = [r["name"] for r in results if not r["ok"]]
        log("run finished: " + ("all OK" if not bad else "FAILED: " + ", ".join(bad)))
        return not bad
    finally:
        LOCK.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run enabled jobs now and exit")
    ap.add_argument("--list", action="store_true", help="show jobs and next run times")
    args = ap.parse_args()

    cfg = load_config()
    interval = int(cfg.get("interval_hours", 2))
    if 24 % interval:
        sys.exit("interval_hours must divide 24 evenly (1, 2, 3, 4, 6, 8, 12, 24)")

    if args.list:
        for j in cfg["jobs"]:
            print(f"[{'x' if j.get('enabled', True) else ' '}] {j['name']}: {' '.join(j['cmd'])}")
        t = now_ict()
        print(f"\nnow: {t:%Y-%m-%d %H:%M:%S} ICT")
        for _ in range(4):
            t = next_run(t, interval)
            print(f"next run: {t:%Y-%m-%d %H:%M} ICT")
        return 0

    if args.once:
        return 0 if run_all(cfg) else 1       # non-zero exit = visible failure in Task Scheduler

    log(f"autopilot loop started, every {interval}h on Thai time (Ctrl+C to stop)")
    while True:
        cfg = load_config()                      # re-read so edits apply without restart
        interval = int(cfg.get("interval_hours", interval))
        target = next_run(now_ict(), interval)
        log(f"next run at {target:%Y-%m-%d %H:%M} ICT")
        while now_ict() < target:                # short sleeps survive PC sleep/clock jumps
            time.sleep(min(30, max(1, (target - now_ict()).total_seconds())))
        late = (now_ict() - target).total_seconds()
        if late > 120:
            log(f"running {late / 60:.0f} min late (PC was asleep or busy)")
        run_all(cfg)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("stopped by user")
