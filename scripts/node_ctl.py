#!/usr/bin/env python3
"""
node_ctl.py - control the second LCA machine over SSH (stdlib only).

Run on THIS PC after docs/REMOTE_NODE.md owner steps are done.
Subcommands: status, deploy, rollback, start, stop, restart, logs, pull-model.

Safety:
- subprocess with argument lists only (never shell=True)
- every value placed in a remote command is validated first
- never reads or prints secrets; all output passes through redact()
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_HOST = "lca-node"
DEFAULT_REPO = "C:/lca/repo"
REMOTE_INBOX = "C:/lca/inbox"
REMOTE_LOGS = "C:/lca/logs"
REMOTE_PID = "C:/lca/server.pid"
TASK_NAME = "LCA Server"
PORT = 8420
ALLOWED_MODELS = ("qwen2.5-coder:0.5b", "qwen2.5-coder:1.5b", "qwen2.5:1.5b")

SSH_TIMEOUT = 30
SCP_TIMEOUT = 600
PULL_TIMEOUT = 3600

_HOST_RE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*@)?[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_PATH_RE = re.compile(r"^[A-Za-z]:/[A-Za-z0-9_./-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REDACT = [
    re.compile(r"(?i)(lca_token\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(x-auth-token\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(\"?token\"?\s*[=:]\s*\"?)[^\s\",}]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


class NodeCtlError(Exception):
    """User-facing error with a Thai message."""


# ---------- validation ----------

def validate_host(host: str) -> str:
    """Accept ssh alias, hostname, IPv4 or user@host. Reject shell metacharacters."""
    if not isinstance(host, str) or len(host) > 253 or not _HOST_RE.match(host):
        raise NodeCtlError(f"ชื่อเครื่องไม่ถูกต้อง: {host!r} (ใช้ได้แค่ a-z 0-9 . - _ และ @)")
    return host


def validate_model(name: str) -> str:
    """Only models in the allowlist may be pulled."""
    if name not in ALLOWED_MODELS:
        raise NodeCtlError(f"โมเดลไม่อยู่ในรายการที่อนุญาต: {name!r} ใช้ได้: {', '.join(ALLOWED_MODELS)}")
    return name


def validate_remote_path(path: str) -> str:
    """Absolute Windows path on a drive, no '..', no spaces/quotes/metacharacters."""
    norm = (path or "").replace("\\", "/")
    if not _PATH_RE.match(norm) or ".." in norm.split("/"):
        raise NodeCtlError(f"path ไม่ถูกต้อง: {path!r} (ต้องเป็นเช่น C:/lca/repo ห้ามมี .. หรือช่องว่าง)")
    return norm


def validate_lines(n: int) -> int:
    if not isinstance(n, int) or not 1 <= n <= 5000:
        raise NodeCtlError("จำนวนบรรทัดต้องอยู่ระหว่าง 1 ถึง 5000")
    return n


def validate_sha(sha: str) -> str:
    if not _SHA_RE.match(sha or ""):
        raise NodeCtlError(f"commit sha ไม่ถูกต้อง: {sha!r}")
    return sha


def redact(text: str) -> str:
    """Mask anything that looks like a token or private key."""
    for rx in _REDACT:
        text = rx.sub(lambda m: (m.group(1) if m.groups() else "") + "***", text)
    return text


# ---------- process helpers ----------

def ssh_cmd(host: str, remote: str) -> list[str]:
    """Build an ssh argument list. Remote side runs PowerShell (DefaultShell)."""
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "--", validate_host(host), remote]


def run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run without a shell; convert failures into Thai NodeCtlError."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, shell=False,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise NodeCtlError(f"หมดเวลา {timeout} วินาที: {cmd[0]} ไม่ตอบ (ตรวจสาย LAN และเครื่องที่ 2)")
    except FileNotFoundError:
        raise NodeCtlError(f"ไม่พบโปรแกรม {cmd[0]} (ติดตั้ง OpenSSH Client / git ก่อน)")


def remote(host: str, script: str, timeout: int = SSH_TIMEOUT) -> str:
    """Run a PowerShell snippet on the node; raise on non-zero exit."""
    res = run(ssh_cmd(host, script), timeout)
    if res.returncode != 0:
        msg = redact((res.stderr or res.stdout or "").strip())[:500]
        raise NodeCtlError(f"คำสั่งบนเครื่องที่ 2 ล้มเหลว (rc={res.returncode}): {msg}")
    return res.stdout


# ---------- subcommands ----------

def remote_health(host: str, port: int = PORT) -> dict[str, Any] | None:
    """GET /api/health from the node itself (no token needed)."""
    url = f"http://127.0.0.1:{int(port)}/api/health"
    res = run(ssh_cmd(host, f"curl.exe -s -m 5 {url}"), SSH_TIMEOUT)
    if res.returncode != 0:
        return None
    try:
        data = json.loads(res.stdout or "")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def cmd_status(host: str) -> dict[str, Any]:
    """ssh reachability, health, free RAM, ollama models."""
    res = run(ssh_cmd(host, "hostname"), SSH_TIMEOUT)
    if res.returncode != 0:
        return {"ssh": False, "error": "เชื่อม ssh ไม่ได้ (ตรวจสาย, IP, key และ sshd บนเครื่องที่ 2)"}
    status: dict[str, Any] = {"ssh": True, "hostname": res.stdout.strip()}
    status["health"] = remote_health(host)
    ram = run(ssh_cmd(host, "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"),
              SSH_TIMEOUT)
    try:
        status["ram_free_mb"] = int(ram.stdout.strip()) // 1024
    except ValueError:
        status["ram_free_mb"] = None
    oll = run(ssh_cmd(host, "ollama list"), SSH_TIMEOUT)
    status["ollama"] = oll.stdout.strip() if oll.returncode == 0 else "ollama ไม่ตอบ"
    return status


def _deploy_script(repo: str, bundle: str, sha: str) -> str:
    """PowerShell: init repo if missing, fetch bundle, detached checkout (no reset)."""
    return (
        f"$r='{repo}'; $b='{bundle}'; "
        "if (-not (Test-Path ($r + '/.git'))) { git init -q $r }; "
        "$prev = git -C $r rev-parse --verify -q HEAD; "
        "git -C $r fetch -q $b HEAD; if ($LASTEXITCODE) { exit 3 }; "
        f"git -C $r checkout --detach {sha}; if ($LASTEXITCODE) {{ exit 4 }}; "
        "'PREV=' + $prev; 'DEPLOYED=' + (git -C $r rev-parse HEAD); "
        "Remove-Item -LiteralPath $b -ErrorAction SilentlyContinue"
    )


def _local_sha(repo_dir: Path) -> str:
    res = run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], 30)
    if res.returncode != 0:
        raise NodeCtlError("อ่าน commit ปัจจุบันไม่ได้ (ต้องรันใน git repo)")
    return validate_sha(res.stdout.strip())


def cmd_deploy(host: str, repo: str, repo_dir: Path) -> dict[str, Any]:
    """git bundle of HEAD -> scp -> fetch + checkout on the node. No internet."""
    repo = validate_remote_path(repo)
    sha = _local_sha(repo_dir)
    tmp = Path(tempfile.mkdtemp(prefix="lca-bundle-"))
    bundle = tmp / f"lca-{sha}.bundle"
    try:
        res = run(["git", "-C", str(repo_dir), "bundle", "create", str(bundle), "HEAD"], 300)
        if res.returncode != 0:
            raise NodeCtlError("สร้าง git bundle ไม่สำเร็จ")
        target = f"{REMOTE_INBOX}/{bundle.name}"
        res = run(["scp", "-q", "-o", "BatchMode=yes", "--", str(bundle),
                   f"{validate_host(host)}:{target}"], SCP_TIMEOUT)
        if res.returncode != 0:
            raise NodeCtlError("ส่งไฟล์ bundle ไปเครื่องที่ 2 ไม่สำเร็จ (scp)")
        out = remote(host, _deploy_script(repo, target, sha), 300)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if info.get("DEPLOYED", "").strip() != sha:
        raise NodeCtlError("checkout บนเครื่องที่ 2 ไม่ตรงกับ commit ที่ส่งไป")
    return {"deployed": sha, "previous": info.get("PREV", "").strip() or None,
            "next": "รัน restart แล้ว status เพื่อตรวจ health"}


def cmd_rollback(host: str, repo: str, sha: str) -> dict[str, Any]:
    """Detached checkout of an earlier sha that already exists on the node."""
    repo, sha = validate_remote_path(repo), validate_sha(sha)
    remote(host, f"git -C '{repo}' checkout --detach {sha}; if ($LASTEXITCODE) {{ exit 4 }}")
    return {"checked_out": sha, "next": "รัน restart"}


def cmd_start(host: str) -> dict[str, Any]:
    remote(host, f"Start-ScheduledTask -TaskName '{TASK_NAME}'")
    return {"started": TASK_NAME}


def cmd_stop(host: str) -> dict[str, Any]:
    """Stop only the PID written by run-server.ps1, then end the task."""
    script = (
        f"$f='{REMOTE_PID}'; if (Test-Path $f) {{ "
        "$p=[int](Get-Content -LiteralPath $f -TotalCount 1); "
        "$proc=Get-Process -Id $p -ErrorAction SilentlyContinue; "
        "if ($proc -and $proc.ProcessName -like 'python*') { Stop-Process -Id $p -Force }; "
        "Remove-Item -LiteralPath $f -ErrorAction SilentlyContinue }; "
        f"Stop-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue"
    )
    remote(host, script)
    return {"stopped": TASK_NAME}


def _wait_health(host: str, want_up: bool, wait_s: int) -> bool:
    deadline = time.monotonic() + wait_s
    while True:
        h = remote_health(host)
        if bool(h and h.get("ok")) == want_up:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(2)


def cmd_restart(host: str, wait_s: int = 60) -> dict[str, Any]:
    """stop -> wait until health is down -> start -> wait until health is up."""
    cmd_stop(host)
    if not _wait_health(host, want_up=False, wait_s=min(wait_s, 20)):
        raise NodeCtlError("server ยังตอบ health หลัง stop (อาจมีโปรเซสอื่นใช้พอร์ต 8420)")
    cmd_start(host)
    ok = _wait_health(host, want_up=True, wait_s=wait_s)
    if not ok:
        raise NodeCtlError(f"server ไม่ขึ้นภายใน {wait_s} วินาที ดู logs")
    return {"ok": True, "restarted": TASK_NAME}


def cmd_logs(host: str, lines: int = 200) -> str:
    n = validate_lines(lines)
    script = (
        f"$f = Get-ChildItem -Path '{REMOTE_LOGS}' -Filter 'server-*.log' "
        "-ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1; "
        f"if ($f) {{ Get-Content -LiteralPath $f.FullName -Tail {n} }} else {{ 'no log yet' }}"
    )
    return remote(host, script)


def cmd_pull_model(host: str, name: str) -> str:
    """ollama pull on the node (needs internet on the node)."""
    return remote(host, f"ollama pull {validate_model(name)}", PULL_TIMEOUT)


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ควบคุมเครื่อง LCA เครื่องที่ 2 ผ่าน ssh")
    p.add_argument("--host", default=DEFAULT_HOST, help="ssh alias (ค่าเริ่มต้น lca-node)")
    p.add_argument("--remote-repo", default=DEFAULT_REPO)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "deploy", "start", "stop", "restart"):
        sub.add_parser(name)
    sub.add_parser("rollback").add_argument("sha")
    sub.add_parser("logs").add_argument("--lines", type=int, default=200)
    sub.add_parser("pull-model").add_argument("name")
    return p


def dispatch(args: argparse.Namespace) -> Any:
    host = validate_host(args.host)
    table = {
        "status": lambda: cmd_status(host),
        "deploy": lambda: cmd_deploy(host, args.remote_repo, Path.cwd()),
        "rollback": lambda: cmd_rollback(host, args.remote_repo, args.sha),
        "start": lambda: cmd_start(host),
        "stop": lambda: cmd_stop(host),
        "restart": lambda: cmd_restart(host),
        "logs": lambda: cmd_logs(host, args.lines),
        "pull-model": lambda: cmd_pull_model(host, validate_model(args.name)),
    }
    return table[args.cmd]()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # never crash on non-UTF-8 consoles
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        result = dispatch(args)
    except NodeCtlError as e:
        print(f"ผิดพลาด: {redact(str(e))}", file=sys.stderr)
        return 2
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
    print(redact(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
