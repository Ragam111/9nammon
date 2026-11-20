"""Shared test helpers: settings pointed at a temp dir, and a fake OpenAI-compatible model."""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

import httpx

from app.config import Settings


def make_settings(**overrides: object) -> Settings:
    base = Settings(
        data_dir=Path(tempfile.mkdtemp(prefix="bf-test-")),
        model_base_url="https://model.example.test/v1",
        model_name="test-model",
        model_api_key="sk-test-secret-1234",
        model_timeout_s=5.0,
        model_max_retries=2,
        retry_base_delay_s=0.0,
        max_input_chars=200,
        max_output_tokens=64,
        quota_tokens_per_day=1000,
        rate_limit_user_per_min=100,
        rate_limit_ip_per_min=1000,
        session_ttl_hours=1,
        cookie_secure=False,
        cors_origins=["http://127.0.0.1:5173"],
        cost_per_1k_tokens=0.5,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def sse_body(chunks: list[str], usage: dict[str, int] | None = None) -> bytes:
    """Build an OpenAI-style streaming body."""
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks]
    if usage:
        lines.append(f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


class FakeModel:
    """httpx transport that replays a list of responses (or exceptions), one per request."""

    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def ok_stream(chunks: list[str], usage: dict[str, int] | None = None) -> httpx.Response:
    return httpx.Response(200, content=sse_body(chunks, usage), headers={"content-type": "text/event-stream"})


def parse_sse(text: str) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in text.strip().split("\n\n"):
        name = data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if name:
            events.append((name, json.loads(data)))
    return events
