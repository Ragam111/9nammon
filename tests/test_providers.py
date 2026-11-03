"""Provider adapters: request shape, SSE/NDJSON, usage, cost, and switching.

No test in this module opens a socket. setUpModule replaces
``transport.open_request`` with a guard; each HTTP test patches that function
and the guard is restored afterwards.
"""

from __future__ import annotations

import io
import json
import os
import socket
import ssl
import sys
import tempfile
import unittest
import urllib.error
import http.client
from decimal import Decimal
from email.message import Message
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config_manager  # noqa: E402
from app import model_backend  # noqa: E402
from app.providers import (  # noqa: E402
    ProviderAuthError,
    ProviderError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    chat as chat_fn,
    estimate_tokens,
    get_provider,
    lookup_price,
    lookup_secret,
    register_price,
)
from app.providers.anthropic import AnthropicProvider  # noqa: E402
from app.providers.completions import (  # noqa: E402
    OpenAICompatProvider,
    OpenAIProvider,
    XAIProvider,
    completion_events,
)
from app.providers.gemini import GeminiProvider  # noqa: E402
from app.providers.keys import REF_KEY  # noqa: E402
from app.providers.messages import CONTINUED, to_anthropic, to_gemini, to_openai_messages  # noqa: E402
from app.providers.ollama import OllamaProvider, default_ollama_root, ollama_root  # noqa: E402
from app.providers.pricing import Price, unregister_price  # noqa: E402
from app.providers import transport  # noqa: E402

KEY = "test-key-value"
HISTORY = [
    {"role": "system", "content": "be brief"},
    {"role": "user", "content": "one"},
    {"role": "assistant", "content": "two"},
    {"role": "user", "content": "three"},
]
_REAL_OPEN = None


def setUpModule():
    global _REAL_OPEN
    _REAL_OPEN = transport.open_request

    def guarded(*_args, **_kwargs):
        raise AssertionError("provider tests must not open a network connection")

    transport.open_request = guarded


def tearDownModule():
    transport.open_request = _REAL_OPEN


class FakeResp:
    def __init__(self, body: bytes = b"", lines=None):
        self._body = body
        self._lines = lines or []
        self.closed = False

    def read(self):
        return self._body

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False

    def close(self):
        self.closed = True


def scripted(body=None, lines=None, error=None):
    box = {}

    def _open(req, timeout=None):
        box["req"] = req
        box["timeout"] = timeout
        box["url"] = req.full_url
        box["method"] = req.get_method()
        box["body"] = json.loads(req.data.decode("utf-8")) if req.data else None
        if error is not None:
            raise error
        raw = b"" if body is None else json.dumps(body).encode("utf-8")
        return FakeResp(raw, lines)

    return _open, box


def http_error(code, payload, headers=None):
    msg = Message()
    for name, value in (headers or {}).items():
        msg[name] = value
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return urllib.error.HTTPError(
        "https://example.invalid/v1", code, "err", msg, io.BytesIO(raw),
    )


def _sse(chunks):
    lines = []
    for chunk in chunks:
        lines.append(chunk)
        if not chunk.endswith("\n"):
            lines[-1] = chunk + "\n"
        lines.append("\n")
    return lines


