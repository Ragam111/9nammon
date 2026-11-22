"""Chat API tests. The providers are faked with httpx.MockTransport, so no test touches the network."""

from __future__ import annotations

import asyncio
import io
import json
import time
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from app import chat, quota
from app.auth import create_user
from app.db import Database
from app.main import create_app
from app.model_client import estimate_tokens
from tests.helpers import FakeModel, make_settings, ok_stream, parse_sse

PASSWORD = "correct-horse-battery"
CHAT_KEY = "sk-chat-SECRET-4242"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

BASE: dict[str, Any] = {
    "chat_openai_api_key": CHAT_KEY,
    "chat_openai_models": ["gpt-test", "gpt-other"],
    "chat_anthropic_models": ["claude-test"],
    "chat_gemini_models": ["gemini-test"],
    # Logins are not what these tests measure; keep the login limiter out of the way.
    "login_per_ip_per_min": 100,
    "login_per_user_per_min": 100,
}


@contextmanager
def chat_client(model: FakeModel, **overrides: Any) -> Iterator[tuple[TestClient, io.StringIO]]:
    settings = make_settings(**{**BASE, **overrides})
    db = Database(settings.data_dir / "app.db")
    create_user(db, "alice", PASSWORD)
    create_user(db, "bob", PASSWORD)
    logs = io.StringIO()
    with TestClient(create_app(settings, model.transport, logs), base_url="http://127.0.0.1:8000") as client:
        yield client, logs


def sign_in(client: TestClient, name: str = "alice") -> None:
    client.cookies.clear()
    res = client.post("/api/auth/login", json={"username": name, "password": PASSWORD})
    if res.status_code != 200:
        raise AssertionError(res.text)


def new_conversation(client: TestClient, model_id: str = "gpt-test") -> str:
    res = client.post("/api/chat/conversations", json={"model": model_id})
    if res.status_code != 201:
        raise AssertionError(res.text)
    return str(res.json()["id"])


