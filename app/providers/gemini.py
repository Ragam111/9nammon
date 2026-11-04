"""Google Gemini ``generateContent`` / ``streamGenerateContent``.

The key is sent as ``x-goog-api-key`` and is not placed in the query string.
``streamGenerateContent`` uses ``alt=sse``. Assistant turns are role ``model``.
Parts marked ``thought`` are left out of the visible text when another text
part is present.
"""

from __future__ import annotations

import urllib.parse

from app.providers.base import ModelInfo, Provider, attach_stream, complete, first_int
from app.providers.errors import ProviderError
from app.providers.messages import to_gemini
from app.providers.transport import build_request, iter_sse_json, perform, request_json

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _model_id(model: str) -> str:
    if model.startswith("models/"):
        model = model[len("models/"):]
    return urllib.parse.quote(model, safe="")


def visible_text(data: dict) -> str:
    chunks = []
    for cand in data.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        parts = ((cand.get("content") or {}).get("parts")) or []
        plain = [
            str(p.get("text"))
            for p in parts
            if isinstance(p, dict) and p.get("text") and not p.get("thought")
        ]
        if not plain:
            plain = [
                str(p.get("text"))
                for p in parts
                if isinstance(p, dict) and p.get("text")
            ]
        chunks.extend(plain)
    return "".join(chunks)


def _usage(data: dict) -> dict:
    usage = data.get("usageMetadata") if isinstance(data, dict) else None
    if not isinstance(usage, dict) or not usage:
        return {}
    return {
        "input": first_int(usage, "promptTokenCount"),
        "output": first_int(usage, "candidatesTokenCount"),
        "total": first_int(usage, "totalTokenCount"),
    }


def _body(messages, sampling) -> dict:
    system, contents = to_gemini(messages)
    if not contents:
        raise ProviderError("gemini: conversation has no user or assistant turn")
    body: dict = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    config = {}
    if "temperature" in sampling:
        config["temperature"] = sampling["temperature"]
    if "top_p" in sampling:
        config["topP"] = sampling["top_p"]
    if "max_tokens" in sampling:
        config["maxOutputTokens"] = sampling["max_tokens"]
    if config:
        body["generationConfig"] = config
    return body


def _events(resp):
    for _event, data in iter_sse_json(resp):
        if not isinstance(data, dict):
            continue
        text = visible_text(data)
        if text:
            yield "delta", text
        usage = _usage(data)
        if any(usage.get(key) is not None for key in ("input", "output", "total")):
            yield "usage", usage


class GeminiProvider(Provider):
    name = "gemini"
    key_names = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    requires_key = True
    default_base = DEFAULT_BASE

    def _headers(self, key: str) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-goog-api-key": key,
        }

    def _endpoint(self, model: str, stream: bool) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        url = f"{self.base_url}/models/{_model_id(model)}:{action}"
        if stream:
            url += "?alt=sse"
        return url

    def chat(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts)
        req = build_request(
            "POST",
            self._endpoint(model, False),
            self._headers(key),
            _body(msgs, parsed["sampling"]),
        )
        data = request_json(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return complete(self.name, model, visible_text(data), _usage(data), msgs, table)

    def stream(self, messages, model, **opts):
        model, parsed, msgs, timeout, table, key = self.begin(messages, model, opts)
        req = build_request(
            "POST",
            self._endpoint(model, True),
            self._headers(key),
            _body(msgs, parsed["sampling"]),
        )
        resp = perform(req, timeout, provider=self.name, secrets=self.secret_values(key))
        return attach_stream(self.name, model, msgs, table, resp, _events(resp))

    def list_models(self):
        key = self.require_key()
        req = build_request(
            "GET",
            self.base_url + "/models",
            {"Accept": "application/json", "x-goog-api-key": key},
            None,
        )
        data = request_json(req, self.timeout, provider=self.name, secrets=self.secret_values(key))
        rows = data.get("models")
        if not isinstance(rows, list):
            raise ProviderError("gemini: model list was not a models array", provider=self.name)
        found = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            full = str(row["name"])
            short = full[len("models/"):] if full.startswith("models/") else full
            display = row.get("displayName")
            found.append(ModelInfo(short, self.name, str(display) if display else None))
        return found
