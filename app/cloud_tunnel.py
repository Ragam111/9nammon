"""Cloudflare Quick Tunnel manager — stdlib only, no account needed.

Public API:
  start(port, timeout=30.0) -> str   returns https://xxxx.trycloudflare.com
  stop()
  status() -> dict

Security (Rule 24): only tunnels to 127.0.0.1:{port} — never exposes token in URL.
"""
import re
import subprocess
import threading
import time
from typing import Optional

_lock = threading.Lock()
_proc: Optional[subprocess.Popen] = None
_url: Optional[str] = None
_port: Optional[int] = None

_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def start(port: int, timeout: float = 30.0) -> str:
    """Start cloudflared quick tunnel to 127.0.0.1:{port}.

    Returns the public https URL.
    Raises RuntimeError if cloudflared is missing or times out.
    """
    global _proc, _url, _port

    with _lock:
        if _proc is not None and _proc.poll() is None and _url:
            return _url

        _stop_locked()

        try:
            proc = subprocess.Popen(
                ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "cloudflared not found — download from "
                "https://developers.cloudflare.com/cloudflare-one/connections/"
                "connect-apps/install-and-setup/"
            )

        _proc = proc
        _port = port

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if not line:
                proc.wait()
                raise RuntimeError("cloudflared exited before providing tunnel URL")
            m = _URL_RE.search(line)
            if m:
                _url = m.group(0)
                return _url

        proc.terminate()
        raise RuntimeError(f"cloudflared did not provide URL within {timeout}s")


def stop() -> None:
    """Stop the running tunnel (idempotent)."""
    with _lock:
        _stop_locked()


def _stop_locked() -> None:
    """Terminate process; must be called with _lock held."""
    global _proc, _url, _port
    if _proc is not None:
        try:
            _proc.terminate()
            _proc.wait(timeout=5)
        except Exception:
            try:
                _proc.kill()
            except Exception:
                pass
        _proc = None
    _url = None
    _port = None


def status() -> dict:
    """Return current tunnel status."""
    with _lock:
        running = _proc is not None and _proc.poll() is None
        return {
            "running": running,
            "url": _url if running else None,
            "port": _port if running else None,
        }