def send(client: TestClient, conv_id: str, content: str, model_id: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {"content": content}
    if model_id is not None:
        body["model"] = model_id
    return client.post(f"/api/chat/conversations/{conv_id}/messages", json=body)


def _user_id(client: TestClient, name: str = "alice") -> int:
    with client.app.state.ctx.db.session() as conn:
        return int(conn.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()["id"])


def _used_in_window(client: TestClient) -> int:
    """Tokens counted in the five-hour bucket, which includes any hold for an answer still in flight."""
    ctx = client.app.state.ctx
    return quota.used(ctx.db, _user_id(client), quota.plan(ctx.settings, heavy=False)[0].key)


class SpyModel(FakeModel):
    """FakeModel that runs `probe` each time the upstream is called, while the request is still in flight."""

    def __init__(self, responses: list[httpx.Response | Exception], probe: Callable[[], None]) -> None:
        super().__init__(responses)
        self.probe = probe

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.probe()
        return super().__call__(request)


class ConversationCrudTest(unittest.TestCase):
    def test_create_list_get_rename_and_delete(self) -> None:
        with chat_client(FakeModel([ok_stream(["x"])])) as (client, _):
            sign_in(client)
            res = client.post("/api/chat/conversations", json={"model": "gpt-test"})
            self.assertEqual(res.status_code, 201)
            conv = res.json()
            self.assertEqual(set(conv), {"id", "title", "model", "updated_at"})
            self.assertEqual(conv["model"], "gpt-test")
            conv_id = conv["id"]

            listed = client.get("/api/chat/conversations").json()["conversations"]
            self.assertEqual([c["id"] for c in listed], [conv_id])

            detail = client.get(f"/api/chat/conversations/{conv_id}").json()
            self.assertEqual(detail["messages"], [])
            self.assertEqual(detail["model"], "gpt-test")

            renamed = client.patch(f"/api/chat/conversations/{conv_id}", json={"title": "  งานใหม่  "})
            self.assertEqual((renamed.status_code, renamed.json()), (200, {"id": conv_id, "title": "งานใหม่"}))
            self.assertEqual(client.patch(f"/api/chat/conversations/{conv_id}", json={"title": ""}).status_code, 422)
            self.assertEqual(client.patch(f"/api/chat/conversations/{conv_id}", json={"title": "   "}).status_code, 400)

            self.assertEqual(client.delete(f"/api/chat/conversations/{conv_id}").status_code, 204)
            self.assertEqual(client.get(f"/api/chat/conversations/{conv_id}").status_code, 404)
            self.assertEqual(client.get("/api/chat/conversations").json()["conversations"], [])

    def test_list_is_newest_first(self) -> None:
        with chat_client(FakeModel([ok_stream(["x"])])) as (client, _):
            sign_in(client)
            first = new_conversation(client)
            second = new_conversation(client)
            ids = [c["id"] for c in client.get("/api/chat/conversations").json()["conversations"]]
            self.assertEqual(ids, [second, first])

    def test_send_sets_title_from_first_message_and_stores_both_turns(self) -> None:
        model = FakeModel([ok_stream(["สวัส", "ดี"], usage={"prompt_tokens": 3, "completion_tokens": 2})])
        with chat_client(model) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            events = parse_sse(send(client, conv_id, "ทักทาย\nรายละเอียด").text)
            self.assertEqual([e[0] for e in events], ["start", "delta", "delta", "done"])
            self.assertEqual("".join(str(e[1]["text"]) for e in events if e[0] == "delta"), "สวัสดี")
            detail = client.get(f"/api/chat/conversations/{conv_id}").json()
            self.assertEqual(detail["title"], "ทักทาย")
            self.assertEqual([(m["role"], m["content"], m["status"]) for m in detail["messages"]],
                             [("user", "ทักทาย\nรายละเอียด", "complete"), ("assistant", "สวัสดี", "complete")])
            self.assertEqual(events[-1][1]["message_id"], events[0][1]["message_id"])
            self.assertEqual(detail["messages"][1]["id"], events[0][1]["message_id"])


class AccessTest(unittest.TestCase):
    def test_anonymous_requests_are_refused(self) -> None:
        with chat_client(FakeModel([ok_stream(["x"])])) as (client, _):
            self.assertEqual(client.get("/api/chat/models").status_code, 401)
            self.assertEqual(client.get("/api/chat/conversations").json()["error"]["type"], "auth")

    def test_another_user_gets_404_on_every_route(self) -> None:
        model = FakeModel([ok_stream(["x"])])
        with chat_client(model) as (client, _):
            sign_in(client, "alice")
            conv_id = new_conversation(client)
            self.assertEqual(send(client, conv_id, "hi").status_code, 200)
            requests_before = len(model.requests)

            sign_in(client, "bob")
            self.assertEqual(client.get("/api/chat/conversations").json()["conversations"], [])
            self.assertEqual(client.get(f"/api/chat/conversations/{conv_id}").status_code, 404)
            self.assertEqual(client.patch(f"/api/chat/conversations/{conv_id}", json={"title": "x"}).status_code, 404)
            self.assertEqual(client.delete(f"/api/chat/conversations/{conv_id}").status_code, 404)
            res = send(client, conv_id, "intrude")
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (404, "validation"))
            self.assertEqual(len(model.requests), requests_before)  # nothing reached the provider

            sign_in(client, "alice")  # the owner still sees everything, untouched
            detail = client.get(f"/api/chat/conversations/{conv_id}").json()
            self.assertEqual([m["content"] for m in detail["messages"]], ["hi", "x"])

    def test_unknown_conversation_id_is_404(self) -> None:
        with chat_client(FakeModel([ok_stream(["x"])])) as (client, _):
            sign_in(client)
            missing = "/api/chat/conversations/conv_does_not_exist"
            self.assertEqual(client.get(missing).status_code, 404)
            self.assertEqual(client.patch(missing, json={"title": "t"}).status_code, 404)
            self.assertEqual(client.delete(missing).status_code, 404)
            self.assertEqual(send(client, "conv_does_not_exist", "hi").status_code, 404)


