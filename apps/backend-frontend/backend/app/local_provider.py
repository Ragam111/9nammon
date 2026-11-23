"""Local model provider: Ollama on 127.0.0.1, and nothing else.

The base URL is fixed to the loopback address. Settings, environment variables and user input never change it, and
the constructor refuses any other host. Status checks use GET /api/tags; streaming uses the OpenAI-compatible
/v1/chat/completions endpoint, parsed by the same SSE code as the cloud providers.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx

from .errors import AppError, from_exception, from_upstream_status
from .model_client import StreamResult, iter_text

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
_LOOPBACK_HOST = "127.0.0.1"
_DEFAULT_PORT = 11434
_DEFAULT_TIMEOUT_S = 5.0
_CHARS_PER_TOKEN = 8  # the same output cap rule as the cloud chat relay (max_tokens * 8 characters)


class ModelStatus(StrEnum):
    READY = "ready"
    NOT_INSTALLED = "not_installed"
    NOT_ENOUGH_MEMORY = "not_enough_memory"
    UNREACHABLE = "unreachable"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class ModelSpec:
    """A model the local catalog knows about, with the RAM it needs (injected, never measured here)."""

    id: str
    label: str
    required_ram_gb: float


# Placeholder RAM requirement, not measured. The P0 measurement locks the real thresholds.
DEFAULT_LOCAL_CATALOG = (ModelSpec(id="qwen2.5-coder:1.5b", label="Qwen2.5 Coder 1.5B", required_ram_gb=2.0),)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    status: ModelStatus


@runtime_checkable
class ModelProvider(Protocol):
    id: str
    kind: Literal["local", "cloud"]

    async def list_models(self) -> list[ModelInfo]: ...

    def stream(self, messages: list[dict[str, str]], model: str, max_tokens: int) -> AsyncIterator[str]: ...


AvailableRam = Callable[[], float | None]


def _loopback_base(base_url: str) -> str:
    """The effective base URL. Only plain http to exactly 127.0.0.1 is accepted."""
    parts = urlsplit(base_url)
    if parts.scheme != "http" or parts.hostname != _LOOPBACK_HOST:
        raise ValueError("ollama_local may only call 127.0.0.1")
    return f"http://{_LOOPBACK_HOST}:{parts.port or _DEFAULT_PORT}"


def _tag_matches(model_id: str, tag: str) -> bool:
    """`llama3` matches `llama3:latest`; anything else must match exactly."""
    return tag == model_id or (":" not in model_id and tag == f"{model_id}:latest")


def installed_flag(model_id: str, names: Sequence[str]) -> bool:
    """Whether Ollama reports the catalog model. Public wrapper of the same rule that sets the model status."""
    return any(_tag_matches(model_id, tag) for tag in names)


def _status_for(spec: ModelSpec, installed: Sequence[str], available_ram: float | None) -> ModelStatus:
    if not installed_flag(spec.id, installed):
        return ModelStatus.NOT_INSTALLED
    if available_ram is not None and available_ram < spec.required_ram_gb:
        return ModelStatus.NOT_ENOUGH_MEMORY
    return ModelStatus.READY


class OllamaLocalProvider:
    """ModelProvider for a local Ollama server. `available_ram_gb` returns None when the platform cannot say."""

    id = "ollama_local"
    kind: Literal["local", "cloud"] = "local"

    def __init__(
        self,
        *,
        catalog: Sequence[ModelSpec] = (),
        available_ram_gb: AvailableRam | None = None,
        enabled: bool = True,
        base_url: str = OLLAMA_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self.base_url = _loopback_base(base_url)
        self._catalog = tuple(catalog)
        self._available_ram = available_ram_gb
        self._enabled = enabled
        self._client = client or httpx.AsyncClient(transport=transport, timeout=timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _installed_tags(self) -> list[str] | None:
        """Model names Ollama reports, or None when it is not answering properly (refused, timeout, bad body)."""
        try:
            response = await self._client.get(f"{self.base_url}/api/tags")
        except httpx.HTTPError:
            return None
        if not 200 <= response.status_code < 300:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        items = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return None
        return [str(m["name"]) for m in items if isinstance(m, dict) and m.get("name")]

    async def list_models(self) -> list[ModelInfo]:
        """Status for each catalog model. Precedence: not_configured, unreachable, not_installed, not_enough_memory."""
        if not self._enabled or self._available_ram is None:
            return [ModelInfo(s.id, s.label, ModelStatus.NOT_CONFIGURED) for s in self._catalog]
        installed = await self._installed_tags()
        if installed is None:
            return [ModelInfo(s.id, s.label, ModelStatus.UNREACHABLE) for s in self._catalog]
        available = self._available_ram()
        return [ModelInfo(s.id, s.label, _status_for(s, installed, available)) for s in self._catalog]

    def free_ram_gb(self) -> float | None:
        """Free memory in GB as the host reports it now, or None when the host cannot say."""
        return self._available_ram() if self._available_ram is not None else None

    async def installed_models(self) -> tuple[bool, list[str]]:
        """(reachable, sorted installed model names). Never raises for an unreachable server."""
        if not self._enabled:
            return False, []
        installed = await self._installed_tags()
        if installed is None:
            return False, []
        return True, sorted(set(installed))

    async def stream(self, messages: list[dict[str, str]], model: str, max_tokens: int) -> AsyncIterator[str]:
        """Yield text deltas from /v1/chat/completions.

        Deltas already yielded are the partial answer when the stream drops part way.
        """
        if not self._enabled:
            raise AppError("upstream", "ยังไม่ได้เปิดใช้โมเดลในเครื่อง")
        payload = {"model": model, "messages": messages, "stream": True, "max_tokens": max_tokens}
        request = self._client.build_request("POST", f"{self.base_url}/v1/chat/completions", json=payload)
        try:
            response = await self._client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise from_exception(exc) from exc
        try:
            if not 200 <= response.status_code < 300:
                raise from_upstream_status(response.status_code, response.headers.get("retry-after"))
            if response.headers.get("content-type", "").startswith("application/json"):
                raise AppError("upstream", "บริการโมเดลในเครื่องตอบกลับไม่ถูกรูปแบบ — ตรวจว่า Ollama ทำงานอยู่")
            result = StreamResult()
            async for delta in iter_text(response, result, max(1, max_tokens) * _CHARS_PER_TOKEN):
                yield delta
        except AppError:
            raise
        except Exception as exc:  # a dropped connection or bad chunk after the stream started
            raise from_exception(exc) from exc
        finally:
            await response.aclose()


def system_available_ram_gb() -> float | None:
    """Available physical memory in GB, or None when the platform does not report it. Standard library only."""
    try:
        if sys.platform == "win32":
            return _windows_available_ram_gb()
        if sys.platform.startswith("linux"):
            return _linux_available_ram_gb()
    except (OSError, ValueError):
        return None
    return None


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [  # ctypes layout that mirrors the Windows MEMORYSTATUSEX struct
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


def _windows_available_ram_gb() -> float | None:
    stat = _MemoryStatusEx()
    stat.dwLength = ctypes.sizeof(stat)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
        return None
    return stat.ullAvailPhys / (1024**3)


def _linux_available_ram_gb() -> float | None:
    with open("/proc/meminfo", encoding="ascii") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024**2)  # the file reports kB
    return None
