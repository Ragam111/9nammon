"""P3 send path for local models: ids resolve to the local catalog, no cloud quota or key is used, the Ollama stream is
relayed as the usual SSE events, and refused or dropped local answers are handled without orphan rows.
Ollama and the cloud model are both faked with httpx.MockTransport; no test opens a socket."""

from __future__ import annotations

import io
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import Database
from app.main import create_app
from tests.helpers import FakeModel, make_settings, ok_stream, parse_sse
from tests.netguard import GuardedTestCase
from tests.test_local_routes import BASE, LOCAL_MODEL, PASSWORD

Handler = Callable[[httpx.Request], httpx.Response]
CLOUD_BUCKET_PREFIXES = ("5h|", "wk|", "hwk|")
SECRET_TEXT = "ข้อความลับ-SECRET-7731"


class DropAfterFirstLine(httpx.AsyncByteStream):
    """One OpenAI-style delta, then the connection drops."""

    async def __aiter__(self) -> Any:
        yield 'data: {"choices": [{"delta": {"content": "สวัส"}}]}\n\n'.encode()
        raise httpx.RemoteProtocolError("peer closed connection")


def ollama(installed: tuple[str, ...] = (LOCAL_MODEL,), *, drop: bool = False, refuse: bool = False,
           seen: list[httpx.Request] | None = None) -> Handler:
    """A fake Ollama: /api/tags lists `installed`, /v1/chat/completions streams two deltas (or drops after one)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if refuse:
            raise httpx.ConnectError("refused", request=request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": name} for name in installed]})
        if request.url.path == "/v1/chat/completions":
            if drop:
                return httpx.Response(200, stream=DropAfterFirstLine(),
                                      headers={"content-type": "text/event-stream"})
            return ok_stream(["สวัส", "ดี"])
        return httpx.Response(404, json={"error": "not found"})

    return handler


@contextmanager
def client_for(local: Handler, *, cloud: FakeModel | None = None, ram_gb: float | None = 16.0,
               log: io.StringIO | None = None, **overrides: Any) -> Iterator[TestClient]:
    """A signed-in client with local models enabled. `ram_gb` is the free memory the fake host reports."""
    settings = make_settings(**{**BASE, "local_models_enabled": True, **overrides})
    db = Database(settings.data_dir / "app.db")
    create_user(db, "alice", PASSWORD)
    model = cloud or FakeModel([ok_stream(["x"])])
    app = create_app(settings, model.transport, log if log is not None else io.StringIO(),
                     local_transport=httpx.MockTransport(local), local_ram_gb=lambda: ram_gb)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
        yield client


def new_conversation(client: TestClient, model: str = "gpt-test") -> str:
    res = client.post("/api/chat/conversations", json={"model": model})
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


def send(client: TestClient, conv_id: str, content: str = "hi", model: str = LOCAL_MODEL) -> httpx.Response:
    return client.post(f"/api/chat/conversations/{conv_id}/messages", json={"content": content, "model": model})


def stored_messages(client: TestClient, conv_id: str) -> list[dict[str, Any]]:
    return client.get(f"/api/chat/conversations/{conv_id}").json()["messages"]


def usage_days(client: TestClient) -> list[str]:
    db = client.app.state.ctx.db
    with db.session() as conn:
        return [str(row["day"]) for row in conn.execute("SELECT day FROM usage").fetchall()]


class LocalSendTest(GuardedTestCase):
    def test_local_send_streams_and_stores_user_and_assistant_rows(self) -> None:
        cloud = FakeModel([ok_stream(["x"])])
        with client_for(ollama(), cloud=cloud) as client:
            conv = new_conversation(client)
            res = send(client, conv)
            self.assertEqual(res.status_code, 200, res.text)
            names = [name for name, _ in parse_sse(res.text)]
            self.assertEqual(names[0], "start")
            self.assertEqual(names[-1], "done")
            self.assertEqual(set(names[1:-1]), {"delta"})
            msgs = stored_messages(client, conv)
            self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
            self.assertEqual(msgs[1]["content"], "สวัสดี")
            self.assertEqual(msgs[1]["status"], "complete")
            self.assertEqual(client.get(f"/api/chat/conversations/{conv}").json()["model"], LOCAL_MODEL)
            self.assertEqual(cloud.requests, [])  # the cloud model is never called for a local id

    def test_local_send_takes_no_cloud_quota_and_no_cloud_key(self) -> None:
        cloud = FakeModel([ok_stream(["x"])])
        with client_for(ollama(), cloud=cloud, quota_tokens_per_window=1) as client:
            conv = new_conversation(client)
            res = send(client, conv)  # the cloud window quota is already exhausted at 1 token
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(parse_sse(res.text)[-1][0], "done")
            self.assertFalse([d for d in usage_days(client) if d.startswith(CLOUD_BUCKET_PREFIXES)])
            self.assertEqual(cloud.requests, [])

    def test_local_send_is_still_rate_limited(self) -> None:
        with client_for(ollama(), rate_limit_user_per_min=1) as client:
            conv = new_conversation(client)
            self.assertEqual(send(client, conv).status_code, 200)
            second = send(client, conv)
            self.assertEqual(second.status_code, 429)
            self.assertEqual(second.json()["error"]["type"], "rate_limit")

    def test_refused_local_model_writes_no_rows(self) -> None:
        cases = [
            (ollama(installed=()), 16.0, "ollama pull"),  # not_installed
            (ollama(), 1.0, "RAM"),  # not_enough_memory: the placeholder needs 2.0 GB
            (ollama(refuse=True), 16.0, "Ollama"),  # unreachable
        ]
        for handler, ram_gb, expected in cases:
            with self.subTest(expected=expected), client_for(handler, ram_gb=ram_gb) as client:
                conv = new_conversation(client)
                res = send(client, conv)
                self.assertEqual(res.status_code, 400, res.text)
                self.assertEqual(res.json()["error"]["type"], "validation")
                self.assertIn(expected, res.json()["error"]["message"])
                self.assertEqual(stored_messages(client, conv), [])
                self.assertEqual(client.get(f"/api/chat/conversations/{conv}").json()["model"], "gpt-test")

    def test_raw_tag_name_is_not_routable_even_when_installed(self) -> None:
        with client_for(ollama(installed=("llama3:latest",))) as client:
            conv = new_conversation(client)
            res = send(client, conv, model="llama3:latest")
            self.assertEqual(res.status_code, 400)
            self.assertIn("ไม่พบโมเดลนี้ในรายการ", res.json()["error"]["message"])
            self.assertEqual(stored_messages(client, conv), [])

    def test_partial_local_answer_is_kept_and_reported_when_ollama_drops(self) -> None:
        with client_for(ollama(drop=True)) as client:
            conv = new_conversation(client)
            res = send(client, conv)
            self.assertEqual(res.status_code, 200)
            events = parse_sse(res.text)
            self.assertEqual([name for name, _ in events], ["start", "delta", "error"])
            error = events[-1][1]
            self.assertIs(error["partial"], True)
            self.assertIs(error["retryable"], True)  # upstream errors are retryable
            msgs = stored_messages(client, conv)
            self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
            self.assertEqual(msgs[1]["status"], "partial")
            self.assertEqual(msgs[1]["content"], "สวัส")
            self.assertEqual(error["message_id"], msgs[1]["id"])

    def test_user_message_text_stays_out_of_logs(self) -> None:
        log = io.StringIO()
        with client_for(ollama(), log=log) as client:
            conv = new_conversation(client)
            self.assertEqual(send(client, conv, content=SECRET_TEXT).status_code, 200)
        text = log.getvalue()
        self.assertNotIn(SECRET_TEXT, text)
        self.assertIn('"provider": "ollama_local"', text)

    def test_every_local_request_targets_loopback_11434(self) -> None:
        seen: list[httpx.Request] = []
        with client_for(ollama(seen=seen)) as client:
            conv = new_conversation(client)
            self.assertEqual(send(client, conv).status_code, 200)
        self.assertTrue(seen)
        self.assertIn("/v1/chat/completions", [r.url.path for r in seen])
        for request in seen:
            self.assertEqual((request.url.host, request.url.port), ("127.0.0.1", 11434))

    def test_create_conversation_accepts_ready_local_model_only(self) -> None:
        with client_for(ollama()) as client:
            res = client.post("/api/chat/conversations", json={"model": LOCAL_MODEL})
            self.assertEqual(res.status_code, 201, res.text)
            self.assertEqual(res.json()["model"], LOCAL_MODEL)
        with client_for(ollama(installed=())) as client:
            res = client.post("/api/chat/conversations", json={"model": LOCAL_MODEL})
            self.assertEqual(res.status_code, 400)


class LocalModelRowsTest(GuardedTestCase):
    def _rows(self, client: TestClient) -> dict[str, dict[str, Any]]:
        res = client.get("/api/chat/models")
        self.assertEqual(res.status_code, 200, res.text)
        return {row["id"]: row for row in res.json()["models"]}

    def test_local_row_carries_status_and_ram_and_cloud_rows_gain_only_additive_fields(self) -> None:
        with client_for(ollama(), ram_gb=16.0) as client:
            res = client.get("/api/chat/models")
            rows = self._rows(client)
            local = rows[LOCAL_MODEL]
            self.assertEqual(local["provider_kind"], "local")
            self.assertEqual(local["provider"], "ollama")
            self.assertEqual(local["label"], "Qwen2.5 Coder 1.5B")
            self.assertEqual(local["status"], "ready")
            self.assertIs(local["configured"], True)
            self.assertEqual(local["required_ram_gb"], 2.0)
            self.assertEqual(local["available_ram_gb"], 16.0)
            gpt = rows["gpt-test"]
            base_keys = {"id", "provider", "label", "configured", "provider_kind", "status"}
            self.assertTrue(base_keys <= set(gpt))
            self.assertTrue(set(gpt) - base_keys <= {"required_ram_gb", "available_ram_gb"})
            self.assertEqual(gpt["provider_kind"], "cloud")
            self.assertIsNone(gpt["required_ram_gb"])
            # Never a key, never a base URL.
            self.assertNotIn("SECRET-4242", res.text)
            self.assertNotIn("http", res.text)

    def test_local_row_status_follows_model_status(self) -> None:
        with client_for(ollama(installed=())) as client:
            self.assertEqual(self._rows(client)[LOCAL_MODEL]["status"], "not_installed")
        with client_for(ollama(), ram_gb=1.0) as client:
            self.assertEqual(self._rows(client)[LOCAL_MODEL]["status"], "not_enough_memory")
        with client_for(ollama(refuse=True)) as client:
            self.assertEqual(self._rows(client)[LOCAL_MODEL]["status"], "unreachable")


if __name__ == "__main__":
    unittest.main()