class ProviderTest(unittest.TestCase):
    def test_models_route_reports_configured_flags_without_keys(self) -> None:
        with chat_client(FakeModel([ok_stream(["x"])])) as (client, _):
            sign_in(client)
            res = client.get("/api/chat/models")
            self.assertEqual(res.status_code, 200)
            self.assertNotIn(CHAT_KEY, res.text)
            flags = {m["id"]: (m["provider"], m["configured"]) for m in res.json()["models"]}
            self.assertEqual(flags["gpt-test"], ("gpt", True))
            self.assertEqual(flags["gpt-other"], ("gpt", True))
            self.assertEqual(flags["claude-test"], ("claude", False))
            self.assertEqual(flags["gemini-test"], ("gemini", False))

    def test_unconfigured_provider_is_400_and_nothing_is_stored(self) -> None:
        model = FakeModel([ok_stream(["x"])])
        with chat_client(model) as (client, _):
            sign_in(client)
            res = client.post("/api/chat/conversations", json={"model": "claude-test"})
            self.assertEqual(res.status_code, 400)
            conv_id = new_conversation(client)
            res = send(client, conv_id, "hi", model_id="claude-test")
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (400, "validation"))
            self.assertEqual(model.requests, [])
            self.assertEqual(client.get(f"/api/chat/conversations/{conv_id}").json()["messages"], [])

    def test_unknown_model_is_400(self) -> None:
        with chat_client(FakeModel([ok_stream(["x"])])) as (client, _):
            sign_in(client)
            self.assertEqual(client.post("/api/chat/conversations", json={"model": "ghost"}).status_code, 400)

    def test_openai_request_uses_bearer_and_official_url(self) -> None:
        model = FakeModel([ok_stream(["hi"], usage={"prompt_tokens": 1, "completion_tokens": 1})])
        with chat_client(model) as (client, _):
            sign_in(client)
            send(client, new_conversation(client), "hello")
            sent = model.requests[0]
            self.assertEqual(str(sent.url), OPENAI_URL)
            self.assertEqual(sent.headers["authorization"], f"Bearer {CHAT_KEY}")
            body = json.loads(sent.content)
            self.assertEqual((body["model"], body["stream"]), ("gpt-test", True))
            self.assertEqual(body["messages"], [{"role": "user", "content": "hello"}])

    def test_anthropic_and_gemini_use_their_own_endpoints_and_headers(self) -> None:
        model = FakeModel([ok_stream(["a"]), ok_stream(["g"])])
        keys = {"chat_anthropic_api_key": "sk-ant-TEST-1111", "chat_gemini_api_key": "gem-key-TEST-2222"}
        with chat_client(model, **keys) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client, "claude-test")
            self.assertEqual(send(client, conv_id, "one").status_code, 200)
            anthropic_req = model.requests[0]
            self.assertEqual(str(anthropic_req.url), "https://api.anthropic.com/v1/chat/completions")
            self.assertEqual(anthropic_req.headers["x-api-key"], "sk-ant-TEST-1111")
            self.assertEqual(anthropic_req.headers["anthropic-version"], "2023-06-01")
            self.assertNotIn("authorization", anthropic_req.headers)

            gem_conv = new_conversation(client, "gemini-test")
            self.assertEqual(send(client, gem_conv, "two").status_code, 200)
            gemini_req = model.requests[1]
            self.assertEqual(str(gemini_req.url),
                             "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            self.assertEqual(gemini_req.headers["authorization"], "Bearer gem-key-TEST-2222")

    def test_model_override_is_used_and_becomes_the_conversation_model(self) -> None:
        model = FakeModel([ok_stream(["x"]), ok_stream(["y"])])
        with chat_client(model) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client, "gpt-test")
            send(client, conv_id, "first", model_id="gpt-other")
            self.assertEqual(json.loads(model.requests[0].content)["model"], "gpt-other")
            self.assertEqual(client.get(f"/api/chat/conversations/{conv_id}").json()["model"], "gpt-other")


