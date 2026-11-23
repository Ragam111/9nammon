"""P2 chat routes: model rows with provider_kind and status, local health, and the unchanged send contract.
The cloud providers and the local Ollama are both faked with httpx.MockTransport; no test opens a socket."""

from __future__ import annotations

import io
import os
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from app import chat
from app.auth import create_user
from app.db import Database
from app.main import create_app
from tests.helpers import FakeModel, make_settings, ok_stream, parse_sse
from tests.netguard import GuardedTestCase

PASSWORD = "correct-horse-battery"
LOCAL_MODEL = "qwen2.5-coder:1.5b"
FIVE_STATUSES = {"ready", "not_installed", "not_enough_memory", "unreachable", "not_configured"}
BASE: dict[str, Any] = {
    "chat_openai_api_key": "sk-chat-SECRET-4242",
    "chat_openai_models": ["gpt-test"],
    "chat_anthropic_models": ["claude-test"],
    "chat_gemini_models": ["gemini-test"],
    "login_per_ip_per_min": 100,
    "login_per_user_per_min": 100,
}
Handler = Callable[[httpx.Request], httpx.Response]


@contextmanager
def app_client(
    *, local: Handler | None = None, model: FakeModel | None = None, **overrides: Any
) -> Iterator[TestClient]:
    """A client whose local provider is enabled only when a `local` handler is given."""
    settings = make_settings(**{**BASE, "local_models_enabled": local is not None, **overrides})
    db = Database(settings.data_dir / "app.db")
    create_user(db, "alice", PASSWORD)
    cloud = (model or FakeModel([ok_stream(["x"])])).transport
    local_transport = httpx.MockTransport(local) if local is not None else None
    app = create_app(settings, cloud, io.StringIO(), local_transport=local_transport, local_ram_gb=lambda: 16.0)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
        yield client


def tags(*names: str) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": n} for n in names]})

    return handler


def rows_by_id(client: TestClient) -> dict[str, dict[str, Any]]:
    res = client.get("/api/chat/models")
    assert res.status_code == 200, res.text
    return {row["id"]: row for row in res.json()["models"]}


class ModelRowsTest(GuardedTestCase):
    def test_models_rows_have_provider_kind_and_status(self) -> None:
        with app_client(local=tags(LOCAL_MODEL)) as client:
            res = client.get("/api/chat/models")
            self.assertEqual(res.status_code, 200)
            rows = res.json()["models"]
            self.assertTrue(rows)
            for row in rows:
                self.assertIn(row["provider_kind"], {"local", "cloud"})
                self.assertIn(row["status"], FIVE_STATUSES)
                for key in ("id", "provider", "label", "configured"):
                    self.assertIn(key, row)
            kinds = {row["id"]: row["provider_kind"] for row in rows}
            self.assertEqual(kinds["gpt-test"], "cloud")
            # P3: the installed catalog model is listed as a local row; the send path routes it.
            self.assertEqual(kinds[LOCAL_MODEL], "local")
            self.assertEqual(set(kinds.values()), {"cloud", "local"})

    def test_models_cloud_status_not_configured_without_key(self) -> None:
        with app_client(chat_openai_api_key="") as client:
            gpt = rows_by_id(client)["gpt-test"]
            self.assertEqual(gpt["status"], "not_configured")
            self.assertEqual(gpt["provider_kind"], "cloud")
            self.assertFalse(gpt["configured"])

    def test_models_cloud_status_ready_with_key(self) -> None:
        with app_client() as client:
            gpt = rows_by_id(client)["gpt-test"]
            self.assertEqual(gpt["status"], "ready")
            self.assertTrue(gpt["configured"])

    def test_models_never_returns_api_key(self) -> None:
        with app_client(chat_openai_api_key="sk-test-secret") as client:
            res = client.get("/api/chat/models")
            self.assertEqual(res.status_code, 200)
            self.assertNotIn("sk-test-secret", res.text)

    def test_models_lists_local_model_when_ollama_has_it(self) -> None:
        with app_client(local=tags(LOCAL_MODEL)) as client:
            row = rows_by_id(client)[LOCAL_MODEL]
            self.assertEqual((row["provider_kind"], row["status"]), ("local", "ready"))
            health = client.get("/api/chat/local/health").json()
            self.assertEqual(health["models"], [LOCAL_MODEL])

    def test_cloud_rows_keep_status_when_local_provider_is_down(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with app_client(local=refuse) as client:
            rows = rows_by_id(client)
            self.assertEqual(rows["gpt-test"]["status"], "ready")
            self.assertEqual(rows[LOCAL_MODEL]["status"], "unreachable")


class LocalHealthTest(GuardedTestCase):
    def test_local_health_reachable_lists_installed_models(self) -> None:
        with app_client(local=tags(LOCAL_MODEL)) as client:
            res = client.get("/api/chat/local/health")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"reachable": True, "models": [LOCAL_MODEL]})

    def test_local_health_unreachable_is_200(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with app_client(local=refuse) as client:
            res = client.get("/api/chat/local/health")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"reachable": False, "models": []})

    def test_local_health_without_provider_is_unreachable(self) -> None:
        with app_client(local=tags(LOCAL_MODEL)) as client:
            client.app.state.ctx.local = None
            res = client.get("/api/chat/local/health")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"reachable": False, "models": []})

    def test_local_health_requires_signed_in_user(self) -> None:
        with app_client(local=tags(LOCAL_MODEL)) as client:
            client.cookies.clear()
            health = client.get("/api/chat/local/health")
            models = client.get("/api/chat/models")
            self.assertEqual((health.status_code, models.status_code), (401, 401))
            self.assertEqual(health.json()["error"]["type"], models.json()["error"]["type"])
            self.assertEqual(set(health.json()["error"]), set(models.json()["error"]))

    def test_local_health_ignores_base_url_query(self) -> None:
        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"models": []})

        with app_client(local=record) as client:
            res = client.get("/api/chat/local/health?base_url=http://10.0.0.5:9999")
            self.assertEqual(res.status_code, 200)
        self.assertTrue(seen)
        for request in seen:
            self.assertEqual((request.url.host, request.url.port), ("127.0.0.1", 11434))


