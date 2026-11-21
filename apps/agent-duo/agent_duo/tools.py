"""Read-only bridge from the agents to the agent-reach CLI.

The model never writes a shell string. It names a channel, an action and a target, and this module
builds an argv list (no shell). Only allowlisted read actions run. Paid transcription and any
write action are refused.
"""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

ALLOWED_ACTIONS: dict[str, frozenset[str]] = {
    "youtube": frozenset({"read", "search", "subtitle"}),  # "transcribe" is paid (Whisper quota): not allowed
    "bilibili": frozenset({"read", "search", "subtitle", "hot"}),
    "web": frozenset({"read", "search"}),
    "github": frozenset({"read", "search"}),
    "v2ex": frozenset({"hot", "node", "read", "user"}),
}
ACTIONS_WITH_LIMIT = frozenset({"search", "hot", "node"})
ACTIONS_WITHOUT_TARGET = frozenset({"hot"})
MAX_LIMIT = 10
MAX_RESULT_CHARS = 6000
TIMEOUT_S = 90.0
URL_PATTERN = re.compile(r"https?://[^\s\"'<>\]\\]+")  # backslash excluded: JSON escapes must not stick to a URL

Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


class ToolError(ValueError):
    """The model asked for something outside the allowlist, or the call is malformed."""


@dataclass(frozen=True)
class ToolCall:
    channel: str
    action: str
    target: str = ""
    limit: int = 5

    def validate(self) -> None:
        actions = ALLOWED_ACTIONS.get(self.channel)
        if actions is None:
            raise ToolError(f"ช่องทาง {self.channel!r} ไม่ได้รับอนุญาต")
        if self.action not in actions:
            raise ToolError(f"คำสั่ง {self.channel} {self.action!r} ไม่ได้รับอนุญาต (อ่านอย่างเดียวเท่านั้น)")
        if self.action not in ACTIONS_WITHOUT_TARGET and not self.target.strip():
            raise ToolError("ต้องระบุ target")
        if self.target.startswith("-"):
            raise ToolError("target ห้ามขึ้นต้นด้วย '-'")
        if self.channel == "web" and self.action == "read":
            _refuse_private_host(self.target)
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ToolError(f"limit ต้องอยู่ระหว่าง 1 ถึง {MAX_LIMIT}")

    def argv(self, binary: str) -> list[str]:
        self.validate()
        args = [binary, self.channel, self.action]
        if self.target.strip():
            args.append(self.target.strip())
        if self.action in ACTIONS_WITH_LIMIT:
            args += ["--limit", str(self.limit)]
        return args


def _refuse_private_host(target: str) -> None:
    """Web reads may only go to public http(s) hosts: no localhost, LAN, link-local or file URLs."""
    parts = urlsplit(target.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("web read ใช้ได้เฉพาะลิงก์ http(s) ที่มี host")
    host = parts.hostname
    if host == "localhost" or host.endswith(".local"):
        raise ToolError("ห้ามอ่านเครื่องภายในเครือข่าย")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
        raise ToolError("ห้ามอ่านเครื่องภายในเครือข่าย")


def call_from_dict(raw: dict[str, Any]) -> ToolCall:
    """Turn the model's JSON `call` object into a ToolCall, rejecting bad types."""
    try:
        limit = int(raw.get("limit", 5))
    except (TypeError, ValueError) as exc:
        raise ToolError("limit ต้องเป็นตัวเลข") from exc
    return ToolCall(
        channel=str(raw.get("channel", "")).strip(),
        action=str(raw.get("action", "")).strip(),
        target=str(raw.get("target", "")).strip(),
        limit=limit,
    )


def default_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv list, no shell, fixed binary chosen by the operator
        argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
    )


def clip(data: Any, ok: bool) -> dict[str, Any]:
    """Keep the model's context small: the full JSON is cut at MAX_RESULT_CHARS."""
    text = json.dumps(data, ensure_ascii=False)
    return {"ok": ok, "truncated": len(text) > MAX_RESULT_CHARS, "text": text[:MAX_RESULT_CHARS]}


def run_call(call: ToolCall, binary: str = "agent-reach", runner: Runner = default_runner) -> dict[str, Any]:
    """Run one allowlisted call. Every failure comes back as {"ok": False, "error": ...}, never as an exception."""
    try:
        argv = call.argv(binary)
    except ToolError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        proc = runner(argv, TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "หมดเวลาการเรียก agent-reach"}
    except OSError as exc:
        return {"ok": False, "error": f"เรียก agent-reach ไม่ได้: {exc}"}
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return {"ok": False, "error": "ผลลัพธ์ของ agent-reach ไม่ใช่ JSON", "stderr": proc.stderr[-300:]}
    ok = proc.returncode == 0 and not (isinstance(data, dict) and data.get("ok") is False)
    return clip(data, ok)


def _trim(url: str) -> str:
    """Drop sentence punctuation, and a closing bracket only when it has no opening partner in the URL."""
    url = url.rstrip(".,;:!?")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url


def urls_in(result: dict[str, Any]) -> set[str]:
    """Every URL that appears in a tool result. Only these may be cited as sources."""
    return {_trim(m) for m in URL_PATTERN.findall(json.dumps(result, ensure_ascii=False))}
