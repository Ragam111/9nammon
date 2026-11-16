"""Anthropic Messages API.

POST ``{base}/v1/messages`` with header ``anthropic-version: 2023-06-01`` and
``x-api-key``. ``max_tokens`` is required by the API; when the caller omits it
the request uses ``DEFAULT_MAX_TOKENS`` (4096), which is this adapter's default,
not a value published by Anthropic.

System text is the top-level ``system`` field. User and assistant turns alternate.
"""

from __future__ import annotations

from app.providers.base import ModelInfo, Provider, attach_stream, complete, first_int
from app.providers.errors import ProviderError
from app.providers.messages import to_anthropic
from app.providers.transport import build_request, iter_sse_json, perform, request_json

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_BASE = "https://api.anthropic.com"


def _text(data: dict) -> str:
    chunks = []
    for block in data.get("content") or []:
        if isinstance(block, str):
            chunks.append(block)
        elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            chunks.append(str(block["text"]))
    return "".join(chunks)


def _usage(data: dict) -> dict:
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict) or not usage:
        return {}
    return {
        "input": first_int(usage, "input_tokens"),
        "output": first_int(usage, "output_tokens"),
    }


def _events(resp):
    for event, data in iter_sse_json(resp):
        if not isinstance(data, dict):
            continue
        kind = data.get("type") or event
        if kind == "message_start":
            message = data.get("message") if isinstance(data.get("message"), dict) else {}
            usage = _usage(message)
            if usage:
                yield "usage", usage
        elif kind == "content_block_delta":
            delta = data.get("delta") if isinstance(data.get("delta"), dict) else {}
            if delta.get("type") in (None, "text_delta") and delta.get("text"):
                yield "delta", str(delta["text"])
        elif kind == "message_delta":
            usage = _usage(data)
            if usage:
                yield "usage", usage


class AnthropicProvider(Provider):
    name = "anthropic"
    key_names = ("ANTHROPIC_API_KEY",)
    requires_key = True
    default_base = DEFAULT_BASE

    def _headers(self, key: str, *, stream: bool) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

    def _body(self, model, messages, sampling, stream: bool) -> dict:
        system, turns = to_anthropic(messages)
        if not turns:
            raise ProviderError("anthropic: conversation has no user or assistant turn")
        body = {
            "model": model,
            "max_tokens": sampling.get("max_tokens", DEFAULT_MAX_TOKENS),
            "messages": turns,
            "stream": stream,
        }
        if system:
            body["system"] = system
        if "temperature" in sampling:
            body["temperature"] = sampling["temperature"]
        if "top_p" in sampling:
            body["top_p"] = sampling["top_p"]
        return body

    def chat(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts)
        req = build_request(
            "POST",
            self.base_url + "/v1/messages",
            self._headers(key, stream=False),
            self._body(model, msgs, parsed["sampling"], False),
        )
        data = request_json(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return complete(self.name, model, _text(data), _usage(data), msgs, table)

    def stream(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts)
        req = build_request(
            "POST",
            self.base_url + "/v1/messages",
            self._headers(key, stream=True),
            self._body(model, msgs, parsed["sampling"], True),
        )
        resp = perform(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return attach_stream(self.name, model, msgs, table, resp, _events(resp))

    def list_models(self):
        key = self.require_key()
        req = build_request(
            "GET",
            self.base_url + "/v1/models",
            {
                "Accept": "application/json",
                "x-api-key": key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            None,
        )
        data = request_json(req, self.timeout, provider=self.name, secrets=self.secret_values(key))
        rows = data.get("data")
        if not isinstance(rows, list):
            raise ProviderError("anthropic: model list was not a data array", provider=self.name)
        found = []
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                display = row.get("display_name")
                found.append(ModelInfo(str(row["id"]), self.name, str(display) if display else None))
        return found