class SendTest(unittest.TestCase):
    def test_over_length_content_is_400_before_any_upstream_call(self) -> None:
        model = FakeModel([ok_stream(["x"])])
        with chat_client(model) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            res = send(client, conv_id, "x" * 201)  # max_input_chars is 200 in the test settings
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (400, "validation"))
            self.assertEqual(model.requests, [])

    def test_blank_content_is_400(self) -> None:
        with chat_client(FakeModel([ok_stream(["x"])])) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            self.assertEqual(send(client, conv_id, "   \n ").status_code, 400)

    def test_history_is_truncated_to_the_most_recent_turns_that_fit(self) -> None:
        model = FakeModel([ok_stream(["A" * 40]), ok_stream(["B" * 40]), ok_stream(["C" * 20])])
        with chat_client(model, max_input_chars=100) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            send(client, conv_id, "a" * 40)
            send(client, conv_id, "b" * 40)
            self.assertEqual(send(client, conv_id, "c" * 20).status_code, 200)
            sent = json.loads(model.requests[2].content)["messages"]
            self.assertEqual(sent, [
                {"role": "user", "content": "b" * 40},
                {"role": "assistant", "content": "B" * 40},
                {"role": "user", "content": "c" * 20},
            ])
            self.assertLessEqual(sum(len(m["content"]) for m in sent), 100)
            self.assertNotIn("system", {m["role"] for m in sent})

    def test_upstream_drop_mid_stream_stores_a_partial_answer(self) -> None:
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):  # type: ignore[override]
                yield b'data: {"choices":[{"delta":{"content":"half"}}]}\n\n'
                raise httpx.ReadError("connection reset")

        model = FakeModel([httpx.Response(200, stream=Broken())])
        with chat_client(model) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            events = parse_sse(send(client, conv_id, "hi").text)
            self.assertEqual([e[0] for e in events], ["start", "delta", "error"])
            err = events[-1][1]
            self.assertEqual((err["code"], err["partial"], err["retryable"]), ("upstream", True, True))
            self.assertEqual(err["message_id"], events[0][1]["message_id"])
            messages = client.get(f"/api/chat/conversations/{conv_id}").json()["messages"]
            self.assertEqual([(m["role"], m["content"], m["status"]) for m in messages],
                             [("user", "hi", "complete"), ("assistant", "half", "partial")])

    def test_empty_stream_stores_no_assistant_message(self) -> None:
        with chat_client(FakeModel([ok_stream([])])) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            events = parse_sse(send(client, conv_id, "hi").text)
            self.assertEqual([e[0] for e in events], ["start", "error"])
            self.assertFalse(events[-1][1]["partial"])
            self.assertIsNone(events[-1][1]["message_id"])
            messages = client.get(f"/api/chat/conversations/{conv_id}").json()["messages"]
            self.assertEqual([m["role"] for m in messages], ["user"])

    def test_pre_stream_failure_is_json_error_and_no_assistant_message(self) -> None:
        model = FakeModel([httpx.Response(401)])  # the provider rejects the key; not retried
        with chat_client(model) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            res = send(client, conv_id, "hi")
            self.assertEqual(res.status_code, 502)
            self.assertEqual(res.headers["content-type"].split(";")[0], "application/json")
            self.assertEqual(res.json()["error"]["type"], "upstream")
            self.assertNotIn(CHAT_KEY, res.text)
            messages = client.get(f"/api/chat/conversations/{conv_id}").json()["messages"]
            self.assertEqual([m["role"] for m in messages], ["user"])

    def test_output_cap_marks_the_stored_answer_partial(self) -> None:
        model = FakeModel([ok_stream(["x" * 40])])
        with chat_client(model, max_output_tokens=2) as (client, _):  # 2 tokens = 16 characters here
            sign_in(client)
            conv_id = new_conversation(client)
            events = parse_sse(send(client, conv_id, "hi").text)
            self.assertEqual(events[-1][0], "done")
            messages = client.get(f"/api/chat/conversations/{conv_id}").json()["messages"]
            self.assertEqual((messages[-1]["content"], messages[-1]["status"]), ("x" * 16, "partial"))

    def test_quota_denial_is_429_and_stores_nothing(self) -> None:
        model = FakeModel([ok_stream(["x"])])
        with chat_client(model, quota_tokens_per_window=10) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            res = send(client, conv_id, "hi")
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (429, "quota"))
            self.assertEqual(model.requests, [])
            self.assertEqual(client.get(f"/api/chat/conversations/{conv_id}").json()["messages"], [])

    def test_success_is_charged_to_quota_like_run(self) -> None:
        model = FakeModel([ok_stream(["ok"], usage={"prompt_tokens": 7, "completion_tokens": 5})])
        with chat_client(model) as (client, _):
            sign_in(client)
            send(client, new_conversation(client), "hi")
            used = client.get("/api/settings").json()["quota"]["buckets"][0]["used"]
            self.assertEqual(used, 12)


