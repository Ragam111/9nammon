"""Streaming client for an OpenAI-compatible /chat/completions endpoint (Ollama, Google AI Studio's
OpenAI-compatible endpoint, and others). The request is retried only before the first byte arrives."""

from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from .config import Settings
from .errors import AppError, is_retryable_exception
from .retry import with_retry


@dataclass
class StreamResult:
    """Filled in while streaming; read after the iterator ends (or fails)."""

    text_parts: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    finished: bool = False   # provider sent [DONE] or a finish_reason
    truncated: bool = False  # we stopped at the output cap

    @property
    def text(self) -> str:
        return "".join(self.text_parts)


def estimate_tokens(text: str) -> int:
    """Rough token count (about 4 characters per token) used when the provider sends no usage."""
    return math.ceil(len(text) / 4) if text else 0


def _payload(settings: Settings, prompt: str) -> dict[str, object]:
    return {
        "model": settings.model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": settings.max_output_tokens,
        "stream_options": {"include_usage": True},
    }


async def open_stream(client: httpx.AsyncClient, settings: Settings, api_key: str, prompt: str) -> httpx.Response:
    """Send the request and return an open streaming response, retrying transient failures."""

    async def attempt() -> httpx.Response:
        request = client.build_request(
            "POST", f"{settings.model_base_url}/chat/completions",
            json=_payload(settings, prompt),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        response = await client.send(request, stream=True)
        if not 200 <= response.status_code < 300:
            await response.aclose()
            raise httpx.HTTPStatusError("upstream error", request=request, response=response)
        if response.headers.get("content-type", "").startswith("application/json"):
            await response.aclose()  # a JSON body on a streaming request is an error object, not a stream
            raise AppError("upstream", "บริการโมเดลตอบกลับในรูปแบบที่ไม่ใช่ stream — ตรวจ MODEL_BASE_URL และ MODEL_NAME")
        return response

    return await with_retry(
        attempt, max_retries=settings.model_max_retries, base_delay_s=settings.retry_base_delay_s,
        is_retryable=is_retryable_exception,
    )


def _parse_line(line: str, result: StreamResult) -> str | None:
    """Parse one SSE line. Returns the text delta, or None. Updates usage on `result`."""
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if data == "[DONE]":
        result.finished = True
        return None
    try:
        event = json.loads(data) if data else {}
    except json.JSONDecodeError:
        return None
    if event.get("error"):
        raise AppError("upstream", "บริการโมเดลแจ้งข้อผิดพลาดระหว่างตอบ — ลองใหม่อีกครั้ง")
    usage = event.get("usage") or {}
    if usage:
        result.tokens_in = int(usage.get("prompt_tokens") or 0)
        result.tokens_out = int(usage.get("completion_tokens") or 0)
    choices = event.get("choices") or []
    if choices and choices[0].get("finish_reason"):
        result.finished = True
    delta = (choices[0].get("delta") or {}).get("content") if choices else None
    return delta if isinstance(delta, str) and delta else None


async def iter_text(response: httpx.Response, result: StreamResult, max_chars: int) -> AsyncIterator[str]:
    """Yield text deltas from an open response, stop at `max_chars`, and always close the response."""
    try:
        async for line in response.aiter_lines():
            delta = _parse_line(line, result)
            if delta is None:
                continue
            room = max_chars - len(result.text)
            if len(delta) >= room:
                result.truncated = True
                delta = delta[:room]
            if delta:
                result.text_parts.append(delta)
                yield delta
            if result.truncated:
                break
    finally:
        await response.aclose()
    if not result.truncated and not result.finished:
        raise AppError("upstream", "คำตอบจากโมเดลจบไม่ครบ — ผลที่ได้มาแล้วยังอยู่ ลองใหม่ได้")
    if not result.truncated and not result.text:
        raise AppError("upstream", "โมเดลไม่ส่งข้อความกลับมา — ลองใหม่ หรือตรวจ MODEL_NAME")


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def require_key(api_key: str, base_url: str) -> None:
    """Remote providers need a key; a local server on 127.0.0.1/localhost may not."""
    local = (urlparse(base_url).hostname or "") in LOCAL_HOSTS
    if not api_key and not local:
        raise AppError("upstream", "ยังไม่ได้ตั้งค่า API key ของโมเดล — ไปที่หน้า Settings เพื่อตั้งค่า")
