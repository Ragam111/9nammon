"""Cloudflare Quick Tunnel manager — stdlib only, no account needed.

Public API:
  start(port, timeout=30.0) -> dict   {"running","url","error","provider","started_at"}
  stop() -> bool                       True if was running
  status() -> dict

Security (Rule 24): only tunnels to 127.0.0.1:{port} — never exposes token in URL.
"""
import re
import shutil
import subprocess
import threading
import time
from typing import Optional

_lock = threading.Lock()
_CF_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

_state: dict = {
    "proc": None,
    "url": None,
    "provider": None,
    "started_at": None,
    "error": None,
}


def _find(binary: str) -> Optional[str]:
    """Return full path of binary if found in PATH, else None."""
    return shutil.which(binary)


def start(port: int, timeout: float = 30.0) -> dict:
    """Start cloudflared quick tunnel to 127.0.0.1:{port} (Rule 24).

    Returns dict: {"running": bool, "url": str|None, "error": str|None,
                   "provider": str|None, "started_at": float|None}
    """
    with _lock:
        # Return cached if already alive
        if _state["proc"] is not None and _state["proc"].poll() is None and _state["url"]:
            return {
                "running": True,
                "url": _state["url"],
                "error": None,
                "provider": _state["provider"],
                "started_at": _state["started_at"],
            }

        binary = _find("cloudflared")
        if binary is None:
            err = "cloudflared not found — download from developers.cloudflare.com"
            _state["error"] = err
            return {"running": False, "url": None, "error": err,
                    "provider": None, "started_at": None}

        _state.update(proc=None, url=None, provider=None, started_at=None, error=None)

        try:
            proc = subprocess.Popen(
                [binary, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            err = str(exc)
            _state["error"] = err
            return {"running": False, "url": None, "error": err,
                    "provider": None, "started_at": None}

        _state["proc"] = proc
        _state["provider"] = "cloudflare"
        _state["started_at"] = time.monotonic()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if not line:
                proc.wait()
                err = "cloudflared exited before providing tunnel URL"
                _state["error"] = err
                return {"running": False, "url": None, "error": err,
                        "provider": None, "started_at": None}
            m = _CF_URL_RE.search(line)
            if m:
                _state["url"] = m.group(0)
                return {
                    "running": True,
                    "url": _state["url"],
                    "error": None,
                    "provider": _state["provider"],
                    "started_at": _state["started_at"],
                }

        proc.terminate()
        err = f"cloudflared did not provide URL within {timeout}s"
        _state["error"] = err
        return {"running": False, "url": None, "error": err,
                "provider": None, "started_at": None}


def stop() -> bool:
    """Stop the running tunnel (idempotent). Returns True if was running."""
    with _lock:
        if _state["proc"] is None or _state["proc"].poll() is not None:
            return False
        try:
            _state["proc"].terminate()
            _state["proc"].wait(timeout=5)
        except Exception:
            try:
                _state["proc"].kill()
            except Exception:
                pass
        _state.update(proc=None, url=None, provider=None, started_at=None, error=None)
        return True


def status() -> dict:
    """Return current tunnel status."""
    with _lock:
        running = _state["proc"] is not None and _state["proc"].poll() is None
        return {
            "running": running,
            "url": _state["url"] if running else None,
            "provider": _state["provider"] if running else None,
            "started_at": _state["started_at"] if running else None,
            "error": _state["error"],
        }
