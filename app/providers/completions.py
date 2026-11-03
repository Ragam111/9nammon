"""OpenAI Chat Completions, the Responses API, xAI, and any OpenAI-compatible base URL.

xAI and generic compatible endpoints speak Chat Completions. The official
OpenAI provider also speaks Responses when ``api="responses"`` (or
``openai_api="responses"``). ``stream_options.include_usage`` is sent only to
the official OpenAI chat endpoint; other servers may reject unknown fields.
"""

from __future__ import annotations

from app.providers.base import (
    ModelInfo,
    Provider,
    attach_stream,
    complete,
    first_int,
)
from app.providers.errors import ProviderError
from app.providers.messages import to_openai_messages
from app.providers.transport import (
    DONE,
    build_request,
    iter_sse_json,
    perform,
    request_json,
)

OPENAI_BASE = "https://api.openai.com/v1"
XAI_BASE = "https://api.x.ai/v1"


def normalize_base(base: str) -> str:
    base = (base or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/models"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return base


def _join(base: str, path: str) -> str:
    return normalize_base(base) + "/" + path.lstrip("/")


def message_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict) and part.get("type") in (None, "text", "output_text"):
                if part.get("text"):
                    chunks.append(str(part["text"]))
        return "".join(chunks)
    return ""


def completion_usage(data: dict) -> dict:
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict) or not usage:
        return {}
    return {
        "input": first_int(usage, "prompt_tokens", "input_tokens"),
        "output": first_int(usage, "completion_tokens", "output_tokens"),
        "total": first_int(usage, "total_tokens"),
    }


def completion_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    return message_text(message.get("content"))


def chat_body(model, messages, sampling, stream: bool, *, stream_options: bool) -> dict:
    body = {
        "model": model,
        "messages": to_openai_messages(messages),
        "stream": stream,
    }
    if "temperature" in sampling:
        body["temperature"] = sampling["temperature"]
    if "top_p" in sampling:
        body["top_p"] = sampling["top_p"]
    if "max_tokens" in sampling:
        body["max_tokens"] = sampling["max_tokens"]
    if stream and stream_options:
        body["stream_options"] = {"include_usage": True}
    return body


def completion_events(resp):
    for _event, data in iter_sse_json(resp):
        if data is DONE:
            break
        if not isinstance(data, dict):
            continue
        usage = completion_usage(data)
        if any(usage.get(key) is not None for key in ("input", "output", "total")):
            yield "usage", usage
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            continue
        delta = choices[0].get("delta") or {}
        text = message_text(delta.get("content"))
        if text:
            yield "delta", text


def responses_usage(data: dict) -> dict:
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict) or not usage:
        return {}
    return {
        "input": first_int(usage, "input_tokens", "prompt_tokens"),
        "output": first_int(usage, "output_tokens", "completion_tokens"),
        "total": first_int(usage, "total_tokens"),
    }


def responses_text(data: dict) -> str:
    chunks = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            chunks.append(content)
        else:
            chunks.append(message_text(content))
    if any(chunks):
        return "".join(chunks)
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    return ""


def responses_body(model, messages, sampling, stream: bool) -> dict:
    body = {
        "model": model,
        "input": to_openai_messages(messages),
        "stream": stream,
    }
    if "temperature" in sampling:
        body["temperature"] = sampling["temperature"]
    if "top_p" in sampling:
        body["top_p"] = sampling["top_p"]
    if "max_tokens" in sampling:
        body["max_output_tokens"] = sampling["max_tokens"]
    return body


def responses_events(resp):
    for event, data in iter_sse_json(resp):
        if data is DONE or not isinstance(data, dict):
            continue
        kind = data.get("type") or event
        if kind == "response.output_text.delta" and data.get("delta"):
            yield "delta", str(data["delta"])
        elif kind in ("response.completed", "response.incomplete"):
            obj = data.get("response") if isinstance(data.get("response"), dict) else data
            usage = responses_usage(obj)
            if any(usage.get(key) is not None for key in ("input", "output", "total")):
                yield "usage", usage