class SecrecyTest(unittest.TestCase):
    def test_key_never_appears_in_responses_or_logs(self) -> None:
        model = FakeModel([ok_stream(["answer"]), httpx.Response(401), ok_stream(["second"])])
        with chat_client(model) as (client, logs):
            sign_in(client)
            bodies = [client.get("/api/chat/models").text]
            conv_id = new_conversation(client)
            bodies.append(client.get("/api/chat/conversations").text)
            bodies.append(send(client, conv_id, "hi").text)
            bodies.append(send(client, conv_id, "again").text)
            bodies.append(client.get(f"/api/chat/conversations/{conv_id}").text)
            bodies.append(client.post("/api/chat/conversations", json={"model": "claude-test"}).text)
            for text in [*bodies, logs.getvalue()]:
                self.assertNotIn(CHAT_KEY, text)
            self.assertEqual(model.requests[0].headers["authorization"], f"Bearer {CHAT_KEY}")

    def test_message_text_and_keys_are_not_logged(self) -> None:
        with chat_client(FakeModel([ok_stream(["secret reply"])])) as (client, logs):
            sign_in(client)
            send(client, new_conversation(client), "private question")
            text = logs.getvalue()
            self.assertIn('"event": "chat"', text)
            self.assertNotIn("private question", text)
            self.assertNotIn("secret reply", text)
            self.assertNotIn(CHAT_KEY, text)


class HoldAndDisconnectTest(unittest.TestCase):
    def test_quota_is_held_while_the_answer_is_in_flight(self) -> None:
        seen: list[int] = []
        holder: dict[str, TestClient] = {}
        model = SpyModel([ok_stream(["ok"], usage={"prompt_tokens": 7, "completion_tokens": 5})],
                         probe=lambda: seen.append(_used_in_window(holder["client"])))
        with chat_client(model) as (client, _):
            holder["client"] = client
            sign_in(client)
            self.assertEqual(send(client, new_conversation(client), "hi").status_code, 200)
            self.assertEqual(seen, [1 + 64])  # estimate for "hi" plus the output cap, held before the upstream call
            self.assertEqual(_used_in_window(client), 12)  # the hold is settled to the real usage

    def test_message_history_is_read_from_a_bounded_window(self) -> None:
        model = FakeModel([ok_stream(["A"]), ok_stream(["B"]), ok_stream(["C"])])
        with chat_client(model) as (client, _), mock.patch.object(chat, "HISTORY_LIMIT", 2, create=True):
            sign_in(client)
            conv_id = new_conversation(client)
            send(client, conv_id, "one")
            send(client, conv_id, "two")
            self.assertEqual(send(client, conv_id, "three").status_code, 200)
            sent = json.loads(model.requests[2].content)["messages"]
            self.assertEqual(sent, [
                {"role": "user", "content": "two"},
                {"role": "assistant", "content": "B"},
                {"role": "user", "content": "three"},
            ])

    def test_client_leaving_before_the_first_delta_still_settles(self) -> None:
        model = FakeModel([ok_stream(["one", "two"], usage={"prompt_tokens": 3, "completion_tokens": 2})])
        with chat_client(model) as (client, logs):
            sign_in(client)
            conv_id = new_conversation(client)
            ctx = client.app.state.ctx
            uid = _user_id(client)
            ref = chat.find_model(ctx.settings, "gpt-test")
            buckets = quota.plan(ctx.settings, heavy=False)
            chat.start_turn(ctx.db, uid, conv_id, "hi", ref.id, first_turn=True)
            quota.record_all(ctx.db, uid, buckets, 65)  # the hold the route takes before the upstream call
            upstream = asyncio.run(_leave_after_start(model, ctx, uid, conv_id, ref, buckets))
            self.assertTrue(upstream.is_closed)  # the upstream connection is released at once
            self.assertIn('"event": "chat"', logs.getvalue())  # the turn is logged once
            self.assertIn('"status": "error"', logs.getvalue())
            messages = client.get(f"/api/chat/conversations/{conv_id}").json()["messages"]
            self.assertEqual([(m["role"], m["status"]) for m in messages], [("user", "complete")])
            self.assertEqual(_used_in_window(client), 0)  # no output, so the hold is returned in full

    def test_conversation_deleted_mid_answer_releases_hold_and_closes_upstream(self) -> None:
        model = FakeModel([ok_stream(["one", "two"], usage={"prompt_tokens": 3, "completion_tokens": 2})])
        with chat_client(model) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            ctx = client.app.state.ctx
            uid = _user_id(client)
            ref = chat.find_model(ctx.settings, "gpt-test")
            buckets = quota.plan(ctx.settings, heavy=False)
            chat.start_turn(ctx.db, uid, conv_id, "hi", ref.id, first_turn=True)
            quota.record_all(ctx.db, uid, buckets, 65)  # the hold the route takes before the upstream call
            upstream = asyncio.run(_delete_mid_answer(model, ctx, uid, conv_id, ref, buckets))
            self.assertTrue(upstream.is_closed)  # the upstream connection is released
            # The hold of 65 is replaced by the estimate for the answer that was produced ("one").
            self.assertEqual(_used_in_window(client), estimate_tokens("hi") + estimate_tokens("one"))
            self.assertEqual(client.get(f"/api/chat/conversations/{conv_id}").status_code, 404)


