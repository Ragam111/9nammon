"""Model client. The workflow only needs complete(system, messages) -> text, so tests use a fake."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class ModelError(RuntimeError):
    """A model call failed or returned no text."""


class ModelClient(Protocol):
    def complete(self, system: str, messages: list[dict[str, str]]) -> str: ...


class AnthropicClient:
    """Messages API over HTTPS with the standard library only."""

    def __init__(self, api_key: str, model: str, max_tokens: int = 1500, timeout_s: float = 120.0,
                 url: str = API_URL) -> None:
        if not api_key:
            raise ModelError("ต้องตั้งค่า ANTHROPIC_API_KEY ก่อน")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.url = url

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        body = json.dumps({"model": self.model, "max_tokens": self.max_tokens, "system": system,
                           "messages": messages}).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310 - fixed https endpoint
            self.url, data=body, method="POST",
            headers={"content-type": "application/json", "x-api-key": self.api_key,
                     "anthropic-version": API_VERSION},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise ModelError(f"เรียกโมเดล {self.model} ไม่สำเร็จ: {exc}") from exc
        text = "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text")
        if not text.strip():
            raise ModelError(f"โมเดล {self.model} ตอบว่างเปล่า")
        return text