class ChatCompletionsProvider(Provider):
    """POST ``{base}/chat/completions`` and GET ``{base}/models``."""

    send_stream_options = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = normalize_base(self.base_url)

    def _headers(self, key: str | None, *, stream: bool) -> dict:
        headers = {"Content-Type": "application/json"}
        headers["Accept"] = "text/event-stream" if stream else "application/json"
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _auth_headers(self, key: str | None) -> dict:
        headers = {"Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _chat_completions(self, model, parsed, msgs, timeout, table, key):
        body = chat_body(model, msgs, parsed["sampling"], False, stream_options=False)
        req = build_request(
            "POST",
            _join(self.base_url, "chat/completions"),
            self._headers(key, stream=False),
            body,
        )
        data = request_json(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return complete(self.name, model, completion_text(data), completion_usage(data), msgs, table)

    def _stream_completions(self, model, parsed, msgs, timeout, table, key):
        body = chat_body(
            model, msgs, parsed["sampling"], True, stream_options=self.send_stream_options,
        )
        req = build_request(
            "POST",
            _join(self.base_url, "chat/completions"),
            self._headers(key, stream=True),
            body,
        )
        resp = perform(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return attach_stream(
            self.name, model, msgs, table, resp, completion_events(resp),
        )

    def chat(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts)
        return self._chat_completions(model, parsed, msgs, timeout, table, key)

    def stream(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts)
        return self._stream_completions(model, parsed, msgs, timeout, table, key)

    def list_models(self):
        key = self.require_key()
        if not self.base_url:
            raise ProviderError(f"{self.name}: base_url is required")
        req = build_request(
            "GET",
            _join(self.base_url, "models"),
            self._auth_headers(key),
            None,
        )
        data = request_json(req, self.timeout, provider=self.name, secrets=self.secret_values(key))
        rows = data.get("data")
        if not isinstance(rows, list):
            raise ProviderError(f"{self.name}: model list was not a data array", provider=self.name)
        found = []
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                display = row.get("name") or row.get("display_name")
                found.append(ModelInfo(str(row["id"]), self.name, str(display) if display else None))
        return found


class OpenAIProvider(ChatCompletionsProvider):
    name = "openai"
    key_names = ("OPENAI_API_KEY",)
    requires_key = True
    default_base = OPENAI_BASE
    send_stream_options = True

    def __init__(self, *, openai_api: str = "chat", **kwargs):
        if openai_api not in ("chat", "responses"):
            raise ProviderError("openai_api must be 'chat' or 'responses'")
        self.openai_api = openai_api
        super().__init__(**kwargs)

    def _mode(self, parsed) -> str:
        mode = parsed["api"] or self.openai_api
        if mode not in ("chat", "responses"):
            raise ProviderError("api must be 'chat' or 'responses'")
        return mode

    def chat(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts, allow_api=True)
        if self._mode(parsed) == "chat":
            return self._chat_completions(model, parsed, msgs, timeout, table, key)
        body = responses_body(model, msgs, parsed["sampling"], False)
        req = build_request(
            "POST",
            _join(self.base_url, "responses"),
            self._headers(key, stream=False),
            body,
        )
        data = request_json(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return complete(self.name, model, responses_text(data), responses_usage(data), msgs, table)

    def stream(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts, allow_api=True)
        if self._mode(parsed) == "chat":
            return self._stream_completions(model, parsed, msgs, timeout, table, key)
        body = responses_body(model, msgs, parsed["sampling"], True)
        req = build_request(
            "POST",
            _join(self.base_url, "responses"),
            self._headers(key, stream=True),
            body,
        )
        resp = perform(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return attach_stream(self.name, model, msgs, table, resp, responses_events(resp))


class XAIProvider(ChatCompletionsProvider):
    name = "xai"
    key_names = ("XAI_API_KEY",)
    requires_key = True
    default_base = XAI_BASE


class OpenAICompatProvider(ChatCompletionsProvider):
    """Any server that speaks ``/v1/chat/completions``. A key is optional (local vLLM)."""

    name = "openai_compat"
    key_names = ("OPENAI_COMPAT_API_KEY", "OPENAI_API_KEY")
    requires_key = False
    default_base = ""