async def _delete_mid_answer(model: FakeModel, ctx: Any, uid: int, conv_id: str, ref: chat.ModelRef,
                             buckets: list[quota.Bucket]) -> httpx.Response:
    """Stream one delta, delete the conversation while the answer is in flight, then the client disconnects."""
    async with httpx.AsyncClient(transport=model.transport) as http:
        upstream = await http.send(http.build_request("POST", OPENAI_URL, json={"stream": True}), stream=True)
        relay = chat._relay(ctx, uid, conv_id, ref, upstream, "hi", time.perf_counter(), "req-delete", 64,
                            buckets, "msg_delete", 65)
        assert (await relay.__anext__()).startswith("event: start")
        assert (await relay.__anext__()).startswith("event: delta")
        chat.delete_conversation(ctx.db, uid, conv_id)
        await relay.aclose()
    return upstream


async def _leave_after_start(model: FakeModel, ctx: Any, uid: int, conv_id: str, ref: chat.ModelRef,
                             buckets: list[quota.Bucket]) -> httpx.Response:
    """Open the upstream stream the way the route does, read only the start event, then close the relay."""
    async with httpx.AsyncClient(transport=model.transport) as http:
        upstream = await http.send(http.build_request("POST", OPENAI_URL, json={"stream": True}), stream=True)
        relay = chat._relay(ctx, uid, conv_id, ref, upstream, "hi", time.perf_counter(), "req-leave", 64,
                            buckets, "msg_leave", 65)
        start = await relay.__anext__()
        assert start.startswith("event: start"), start
        await relay.aclose()  # the browser went away at its first event
    return upstream


class RequestGuardTest(unittest.TestCase):
    def test_malformed_content_length_is_400_not_500(self) -> None:
        with chat_client(FakeModel([ok_stream(["x"])])) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            for value in ("abc", "-5", "1.5"):
                res = client.post(f"/api/chat/conversations/{conv_id}/messages", content=b'{"content": "hi"}',
                                  headers={"content-type": "application/json", "content-length": value})
                self.assertEqual((res.status_code, res.json()["error"]["type"]), (400, "validation"), value)

    def test_body_over_the_limit_is_413_before_any_upstream_call(self) -> None:
        model = FakeModel([ok_stream(["x"])])
        with chat_client(model) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            res = send(client, conv_id, "x" * (300 * 1024))
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (413, "validation"))
            self.assertEqual(model.requests, [])

    def test_foreign_origin_is_refused_on_patch_delete_and_send(self) -> None:
        model = FakeModel([ok_stream(["x"])])
        evil = {"Origin": "https://evil.example"}
        with chat_client(model) as (client, _):
            sign_in(client)
            conv_id = new_conversation(client)
            base = f"/api/chat/conversations/{conv_id}"
            self.assertEqual(client.patch(base, json={"title": "t"}, headers=evil).status_code, 401)
            self.assertEqual(client.delete(base, headers=evil).status_code, 401)
            self.assertEqual(client.post(f"{base}/messages", json={"content": "hi"}, headers=evil).status_code, 401)
            self.assertEqual(model.requests, [])
            detail = client.get(base).json()
            self.assertEqual((detail["title"], detail["messages"]), ("สนทนาใหม่", []))


if __name__ == "__main__":
    unittest.main()
