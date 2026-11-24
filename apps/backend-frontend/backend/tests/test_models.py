"""The model list comes from the configured server (GET /models), never from a hard-coded list."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable

import httpx

from app.errors import AppError
from app.model_client import list_models
from tests.helpers import make_settings

Handler = Callable[[httpx.Request], httpx.Response]


def _run(handler: Handler, base_url: str = "http://127.0.0.1:11434/v1", api_key: str = "") -> list[str]:
    settings = make_settings(model_base_url=base_url)

    async def go() -> list[str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await list_models(client, settings, api_key)

    return asyncio.run(go())


class ListModelsTest(unittest.TestCase):
    def test_returns_sorted_ids_from_the_server(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/models")
            body = {"object": "list", "data": [{"id": "qwen2.5:1.5b"}, {"id": "llama3:8b"}, {"nope": 1}]}
            return httpx.Response(200, json=body)

        self.assertEqual(_run(handler), ["llama3:8b", "qwen2.5:1.5b"])

    def test_sends_the_key_only_as_a_header(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization", "")
            return httpx.Response(200, json={"data": [{"id": "m"}]})

        _run(handler, base_url="https://api.example.test/v1", api_key="sk-test-key-9999")
        self.assertEqual(seen["auth"], "Bearer sk-test-key-9999")

    def test_remote_server_without_key_is_refused_before_any_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("must not call a remote server without a key")

        with self.assertRaises(AppError):
            _run(handler, base_url="https://api.example.test/v1", api_key="")

    def test_rejected_key_gives_a_key_message(self) -> None:
        with self.assertRaises(AppError) as ctx:
            _run(lambda r: httpx.Response(401, json={}), base_url="https://api.example.test/v1", api_key="sk-x")
        self.assertEqual(ctx.exception.type, "upstream")
        self.assertIn("API key", ctx.exception.user_message)

    def test_unreachable_server_is_an_upstream_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with self.assertRaises(AppError) as ctx:
            _run(handler)
        self.assertEqual(ctx.exception.type, "upstream")

    def test_non_openai_body_is_an_upstream_error(self) -> None:
        with self.assertRaises(AppError):
            _run(lambda r: httpx.Response(200, text="<html>not json</html>"))
        with self.assertRaises(AppError):
            _run(lambda r: httpx.Response(200, json={"models": []}))


if __name__ == "__main__":
    unittest.main()