OPENAI_CHUNK = {
    "choices": [{"message": {"role": "assistant", "content": "pong"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
}
ANTHROPIC_CHUNK = {
    "content": [{"type": "text", "text": "pong"}],
    "usage": {"input_tokens": 11, "output_tokens": 3},
}
GEMINI_CHUNK = {
    "candidates": [{"content": {"parts": [{"text": "pong"}]}}],
    "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 3, "totalTokenCount": 14},
}
OLLAMA_CHUNK = {
    "message": {"role": "assistant", "content": "pong"},
    "prompt_eval_count": 11,
    "eval_count": 3,
    "done": True,
}

OPENAI_STREAM = _sse([
    'data: {"choices":[{"delta":{"content":"po"}}]}',
    "data: not-json",
    'data: {"choices":[{"delta":{"content":"ng"}}]}',
    'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":3,"total_tokens":14}}',
    "data: [DONE]",
    'data: {"choices":[{"delta":{"content":"X"}}]}',
])
ANTHROPIC_STREAM = _sse([
    'event: message_start',
    'data: {"type":"message_start","message":{"usage":{"input_tokens":11,"output_tokens":1}}}',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"po"}}',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"hidden"}}',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ng"}}',
    'event: message_delta',
    'data: {"type":"message_delta","usage":{"output_tokens":3}}',
    'event: message_stop',
    'data: {"type":"message_stop"}',
])
GEMINI_STREAM = _sse([
    'data: {"candidates":[{"content":{"parts":[{"text":"po"}]}}],"usageMetadata":{"promptTokenCount":11,"candidatesTokenCount":1,"totalTokenCount":12}}',
    'data: {"candidates":[{"content":{"parts":[{"text":"ng"}]}}],"usageMetadata":{"promptTokenCount":11,"candidatesTokenCount":3,"totalTokenCount":14}}',
])
RESPONSES_STREAM = _sse([
    "event: response.output_text.delta",
    'data: {"type":"response.output_text.delta","delta":"po"}',
    "event: response.output_text.delta",
    'data: {"type":"response.output_text.delta","delta":"ng"}',
    "event: response.completed",
    'data: {"type":"response.completed","response":{"usage":{"input_tokens":11,"output_tokens":3,"total_tokens":14}}}',
])
OLLAMA_STREAM = [
    '{"message":{"content":"po"},"done":false}\n',
    "not-json\n",
    "\n",
    '{"message":{"content":"ng"},"done":false}\n',
    '{"message":{"content":""},"done":true,"prompt_eval_count":11,"eval_count":3}\n',
]


def _spec(
    name, factory, model, url, kind, cost, list_url, list_body, list_id, stream_lines,
    auth,
):
    return {
        "name": name,
        "factory": factory,
        "model": model,
        "url": url,
        "kind": kind,
        "cost": cost,
        "list_url": list_url,
        "list_body": list_body,
        "list_id": list_id,
        "stream_lines": stream_lines,
        "auth": auth,
    }


SPECS = [
    _spec(
        "anthropic",
        lambda: AnthropicProvider(api_key=KEY),
        "claude-sonnet-4-5",
        "https://api.anthropic.com/v1/messages",
        "anthropic",
        Decimal("0.000078"),
        "https://api.anthropic.com/v1/models",
        {"data": [{"id": "claude-sonnet-4-5", "display_name": "Sonnet"}]},
        "claude-sonnet-4-5",
        ANTHROPIC_STREAM,
        "anthropic",
    ),
    _spec(
        "openai",
        lambda: OpenAIProvider(api_key=KEY),
        "gpt-4.1",
        "https://api.openai.com/v1/chat/completions",
        "openai",
        Decimal("0.000046"),
        "https://api.openai.com/v1/models",
        {"data": [{"id": "gpt-4.1"}]},
        "gpt-4.1",
        OPENAI_STREAM,
        "bearer",
    ),
    _spec(
        "gemini",
        lambda: GeminiProvider(api_key=KEY),
        "gemini-2.5-flash",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        "gemini",
        Decimal("0.0000108"),
        "https://generativelanguage.googleapis.com/v1beta/models",
        {"models": [{"name": "models/gemini-2.5-flash", "displayName": "Flash"}]},
        "gemini-2.5-flash",
        GEMINI_STREAM,
        "gemini",
    ),
    _spec(
        "xai",
        lambda: XAIProvider(api_key=KEY),
        "grok-4.3",
        "https://api.x.ai/v1/chat/completions",
        "openai",
        Decimal("0.00002125"),
        "https://api.x.ai/v1/models",
        {"data": [{"id": "grok-4.3"}]},
        "grok-4.3",
        OPENAI_STREAM,
        "bearer",
    ),
    _spec(
        "ollama",
        lambda: OllamaProvider(api_key=None, base_url="http://127.0.0.1:11434"),
        "qwen2.5-coder:0.5b",
        "http://127.0.0.1:11434/api/chat",
        "ollama",
        Decimal("0"),
        "http://127.0.0.1:11434/api/tags",
        {"models": [{"name": "qwen2.5-coder:0.5b"}]},
        "qwen2.5-coder:0.5b",
        OLLAMA_STREAM,
        "none",
    ),
    _spec(
        "openai_compat",
        lambda: OpenAICompatProvider(api_key=KEY, base_url="http://127.0.0.1:9000/v1"),
        "my-local-model",
        "http://127.0.0.1:9000/v1/chat/completions",
        "openai",
        None,
        "http://127.0.0.1:9000/v1/models",
        {"data": [{"id": "my-local-model"}]},
        "my-local-model",
        OPENAI_STREAM,
        "bearer",
    ),
]


def _assert_auth(test, spec, req):
    test.assertNotIn(KEY, req.full_url)
    if spec["auth"] == "anthropic":
        test.assertEqual(req.get_header("X-api-key"), KEY)
        test.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
        test.assertIsNone(req.get_header("Authorization"))
    elif spec["auth"] == "bearer":
        test.assertEqual(req.get_header("Authorization"), f"Bearer {KEY}")
    elif spec["auth"] == "gemini":
        test.assertEqual(req.get_header("X-goog-api-key"), KEY)
        test.assertIsNone(req.get_header("Authorization"))
    elif spec["auth"] == "none":
        test.assertIsNone(req.get_header("Authorization"))
        test.assertIsNone(req.get_header("X-api-key"))


def _assert_transcript(test, spec, body, *, stream):
    encoded = json.dumps(body, ensure_ascii=False)
    for piece in ("be brief", "one", "two", "three"):
        test.assertIn(piece, encoded)
    kind = spec["kind"]
    if kind != "gemini":
        test.assertEqual(body["model"], spec["model"])
    if kind == "anthropic":
        test.assertEqual(body["system"], "be brief")
        test.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user"])
        test.assertEqual(body["messages"][1]["content"], "two")
        test.assertEqual(body["max_tokens"], 4096)
        test.assertEqual(body["stream"], stream)
    elif kind == "gemini":
        test.assertEqual(body["systemInstruction"]["parts"][0]["text"], "be brief")
        test.assertEqual([c["role"] for c in body["contents"]], ["user", "model", "user"])
        test.assertEqual(body["contents"][1]["parts"][0]["text"], "two")
    elif kind == "ollama":
        test.assertEqual(body["stream"], stream)
        test.assertEqual(body["messages"][0], {"role": "system", "content": "be brief"})
        test.assertEqual(body["messages"][2], {"role": "assistant", "content": "two"})
        test.assertNotIn("options", body)
    else:
        test.assertEqual(body["stream"], stream)
        test.assertEqual(body["messages"][0]["role"], "system")
        test.assertEqual(body["messages"][2]["content"], "two")
        test.assertNotIn("max_tokens", body)
        if stream and spec["name"] == "openai":
            test.assertEqual(body["stream_options"], {"include_usage": True})
        else:
            test.assertNotIn("stream_options", body)


class ProviderMatrixTest(unittest.TestCase):
    def _chat(self, spec):
        opener, box = scripted(body=_body_for(spec))
        original = list(HISTORY)
        with mock.patch("app.providers.transport.open_request", opener):
            result = spec["factory"]().chat(HISTORY, spec["model"], timeout=9)
        self.assertEqual(HISTORY, original)
        self.assertEqual(box["url"], spec["url"])
        self.assertEqual(box["method"], "POST")
        self.assertEqual(box["timeout"], 9)
        _assert_auth(self, spec, box["req"])
        _assert_transcript(self, spec, box["body"], stream=False)
        self.assertEqual(result.text, "pong")
        self.assertEqual(result.provider, spec["name"])
        self.assertFalse(result.usage.estimated)
        self.assertEqual(result.usage.source, "provider")
        self.assertEqual(result.usage.input_tokens, 11)
        self.assertEqual(result.usage.output_tokens, 3)
        self.assertEqual(result.usage.total_tokens, 14)
        self.assertFalse(result.cost.authoritative)
        self.assertIn("not an invoice", result.cost.note)
        if spec["cost"] is None:
            self.assertIsNone(result.cost.usd)
            self.assertIsNone(result.cost.source)
        else:
            self.assertEqual(result.cost.usd, spec["cost"])
            self.assertTrue(result.cost.source)

    def _stream(self, spec):
        opener, box = scripted(lines=spec["stream_lines"])
        with mock.patch("app.providers.transport.open_request", opener):
            stream = spec["factory"]().stream(HISTORY, spec["model"], timeout=9)
            deltas = list(stream)
        self.assertEqual(deltas, ["po", "ng"])
        self.assertNotIn("X", deltas)
        self.assertNotIn("hidden", "".join(deltas))
        self.assertEqual(box["timeout"], 9)
        if spec["kind"] == "gemini":
            self.assertIn(":streamGenerateContent", box["url"])
            self.assertIn("alt=sse", box["url"])
        else:
            self.assertTrue(box["body"]["stream"])
        _assert_auth(self, spec, box["req"])
        _assert_transcript(self, spec, box["body"], stream=True)
        self.assertFalse(stream.usage.estimated)
        self.assertEqual(stream.usage.input_tokens, 11)
        self.assertEqual(stream.usage.output_tokens, 3)
        self.assertEqual(stream.cost.usd, spec["cost"])
        self.assertFalse(stream.cost.authoritative)

    def _list(self, spec):
        opener, box = scripted(body=spec["list_body"])
        with mock.patch("app.providers.transport.open_request", opener):
            found = spec["factory"]().list_models()
        self.assertEqual(box["url"], spec["list_url"])
        self.assertEqual(box["method"], "GET")
        self.assertIsNone(box["body"])
        _assert_auth(self, spec, box["req"])
        self.assertEqual([item.id for item in found], [spec["list_id"]])
        self.assertEqual(found[0].provider, spec["name"])

    def _error(self, spec, problem, exc_type, check):
        opener, _box = scripted(error=problem)
        with mock.patch("app.providers.transport.open_request", opener):
            with self.assertRaises(exc_type) as caught:
                spec["factory"]().chat(HISTORY, spec["model"])
        if spec["auth"] != "none":
            self.assertNotIn(KEY, str(caught.exception))
        check(self, caught.exception)


def _body_for(spec):
    return {
        "anthropic": ANTHROPIC_CHUNK,
        "gemini": GEMINI_CHUNK,
        "ollama": OLLAMA_CHUNK,
    }.get(spec["kind"], OPENAI_CHUNK)


def _install_matrix():
    for spec in SPECS:
        def chat(self, spec=spec):
            self._chat(spec)

        def stream(self, spec=spec):
            self._stream(spec)

        def listing(self, spec=spec):
            self._list(spec)

        def auth(self, spec=spec):
            self._error(
                spec,
                http_error(401, {"error": {"message": f"bad {KEY}"}}),
                ProviderAuthError,
                lambda test, exc: test.assertEqual(exc.status, 401),
            )

        def limited(self, spec=spec):
            self._error(
                spec,
                http_error(429, {"error": {"message": "slow down"}}, {"Retry-After": "12"}),
                ProviderRateLimitError,
                lambda test, exc: (
                    test.assertEqual(exc.retry_after, 12.0),
                    test.assertEqual(exc.retry_after_raw, "12"),
                    test.assertEqual(exc.status, 429),
                ),
            )

        def timed(self, spec=spec):
            self._error(
                spec,
                socket.timeout("timed out"),
                ProviderTimeoutError,
                lambda test, exc: test.assertIn("timed out", str(exc)),
            )

        for fn, label in (
            (chat, "chat"),
            (stream, "stream"),
            (listing, "list_models"),
            (auth, "auth_error"),
            (limited, "rate_limit"),
            (timed, "timeout"),
        ):
            fn.__name__ = f"test_{label}_{spec['name']}"
            setattr(ProviderMatrixTest, fn.__name__, fn)


_install_matrix()


class SwitchingAndShapeTest(unittest.TestCase):
    def test_same_transcript_converts_for_each_provider(self):
        messages = [
            {"role": "system", "content": "ตอบสั้น"},
            {"role": "user", "content": "สวัสดี"},
            {"role": "assistant", "content": "หวัดดี"},
            {"role": "user", "content": "ต่อ"},
        ]
        from app.providers.messages import normalize_messages
        msgs = normalize_messages(messages)
        self.assertEqual([m.role for m in msgs], ["system", "user", "assistant", "user"])
        system, anthropic_turns = to_anthropic(msgs)
        self.assertEqual(system, "ตอบสั้น")
        self.assertEqual(anthropic_turns[0]["content"], "สวัสดี")
        self.assertEqual(anthropic_turns[1]["role"], "assistant")
        self.assertNotIn("system", [t["role"] for t in anthropic_turns])
        openai_turns = to_openai_messages(msgs)
        self.assertEqual(openai_turns, messages)
        gemini_system, contents = to_gemini(msgs)
        self.assertEqual(gemini_system, "ตอบสั้น")
        self.assertEqual([c["role"] for c in contents], ["user", "model", "user"])
        self.assertEqual(contents[1]["parts"][0]["text"], "หวัดดี")
        # Appending the assistant reply keeps the next provider in sync.
        continued = messages + [{"role": "assistant", "content": "ได้"}]
        again = normalize_messages(continued)
        _system, turns = to_anthropic(again)
        self.assertEqual(turns[-1], {"role": "assistant", "content": "ได้"})
        self.assertEqual(to_openai_messages(again)[-1]["content"], "ได้")

    def test_assistant_first_turn_is_continued_only_where_required(self):
        from app.providers.messages import normalize_messages
        msgs = normalize_messages([
            {"role": "assistant", "content": "earlier"},
            {"role": "user", "content": "go"},
        ])
        _system, anthropic_turns = to_anthropic(msgs)
        self.assertEqual(anthropic_turns[0], {"role": "user", "content": CONTINUED})
        _system, contents = to_gemini(msgs)
        self.assertEqual(contents[0]["parts"][0]["text"], CONTINUED)
        self.assertEqual(to_openai_messages(msgs)[0]["role"], "assistant")
        self.assertNotIn(CONTINUED, to_openai_messages(msgs)[0]["content"])

    def test_consecutive_roles_merge_for_anthropic_and_gemini(self):
        from app.providers.messages import normalize_messages
        msgs = normalize_messages([
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ])
        _system, turns = to_anthropic(msgs)
        self.assertEqual(turns, [{"role": "user", "content": "a\nb"}])
        _system, contents = to_gemini(msgs)
        self.assertEqual(contents[0]["parts"][0]["text"], "a\nb")
        self.assertEqual(len(to_openai_messages(msgs)), 2)

    def test_gemini_model_role_becomes_assistant_then_model(self):
        from app.providers.messages import normalize_messages
        msgs = normalize_messages([
            {"role": "user", "content": "q"},
            {"role": "model", "content": "a"},
        ])
        self.assertEqual(msgs[1].role, "assistant")
        self.assertEqual(to_openai_messages(msgs)[1]["role"], "assistant")
        _system, contents = to_gemini(msgs)
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(contents[1]["parts"][0]["text"], "a")

    def test_text_parts_join_and_images_are_rejected(self):
        from app.providers.messages import normalize_messages
        msgs = normalize_messages([{
            "role": "user",
            "content": [{"type": "text", "text": "aa"}, {"type": "text", "text": "bb"}],
        }])
        self.assertEqual(msgs[0].content, "aabb")
        with self.assertRaises(ProviderError):
            normalize_messages([{
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "http://example.invalid"}}],
            }])

    def test_thai_text_is_utf8_on_the_wire(self):
        opener, box = scripted(body=OPENAI_CHUNK)
        with mock.patch("app.providers.transport.open_request", opener):
            OpenAIProvider(api_key=KEY).chat(
                [{"role": "user", "content": "สวัสดี"}], "gpt-4.1",
            )
        self.assertIn("สวัสดี", box["req"].data.decode("utf-8"))

    def test_sampling_fields_follow_each_protocol(self):
        opener, box = scripted(body=ANTHROPIC_CHUNK)
        with mock.patch("app.providers.transport.open_request", opener):
            AnthropicProvider(api_key=KEY).chat(
                [{"role": "user", "content": "hi"}],
                "claude-sonnet-4-5",
                temperature=0.2,
                top_p=0.9,
                max_tokens=128,
            )
        self.assertEqual(box["body"]["max_tokens"], 128)
        self.assertEqual(box["body"]["temperature"], 0.2)
        self.assertEqual(box["body"]["top_p"], 0.9)

        opener, box = scripted(body=GEMINI_CHUNK)
        with mock.patch("app.providers.transport.open_request", opener):
            GeminiProvider(api_key=KEY).chat(
                [{"role": "user", "content": "hi"}],
                "gemini-2.5-flash",
                top_p=0.4,
                max_tokens=64,
            )
        self.assertEqual(box["body"]["generationConfig"]["topP"], 0.4)
        self.assertEqual(box["body"]["generationConfig"]["maxOutputTokens"], 64)

        opener, box = scripted(body=OLLAMA_CHUNK)
        with mock.patch("app.providers.transport.open_request", opener):
            OllamaProvider(base_url="http://127.0.0.1:11434").chat(
                [{"role": "user", "content": "hi"}],
                "qwen",
                max_tokens=32,
            )
        self.assertEqual(box["body"]["options"]["num_predict"], 32)

    def test_unsupported_option_does_not_call_the_network(self):
        with self.assertRaises(ProviderError):
            OllamaProvider(base_url="http://127.0.0.1:11434").chat(
                [{"role": "user", "content": "hi"}], "qwen", seed=1,
            )

    def test_module_level_chat_uses_the_provider(self):
        opener, box = scripted(body=OPENAI_CHUNK)
        with mock.patch("app.providers.transport.open_request", opener):
            result = chat_fn(
                [{"role": "user", "content": "hi"}],
                "gpt-4.1",
                provider=OpenAIProvider(api_key=KEY),
            )
        self.assertEqual(result.text, "pong")
        self.assertIn("/chat/completions", box["url"])


