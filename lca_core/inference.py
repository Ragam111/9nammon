"""L1 — thin Ollama client for localhost:11434.

Streaming reads are capped at 32KB. Model downloads are refused.
Network stays off unless ``allow_network=True`` or a transport is injected,
so tests never touch a socket by accident. An unreachable daemon returns
status ``ollama offline`` instead of raising.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlparse

from lca_core.constants import CHUNK_BYTES, OLLAMA_TIMEOUT_S, OLLAMA_URL
from lca_core.security import is_loopback_ip

__all__ = [
    "InferenceResult",
    "OllamaClient",
    "OllamaOffline",
    "StreamResult",
]


class OllamaOffline(Exception):
    def __init__(self, detail: str = "ollama offline"):
        super().__init__(detail)
        self.detail = detail


@dataclass
class InferenceResult:
    status: str
    text: str = ""
    truncated: bool = False


@dataclass
class StreamResult:
    status: str
    chunks: Iterator[bytes]


class OllamaClient:
    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        *,
        timeout: float = OLLAMA_TIMEOUT_S,
        transport=None,
        allow_network: bool = False,
        max_bytes: int = 1024 * 1024,
    ):
        self.base_url = _loopback_base(base_url)
        self.timeout = float(timeout)
        self.transport = transport
        self.allow_network = bool(allow_network)
        self.max_bytes = int(max_bytes)

    def health(self) -> dict:
        try:
            response = self._open("GET", "/api/version", None, min(self.timeout, 2.0))
        except OllamaOffline:
            return {"status": "ollama offline"}
        close = getattr(response, "close", None)
        if close is not None:
            close()
        return {"status": "up"}

    def chat(self, model: str, messages: list, *, timeout: float | None = None) -> InferenceResult:
        """POST /api/chat with stream false. Never calls /api/pull."""
        try:
            response = self._open(
                "POST",
                "/api/chat",
                {"model": model, "messages": list(messages), "stream": False},
                self.timeout if timeout is None else float(timeout),
            )
        except OllamaOffline:
            return InferenceResult(status="ollama offline", text="")
        raw, truncated = _read_capped(response, self.max_bytes)
        text = _chat_text(raw)
        return InferenceResult(status="ok", text=text, truncated=truncated)

    def stream(self, model: str, messages: list, *, timeout: float | None = None) -> StreamResult:
        """POST /api/chat with stream true. Each yielded chunk is <= 32KB."""
        try:
            response = self._open(
                "POST",
                "/api/chat",
                {"model": model, "messages": list(messages), "stream": True},
                self.timeout if timeout is None else float(timeout),
            )
        except OllamaOffline:
            return StreamResult(status="ollama offline", chunks=iter(()))
        return StreamResult(status="ok", chunks=_iter_limited(response, CHUNK_BYTES))

    def pull(self, *_args, **_kwargs):
        raise RuntimeError("model downloads are disabled")

    def _open(self, method: str, path: str, body: dict | None, timeout: float):
        if "pull" in path.split("/"):
            raise RuntimeError("model downloads are disabled")
        url = self.base_url + path
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.transport is not None:
            try:
                return self.transport.open(method, url, body, timeout, headers)
            except OllamaOffline:
                raise
            except (OSError, TimeoutError, urllib.error.URLError) as exc:
                raise OllamaOffline("ollama offline") from exc
        if not self.allow_network:
            raise OllamaOffline("ollama offline")
        return _urlopen(method, url, body, timeout, headers)


def _loopback_base(base_url: str) -> str:
    text = (base_url or "").strip().rstrip("/")
    parsed = urlparse(text)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not is_loopback_ip(host):
        raise ValueError("Ollama client is localhost only")
    return text


def _urlopen(method: str, url: str, body: dict | None, timeout: float, headers: dict):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — loopback checked
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaOffline("ollama offline") from exc


def _iter_limited(response, chunk_size: int):
    try:
        while True:
            raw = response.read(chunk_size)
            if not raw:
                break
            if not isinstance(raw, (bytes, bytearray)):
                raw = str(raw).encode("utf-8")
            view = bytes(raw)
            for start in range(0, len(view), chunk_size):
                yield view[start:start + chunk_size]
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()


def _read_capped(response, max_bytes: int) -> tuple[bytes, bool]:
    parts = []
    total = 0
    truncated = False
    for chunk in _iter_limited(response, CHUNK_BYTES):
        if total >= max_bytes:
            truncated = True
            break
        room = max_bytes - total
        if len(chunk) > room:
            parts.append(chunk[:room])
            total += room
            truncated = True
            break
        parts.append(chunk)
        total += len(chunk)
    return b"".join(parts), truncated


def _chat_text(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return raw.decode("utf-8", errors="replace")
    message = data.get("message") if isinstance(data, dict) else None
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(data, dict) and isinstance(data.get("response"), str):
        return data["response"]
    return ""
