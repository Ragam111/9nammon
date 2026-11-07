"""cloud_tunnel.py — Free self-hosted tunnel exposing LCA server to the internet.

Cloudflare Quick Tunnel: free, no account, no port forwarding.
Requires cloudflared binary on PATH.
  Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

Usage:
    from app import cloud_tunnel
    result = cloud_tunnel.start(8420)   # {"url": "https://xxxx.trycloudflare.com", ...}
    cloud_tunnel.stop()

Architecture:
  [ Browser / Mobile ]
       |
  [ Cloudflare Edge ]
       |
  [ cloudflared (subprocess on this laptop) ]
       |
  [ LCA Server 127.0.0.1:{port} ]
"""

import re
import shutil
import subprocess
import threading
import time
from typing import Optional

_lock = threading.Lock()
_state: dict = {
    "proc": None,
    "url": None,
    "provider": None,
    "started_at": None,
    "error": None,
}

# matches https://xxxx-xxxx.trycloudflare.com in cloudflared stderr
_CF_URL_RE = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")


def _find(name: str) -> Optional[str]:
    """Return full path of binary (checks name and name.exe)."""
    return shutil.which(name) or shutil.which(name + ".exe")


def start(port: int, timeout: float = 30.0) -> dict:
    """Start a Cloudflare Quick Tunnel exposing http://127.0.0.1:{port}.

    Returns:
        {"url": str, "provider": "cloudflare", "error": None}  on success
        {"url": None, "provider": None, "error": str}           on failure

    Security: only tunnels to 127.0.0.1 — never exposes the token or
    any other local service.
    """
    with _lock:
        proc = _state.get("proc")
        if proc and proc.poll() is None:
            return {"url": _state["url"], "provider": _state["provider"], "error": None}

        binary = _find("cloudflared")
        if not binary:
            return {
                "url": None,
                "provider": None,
                "error": (
                    "cloudflared not found — download free binary from "
                    "https://developers.cloudflare.com/cloudflare-one/"
                    "connections/connect-networks/downloads/"
                ),
            }
        return _start_cloudflared(binary, port, timeout)


def _start_cloudflared(binary: str, port: int, timeout: float) -> dict:
    try:
        proc = subprocess.Popen(
            [binary, "tunnel", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        url = _read_cloudflared_url(proc, timeout)
        if url:
            _state.update(
                proc=proc, url=url, provider="cloudflare",
                started_at=time.time(), error=None,
            )
            return {"url": url, "provider": "cloudflare", "error": None}
        proc.terminate()
        return {
            "url": None, "provider": None,
            "error": "cloudflared launched but public URL not found within timeout",
        }
    except Exception as exc:
        return {"url": None, "provider": None, "error": str(exc)}


def _read_cloudflared_url(proc: subprocess.Popen, timeout: float) -> Optional[str]:
    """Stream cloudflared stderr until the trycloudflare.com URL appears."""
    deadline = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            line = proc.stderr.readline()
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            buf += line
            m = _CF_URL_RE.search(buf)
            if m:
                return m.group(0)
        except Exception:
            break
        time.sleep(0.05)
    return None


def stop() -> bool:
    """Terminate the running tunnel process.

    Returns:
        True  — a tunnel was running and has been terminated.
        False — no tunnel was running.
    """
    with _lock:
        proc = _state.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            _state.update(
                proc=None, url=None, provider=None,
                started_at=None, error=None,
            )
            return True
        return False


def status() -> dict:
    """Return the current tunnel state.

    Keys: running (bool), url, provider, started_at (float|None), error.
    """
    with _lock:
        proc = _state.get("proc")
        running = bool(proc and proc.poll() is None)
        return {
            "running": running,
            "url": _state["url"] if running else None,
            "provider": _state["provider"] if running else None,
            "started_at": _state["started_at"] if running else None,
            "error": _state.get("error"),
        }