class LocalEnvSettingTest(GuardedTestCase):
    def _flag(self, raw: str | None) -> bool:
        from app.config import load_settings

        env = {"ENV_FILE": "does-not-exist.env"}
        if raw is not None:
            env["LOCAL_MODELS_ENABLED"] = raw
        with mock.patch.dict(os.environ, env, clear=False):
            if raw is None:
                os.environ.pop("LOCAL_MODELS_ENABLED", None)
            return load_settings().local_models_enabled

    def test_local_models_enabled_defaults_off_and_parses_values(self) -> None:
        self.assertFalse(self._flag(None))
        self.assertTrue(self._flag("true"))
        self.assertTrue(self._flag("1"))
        self.assertFalse(self._flag("0"))
        self.assertFalse(self._flag("no"))
        self.assertFalse(self._flag("OFF"))


class SendContractTest(GuardedTestCase):
    def _send(self, client: TestClient, body: dict[str, Any]) -> httpx.Response:
        conv = client.post("/api/chat/conversations", json={"model": "gpt-test"}).json()["id"]
        return client.post(f"/api/chat/conversations/{conv}/messages", json=body)

    def test_post_message_contract_unchanged(self) -> None:
        ok = FakeModel([ok_stream(["สวัส", "ดี"], usage={"prompt_tokens": 3, "completion_tokens": 2})])
        with app_client(model=ok) as client:
            events = parse_sse(self._send(client, {"content": "hi", "model": "gpt-test"}).text)
            self.assertEqual([name for name, _ in events], ["start", "delta", "delta", "done"])
            done = events[-1][1]
            self.assertEqual((done["tokens_in"], done["tokens_out"]), (3, 2))

        class DropAfterFirstLine(httpx.AsyncByteStream):
            async def __aiter__(self) -> Any:
                yield 'data: {"choices": [{"delta": {"content": "สวัส"}}]}\n\n'.encode()
                raise httpx.RemoteProtocolError("peer closed connection")

        failing = FakeModel(
            [httpx.Response(200, stream=DropAfterFirstLine(), headers={"content-type": "text/event-stream"})]
        )
        with app_client(model=failing) as client:
            events = parse_sse(self._send(client, {"content": "hi", "model": "gpt-test"}).text)
            self.assertEqual([name for name, _ in events], ["start", "delta", "error"])
            error = events[-1][1]
            for key in ("code", "message", "partial", "message_id", "retryable"):
                self.assertIn(key, error)
            self.assertIs(error["partial"], True)

    def test_post_rejects_local_id_outside_the_local_catalog(self) -> None:
        # P3: a catalog id that is ready is routed locally (see test_local_send.py); a raw tag name never is.
        with app_client(local=tags("llama3:latest")) as client:
            res = self._send(client, {"content": "hi", "model": "llama3:latest"})
            self.assertEqual(res.status_code, 400)
            self.assertIn("ไม่พบโมเดลนี้ในรายการ", res.json()["error"]["message"])
        settings = make_settings(**BASE)
        self.assertNotIn(LOCAL_MODEL, [r.id for r in chat.catalog(settings)])


if __name__ == "__main__":
    unittest.main()