class UsageCostAndPricingTest(unittest.TestCase):
    def test_missing_usage_is_estimated(self):
        opener, _box = scripted(body={"content": [{"type": "text", "text": "pong"}]})
        with mock.patch("app.providers.transport.open_request", opener):
            result = AnthropicProvider(api_key=KEY).chat(HISTORY, "claude-sonnet-4-5")
        self.assertTrue(result.usage.estimated)
        self.assertEqual(result.usage.source, "estimate")
        self.assertEqual(result.usage.input_tokens, estimate_tokens("be brief") + 1 + 1 + 1)
        self.assertEqual(result.usage.output_tokens, estimate_tokens("pong"))
        self.assertTrue(result.cost.estimated)
        self.assertEqual(result.cost.input_usd_per_mtok, Decimal("3"))

    def test_partial_usage_is_mixed(self):
        opener, _box = scripted(body={
            "content": [{"type": "text", "text": "pong"}],
            "usage": {"input_tokens": 11},
        })
        with mock.patch("app.providers.transport.open_request", opener):
            result = AnthropicProvider(api_key=KEY).chat(
                [{"role": "user", "content": "hi"}], "claude-sonnet-4-5",
            )
        self.assertEqual(result.usage.source, "mixed")
        self.assertTrue(result.usage.estimated)
        self.assertEqual(result.usage.input_tokens, 11)
        self.assertEqual(result.usage.output_tokens, estimate_tokens("pong"))

    def test_unknown_model_has_no_price(self):
        opener, _box = scripted(body=ANTHROPIC_CHUNK)
        with mock.patch("app.providers.transport.open_request", opener):
            result = AnthropicProvider(api_key=KEY).chat(
                [{"role": "user", "content": "hi"}], "claude-no-such-model",
            )
        self.assertIsNone(result.cost.usd)
        self.assertFalse(result.cost.authoritative)
        self.assertEqual(result.usage.input_tokens, 11)

    def test_snapshot_ids_use_the_longest_listed_price(self):
        sonnet = lookup_price("anthropic", "claude-sonnet-4-5-20250929")
        self.assertEqual(sonnet.input_usd_per_mtok, Decimal("3"))
        mini = lookup_price("openai", "gpt-4o-mini-2024-07-18")
        self.assertEqual(mini.input_usd_per_mtok, Decimal("0.15"))
        self.assertNotEqual(mini.input_usd_per_mtok, lookup_price("openai", "gpt-4o").input_usd_per_mtok)

    def test_published_rows_name_their_source_and_are_not_authoritative(self):
        haiku = lookup_price("anthropic", "claude-haiku-5-5")
        self.assertIn("platform.claude.com", haiku.source)
        self.assertIn("100k", haiku.source)
        argon = lookup_price("gemini", "gemini-4-argon")
        self.assertIn("ai.google.dev", argon.source)
        self.assertIn("2026-12-01", argon.source)
        grok = lookup_price("xai", "grok-4.3")
        self.assertIn("docs.x.ai", grok.source)
        gpt = lookup_price("openai", "gpt-4.1")
        self.assertIn("developers.openai.com", gpt.source)
        self.assertIsNone(lookup_price("openai", "gpt-does-not-exist"))
        self.assertIsNone(lookup_price("openai_compat", "gpt-4.1"))
        local = lookup_price("ollama", "any-model")
        self.assertEqual(local.input_usd_per_mtok, Decimal("0"))
        self.assertIn("no token meter", local.source)

    def test_register_price_overrides_and_can_be_removed(self):
        try:
            register_price("openai", "gpt-unit", "3", "9", source="unit test table")
            found = lookup_price("openai", "gpt-unit")
            self.assertEqual(found.output_usd_per_mtok, Decimal("9"))
            self.assertEqual(found.source, "unit test table")
        finally:
            unregister_price("openai", "gpt-unit")
        self.assertIsNone(lookup_price("openai", "gpt-unit"))

    def test_call_level_price_table_replaces_the_default(self):
        opener, _box = scripted(body=OPENAI_CHUNK)
        table = {("openai", "gpt-4.1"): Price(Decimal("1"), Decimal("1"), source="unit")}
        with mock.patch("app.providers.transport.open_request", opener):
            result = OpenAIProvider(api_key=KEY).chat(
                [{"role": "user", "content": "hi"}], "gpt-4.1", price_table=table,
            )
        self.assertEqual(result.cost.usd, Decimal(11 + 3) / Decimal(1_000_000))
        self.assertEqual(result.cost.source, "unit")
        self.assertFalse(result.cost.authoritative)

    def test_estimate_tokens_uses_four_characters(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("abcde"), 1)
        self.assertEqual(estimate_tokens("สวัสดี"), max(1, len("สวัสดี") // 4))

    def test_gemini_thought_text_is_not_the_answer(self):
        opener, _box = scripted(body={
            "candidates": [{"content": {"parts": [
                {"thought": True, "text": "secret-thought"},
                {"text": "pong"},
            ]}}],
            "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1, "totalTokenCount": 3},
        })
        with mock.patch("app.providers.transport.open_request", opener):
            result = GeminiProvider(api_key=KEY).chat(
                [{"role": "user", "content": "hi"}], "gemini-2.5-flash",
            )
        self.assertEqual(result.text, "pong")
        self.assertNotIn("secret-thought", result.text)

    def test_responses_request_stream_and_usage(self):
        opener, box = scripted(body={
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "pong"}]}],
            "usage": {"input_tokens": 11, "output_tokens": 3, "total_tokens": 14},
        })
        with mock.patch("app.providers.transport.open_request", opener):
            result = OpenAIProvider(api_key=KEY).chat(
                HISTORY, "gpt-4.1", api="responses", max_tokens=77,
            )
        self.assertEqual(box["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(box["body"]["input"][0]["role"], "system")
        self.assertNotIn("messages", box["body"])
        self.assertEqual(box["body"]["max_output_tokens"], 77)
        self.assertNotIn("max_tokens", box["body"])
        self.assertEqual(result.text, "pong")
        self.assertEqual(result.usage.input_tokens, 11)
        self.assertEqual(result.cost.usd, Decimal("0.000046"))

        opener, box = scripted(lines=RESPONSES_STREAM)
        with mock.patch("app.providers.transport.open_request", opener):
            stream = OpenAIProvider(api_key=KEY, openai_api="responses").stream(HISTORY, "gpt-4.1")
            self.assertEqual(list(stream), ["po", "ng"])
        self.assertTrue(box["url"].endswith("/responses"))
        self.assertEqual(stream.usage.output_tokens, 3)
        self.assertFalse(stream.usage.estimated)


class ErrorNormalizationTest(unittest.TestCase):
    def test_echoed_key_is_scrubbed_and_not_printed(self):
        opener, _box = scripted(error=http_error(401, {"error": {"message": f"invalid {KEY}"}}))
        stdout = io.StringIO()
        with mock.patch("app.providers.transport.open_request", opener):
            with mock.patch("sys.stdout", stdout):
                with self.assertRaises(ProviderAuthError) as caught:
                    AnthropicProvider(api_key=KEY).chat([{"role": "user", "content": "hi"}], "claude-sonnet-4-5")
        self.assertIn("[redacted]", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))
        self.assertNotIn(KEY, stdout.getvalue())
        self.assertEqual(caught.exception.kind, "auth")

    def test_forbidden_is_auth_and_client_error_is_not(self):
        opener, _box = scripted(error=http_error(403, {"error": "no"}))
        with mock.patch("app.providers.transport.open_request", opener):
            with self.assertRaises(ProviderAuthError) as caught:
                XAIProvider(api_key=KEY).chat([{"role": "user", "content": "hi"}], "grok-4.3")
        self.assertEqual(caught.exception.status, 403)

        opener, _box = scripted(error=http_error(400, {"error": {"message": "bad request"}}))
        with mock.patch("app.providers.transport.open_request", opener):
            with self.assertRaises(ProviderError) as caught:
                XAIProvider(api_key=KEY).chat([{"role": "user", "content": "hi"}], "grok-4.3")
        self.assertNotIsInstance(caught.exception, ProviderAuthError)
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("bad request", str(caught.exception))

    def test_gateway_timeout_and_wrapped_socket_timeout(self):
        opener, _box = scripted(error=http_error(504, {"error": "gateway"}))
        with mock.patch("app.providers.transport.open_request", opener):
            with self.assertRaises(ProviderTimeoutError):
                GeminiProvider(api_key=KEY).chat(
                    [{"role": "user", "content": "hi"}], "gemini-2.5-flash",
                )

        opener, _box = scripted(error=urllib.error.URLError(socket.timeout("slow")))
        with mock.patch("app.providers.transport.open_request", opener):
            with self.assertRaises(ProviderTimeoutError) as caught:
                OpenAIProvider(api_key=KEY).chat([{"role": "user", "content": "hi"}], "gpt-4.1")
        self.assertNotIn("slow", str(caught.exception))

    def test_disconnect_is_a_network_error_without_the_key(self):
        opener, _box = scripted(error=http.client.RemoteDisconnected(f"reset {KEY}"))
        with mock.patch("app.providers.transport.open_request", opener):
            with self.assertRaises(ProviderNetworkError) as caught:
                OpenAICompatProvider(api_key=KEY, base_url="http://127.0.0.1:9/v1").chat(
                    [{"role": "user", "content": "hi"}], "m",
                )
        self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(caught.exception.kind, "network")

    def test_retry_after_http_date_parses_and_garbage_does_not(self):
        self.assertEqual(transport.parse_retry_after("12"), 12.0)
        self.assertIsNone(transport.parse_retry_after("not-a-date"))
        self.assertGreater(transport.parse_retry_after("Wed, 01 Jan 2099 00:00:00 GMT"), 0)
        self.assertEqual(transport.parse_retry_after("Mon, 01 Jan 2001 00:00:00 GMT"), 0.0)

        opener, _box = scripted(error=http_error(
            429, {}, {"Retry-After": "Wed, 01 Jan 2099 00:00:00 GMT"},
        ))
        with mock.patch("app.providers.transport.open_request", opener):
            with self.assertRaises(ProviderRateLimitError) as caught:
                AnthropicProvider(api_key=KEY).chat(
                    [{"role": "user", "content": "hi"}], "claude-sonnet-4-5",
                )
        self.assertGreater(caught.exception.retry_after, 0)

    def test_missing_key_does_not_open_a_connection(self):
        root = Path(tempfile.mkdtemp())
        removed = {}
        for name in (
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
            "XAI_API_KEY", "OPENAI_COMPAT_API_KEY", "OLLAMA_API_KEY",
        ):
            if name in os.environ:
                removed[name] = os.environ.pop(name)
        try:
            with self.assertRaises(ProviderAuthError) as caught:
                AnthropicProvider(project_root=root).chat(
                    [{"role": "user", "content": "hi"}], "claude-sonnet-4-5",
                )
            self.assertIn("ANTHROPIC_API_KEY", str(caught.exception))
            self.assertEqual(caught.exception.status, 401)
        finally:
            os.environ.update(removed)

    def test_urlerror_message_is_not_copied(self):
        opener, _box = scripted(error=urllib.error.URLError(f"down {KEY}"))
        with mock.patch("app.providers.transport.open_request", opener):
            with self.assertRaises(ProviderNetworkError) as caught:
                OllamaProvider(base_url="http://127.0.0.1:11434").chat(
                    [{"role": "user", "content": "hi"}], "qwen",
                )
        self.assertNotIn(KEY, str(caught.exception))


class KeyLookupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_config_json_is_sent_as_the_header(self):
        config_manager.set_key(self.root, "ANTHROPIC_API_KEY", "from-config-key")
        opener, box = scripted(body=ANTHROPIC_CHUNK)
        with mock.patch("app.providers.transport.open_request", opener):
            AnthropicProvider(project_root=self.root).chat(
                [{"role": "user", "content": "hi"}], "claude-sonnet-4-5",
            )
        self.assertEqual(box["req"].get_header("X-api-key"), "from-config-key")
        self.assertNotIn("from-config-key", box["url"])

    def test_default_secrets_module_is_secret_store(self):
        from app import secret_store
        from app.providers import keys
        self.assertIs(keys.load_secrets_module(), secret_store)

    def test_entry_only_in_secret_store_is_found_by_default(self):
        from app import secret_store
        secret_store.store(self.root, secret_store.config_entry_name("GEMINI_API_KEY"), "sealed-only")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)
            self.assertEqual(lookup_secret(self.root, ("GEMINI_API_KEY",)), "sealed-only")

    def test_sealed_config_key_round_trips_with_default_store(self):
        config_manager.set_key(self.root, "XAI_API_KEY", "sealed-xai")
        raw = (self.root / "config.json").read_text(encoding="utf-8")
        self.assertNotIn("sealed-xai", raw)
        self.assertEqual(lookup_secret(self.root, ("XAI_API_KEY",)), "sealed-xai")

    def test_env_is_used_when_config_is_empty(self):
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "from-env-key"}):
            found = lookup_secret(self.root, ("XAI_API_KEY",), secrets_module=False)
        self.assertEqual(found, "from-env-key")

    def test_compat_key_is_preferred_over_openai_key(self):
        config_manager.set_key(self.root, "OPENAI_COMPAT_API_KEY", "compat-key")
        config_manager.set_key(self.root, "OPENAI_API_KEY", "openai-key")
        found = lookup_secret(
            self.root, ("OPENAI_COMPAT_API_KEY", "OPENAI_API_KEY"), secrets_module=False,
        )
        self.assertEqual(found, "compat-key")

    def test_sealed_ref_uses_secrets_when_present(self):
        class Store:
            def config_entry_name(self, name):
                return f"config:{name}"

            def reveal(self, _root, entry):
                if entry == "config:ANTHROPIC_API_KEY":
                    return "from-sealed-store"
                return None

        with mock.patch(
            "app.providers.keys.config_manager.get_key",
            return_value={REF_KEY: "config:ANTHROPIC_API_KEY"},
        ):
            found = lookup_secret(self.root, ("ANTHROPIC_API_KEY",), secrets_module=Store())
        self.assertEqual(found, "from-sealed-store")

    def test_direct_store_entry_when_config_has_no_value(self):
        class Store:
            def config_entry_name(self, name):
                return f"config:{name}"

            def reveal(self, _root, entry):
                if entry == "config:GEMINI_API_KEY":
                    return "stored-only"
                return None

        with mock.patch("app.providers.keys.config_manager.get_key", return_value=None):
            found = lookup_secret(self.root, ("GEMINI_API_KEY",), secrets_module=Store())
        self.assertEqual(found, "stored-only")

    def test_sealed_ref_without_secrets_module_is_missing(self):
        with mock.patch(
            "app.providers.keys.config_manager.get_key",
            return_value={REF_KEY: "config:ANTHROPIC_API_KEY"},
        ):
            found = lookup_secret(self.root, ("ANTHROPIC_API_KEY",), secrets_module=False)
        self.assertIsNone(found)

    def test_constructor_key_beats_config(self):
        config_manager.set_key(self.root, "OPENAI_API_KEY", "from-config-key")
        opener, box = scripted(body=OPENAI_CHUNK)
        with mock.patch("app.providers.transport.open_request", opener):
            OpenAIProvider(api_key="constructor-key", project_root=self.root).chat(
                [{"role": "user", "content": "hi"}], "gpt-4.1",
            )
        self.assertEqual(box["req"].get_header("Authorization"), "Bearer constructor-key")

    def test_compat_without_a_key_omits_authorization(self):
        opener, box = scripted(body=OPENAI_CHUNK)
        with mock.patch("app.providers.transport.open_request", opener):
            OpenAICompatProvider(base_url="http://127.0.0.1:9000/v1", project_root=self.root).chat(
                [{"role": "user", "content": "hi"}], "local",
            )
        self.assertIsNone(box["req"].get_header("Authorization"))


class RegistryAndTransportTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_legacy_openai_backend_stays_compatible(self):
        config_manager.set_key(self.root, "MODEL_BACKEND", "openai")
        config_manager.set_key(self.root, "OPENAI_BASE_URL", "http://127.0.0.1:9010/v1")
        provider = get_provider(project_root=self.root)
        self.assertIsInstance(provider, OpenAICompatProvider)
        self.assertEqual(provider.base_url, "http://127.0.0.1:9010/v1")
        official = get_provider("openai", project_root=self.root)
        self.assertIsInstance(official, OpenAIProvider)
        self.assertEqual(official.base_url, "https://api.openai.com/v1")

    def test_chat_provider_and_aliases(self):
        config_manager.set_key(self.root, "MODEL_BACKEND", "ollama")
        config_manager.set_key(self.root, "CHAT_PROVIDER", "gemini")
        self.assertIsInstance(get_provider(project_root=self.root), GeminiProvider)
        self.assertIsInstance(get_provider("grok"), XAIProvider)
        self.assertIsInstance(get_provider("claude"), AnthropicProvider)
        self.assertIsInstance(get_provider("openai-compat", project_root=self.root), OpenAICompatProvider)
        with self.assertRaises(ProviderError):
            get_provider("no-such-provider")

    def test_default_ollama_root_matches_model_backend(self):
        self.assertEqual(default_ollama_root(), ollama_root(model_backend.OLLAMA_URL))
        provider = OllamaProvider(base_url=model_backend.OLLAMA_URL)
        self.assertTrue(provider.base_url.endswith(":11434") or provider.base_url.rstrip("/").endswith("11434"))
        self.assertFalse(provider.base_url.endswith("/api/chat"))

    def test_compat_base_suffix_is_not_doubled(self):
        opener, box = scripted(body=OPENAI_CHUNK)
        provider = OpenAICompatProvider(
            api_key=KEY, base_url="http://127.0.0.1:9/v1/chat/completions",
        )
        with mock.patch("app.providers.transport.open_request", opener):
            provider.chat([{"role": "user", "content": "hi"}], "m")
        self.assertEqual(box["url"], "http://127.0.0.1:9/v1/chat/completions")

    def test_tls_context_verifies_certificates(self):
        ctx = transport.ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_sse_events_without_a_blank_line_still_split(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"A"}}]}\n',
            'data: {"choices":[{"delta":{"content":"B"}}]}\n',
        ]
        events = list(completion_events(FakeResp(lines=lines)))
        self.assertEqual(events, [("delta", "A"), ("delta", "B")])

    def test_stream_close_records_usage_for_a_partial_read(self):
        opener, _box = scripted(lines=OPENAI_STREAM)
        with mock.patch("app.providers.transport.open_request", opener):
            stream = OpenAIProvider(api_key=KEY).stream(
                [{"role": "user", "content": "hi"}], "gpt-4.1",
            )
            self.assertEqual(next(iter(stream)), "po")
            stream.close()
        self.assertIsNotNone(stream.usage)
        self.assertIsNotNone(stream.cost)

    def test_model_backend_callers_keep_their_functions(self):
        self.assertTrue(callable(model_backend.generate))
        self.assertTrue(callable(model_backend.generate_stream))
        self.assertTrue(callable(model_backend.get_backend))
        self.assertEqual(model_backend.OllamaBackend().name, "ollama")
        self.assertEqual(model_backend.OpenAICompatBackend().name, "openai_compat")

    def test_empty_messages_and_bad_role_fail_before_http(self):
        provider = OllamaProvider(base_url="http://127.0.0.1:11434")
        with self.assertRaises(ProviderError):
            provider.chat([], "qwen")
        with self.assertRaises(ProviderError):
            provider.chat([{"role": "tool", "content": "x"}], "qwen")


if __name__ == "__main__":
    unittest.main()
