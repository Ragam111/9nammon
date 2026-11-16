"""Local Ollama ``/api/chat`` (NDJSON when streaming) and ``/api/tags``.

The default root is the same host as ``model_backend`` / ``local_coder.OLLAMA_URL``.
No API key is required. ``OLLAMA_API_KEY``, when set, is sent as a bearer
token for a proxy in front of Ollama and is otherwise omitted.

Usage comes from ``prompt_eval_count`` and ``eval_count``. The price row is
0 USD because this API has no meter.
"""

from __future__ import annotations

from app.providers.base import ModelInfo, Provider, attach_stream, complete, first_int
from app.providers.errors import ProviderError
from app.providers.messages import to_openai_messages
from app.providers.transport import build_request, iter_ndjson, perform, request_json


def ollama_root(base: str) -> str:
    base = (base or "").strip().rstrip("/")
    for suffix in ("/api/chat", "/api/tags"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if base.endswith("/api"):
        base = base[: -len("/api")]
    return base


def default_ollama_root() -> str:
    from app.model_backend import OLLAMA_URL
    return ollama_root(OLLAMA_URL)


def _usage(data: dict) -> dict:
    if "prompt_eval_count" not in data and "eval_count" not in data:
        return {}
    return {
        "input": first_int(data, "prompt_eval_count"),
        "output": first_int(data, "eval_count"),
    }


def _text(data: dict) -> str:
    message = data.get("message") if isinstance(data, dict) else None
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return ""


def _body(model, messages, sampling, stream: bool) -> dict:
    body = {
        "model": model,
        "messages": to_openai_messages(messages),
        "stream": stream,
    }
    options = {}
    if "temperature" in sampling:
        options["temperature"] = sampling["temperature"]
    if "top_p" in sampling:
        options["top_p"] = sampling["top_p"]
    if "max_tokens" in sampling:
        options["num_predict"] = sampling["max_tokens"]
    if options:
        body["options"] = options
    return body


def _events(resp):
    for obj in iter_ndjson(resp):
        text = _text(obj)
        if text:
            yield "delta", text
        if obj.get("done"):
            usage = _usage(obj)
            if usage:
                yield "usage", usage


class OllamaProvider(Provider):
    name = "ollama"
    key_names = ("OLLAMA_API_KEY",)
    requires_key = False
    default_timeout = 300

    def __init__(self, **kwargs):
        if not kwargs.get("base_url"):
            kwargs["base_url"] = default_ollama_root()
        super().__init__(**kwargs)
        self.base_url = ollama_root(self.base_url)

    def _headers(self, key: str | None) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def chat(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts)
        req = build_request(
            "POST",
            self.base_url + "/api/chat",
            self._headers(key),
            _body(model, msgs, parsed["sampling"], False),
        )
        data = request_json(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return complete(self.name, model, _text(data), _usage(data), msgs, table)

    def stream(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts)
        req = build_request(
            "POST",
            self.base_url + "/api/chat",
            self._headers(key),
            _body(model, msgs, parsed["sampling"], True),
        )
        resp = perform(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return attach_stream(self.name, model, msgs, table, resp, _events(resp))

    def list_models(self):
        key = self.require_key()
        req = build_request(
            "GET",
            self.base_url + "/api/tags",
            self._headers(key),
            None,
        )
        data = request_json(req, self.timeout, provider=self.name, secrets=self.secret_values(key))
        rows = data.get("models")
        if not isinstance(rows, list):
            raise ProviderError("ollama: model list was not a models array", provider="ollama")
        found = []
        for row in rows:
            if isinstance(row, dict) and (row.get("name") or row.get("model")):
                name = str(row.get("name") or row.get("model"))
                found.append(ModelInfo(name, self.name, None))
        return found
