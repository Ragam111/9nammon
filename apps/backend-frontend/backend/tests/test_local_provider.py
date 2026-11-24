"""Local provider (Ollama on 127.0.0.1) tests. Every request goes through httpx.MockTransport and the socket guard
is active for each test, so no test can open a real connection."""

from __future__ import annotations

import asyncio
import re
import socket
import unittest
from collections.abc import AsyncIterator, Callable
from unittest import mock

import httpx

from app.errors import AppError
from app.local_provider import ModelProvider, ModelSpec, ModelStatus, OllamaLocalProvider
from tests.helpers import ok_stream
from tests.netguard import GuardedTestCase

MODEL = "qwen2.5-coder:1.5b"
CATALOG = (ModelSpec(id=MODEL, label=MODEL, required_ram_gb=2.0),)
THAI = re.compile(r"[฀-๿]")
Handler = Callable[[httpx.Request], httpx.Response]


class Recorder:
    """Wraps a handler and keeps every request it receives."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def tags(*names: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": n} for n in names]})


def make_provider(
    recorder: Recorder, *, ram: float | None = 8.0, enabled: bool = True, catalog: tuple[ModelSpec, ...] = CATALOG
) -> OllamaLocalProvider:
    return OllamaLocalProvider(
        transport=httpx.MockTransport(recorder), catalog=catalog, available_ram_gb=lambda: ram, enabled=enabled
    )


def run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


class ModelStatusEnumTest(GuardedTestCase):
    def test_model_status_enum_has_exactly_five_values(self) -> None:
        self.assertEqual(
            {s.value for s in ModelStatus},
            {"ready", "not_installed", "not_enough_memory", "unreachable", "not_configured"},
        )


class ProviderIdentityTest(GuardedTestCase):
    def test_ollama_provider_identity(self) -> None:
        provider = make_provider(Recorder(lambda r: tags()))
        self.assertEqual(provider.id, "ollama_local")
        self.assertEqual(provider.kind, "local")
        self.assertIsInstance(provider, ModelProvider)
        self.assertTrue(callable(provider.list_models))
        self.assertTrue(callable(provider.stream))


class ListModelsTest(GuardedTestCase):
    def test_list_models_calls_only_loopback_api_tags(self) -> None:
        recorder = Recorder(lambda r: tags(MODEL))
        run(make_provider(recorder).list_models())
        self.assertEqual(len(recorder.requests), 1)
        request = recorder.requests[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(str(request.url), "http://127.0.0.1:11434/api/tags")
        self.assertEqual(request.url.host, "127.0.0.1")

    def test_list_models_ready_when_installed_and_ram_enough(self) -> None:
        recorder = Recorder(lambda r: tags(MODEL))
        infos = run(make_provider(recorder, ram=8.0).list_models())
        self.assertEqual([(i.id, i.status) for i in infos], [(MODEL, ModelStatus.READY)])

    def test_tag_name_matching(self) -> None:
        catalog = (
            ModelSpec(id="llama3", label="llama3", required_ram_gb=1.0),
            ModelSpec(id=MODEL, label=MODEL, required_ram_gb=1.0),
        )
        # "llama3" matches "llama3:latest"; the qwen id matches itself; a different tag does not match.
        recorder = Recorder(lambda r: tags("llama3:latest", "qwen2.5-coder:3b"))
        infos = {i.id: i.status for i in run(make_provider(recorder, catalog=catalog).list_models())}
        self.assertEqual(infos["llama3"], ModelStatus.READY)
        self.assertEqual(infos[MODEL], ModelStatus.NOT_INSTALLED)
        recorder = Recorder(lambda r: tags(MODEL))
        infos = {i.id: i.status for i in run(make_provider(recorder, catalog=catalog).list_models())}
        self.assertEqual(infos[MODEL], ModelStatus.READY)
        self.assertEqual(infos["llama3"], ModelStatus.NOT_INSTALLED)

    def test_connect_error_yields_unreachable_without_raising(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        infos = run(make_provider(Recorder(refuse)).list_models())
        self.assertEqual([(i.id, i.status) for i in infos], [(MODEL, ModelStatus.UNREACHABLE)])

    def test_missing_model_is_not_installed(self) -> None:
        infos = run(make_provider(Recorder(lambda r: tags("llama3:latest"))).list_models())
        self.assertEqual(infos[0].status, ModelStatus.NOT_INSTALLED)

    def test_insufficient_ram_is_not_enough_memory(self) -> None:
        infos = run(make_provider(Recorder(lambda r: tags(MODEL)), ram=1.0).list_models())
        self.assertEqual(infos[0].status, ModelStatus.NOT_ENOUGH_MEMORY)

    def test_status_precedence(self) -> None:
        # Disabled: not_configured, and no transport call at all.
        disabled = Recorder(lambda r: tags(MODEL))
        infos = run(make_provider(disabled, enabled=False).list_models())
        self.assertEqual([i.status for i in infos], [ModelStatus.NOT_CONFIGURED])
        self.assertEqual(disabled.requests, [])

        # Unreachable outranks not_installed and not_enough_memory.
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        infos = run(make_provider(Recorder(refuse), ram=0.5).list_models())
        self.assertEqual(infos[0].status, ModelStatus.UNREACHABLE)

        # not_installed outranks not_enough_memory: the model is absent, so RAM is not even the question.
        infos = run(make_provider(Recorder(lambda r: tags()), ram=0.5).list_models())
        self.assertEqual(infos[0].status, ModelStatus.NOT_INSTALLED)


class StreamTest(GuardedTestCase):
    def test_stream_yields_deltas_from_fake_sse(self) -> None:
        recorder = Recorder(lambda r: ok_stream(["สวัส", "ดี"]))
        provider = make_provider(recorder)

        async def collect() -> list[str]:
            return [delta async for delta in provider.stream([{"role": "user", "content": "hi"}], MODEL, 64)]

        self.assertEqual(run(collect()), ["สวัส", "ดี"])
        self.assertEqual(len(recorder.requests), 1)
        self.assertEqual(recorder.requests[0].url.host, "127.0.0.1")
        self.assertEqual(recorder.requests[0].url.path, "/v1/chat/completions")

    def test_stream_drop_keeps_partial_and_raises_thai_error(self) -> None:
        first = 'data: {"choices": [{"delta": {"content": "สวัสดี"}}]}\n\n'.encode()

        class DropAfterFirstLine(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                yield first
                raise httpx.RemoteProtocolError("peer closed connection")

        def drop(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=DropAfterFirstLine(), headers={"content-type": "text/event-stream"})

        provider = make_provider(Recorder(drop))
        received: list[str] = []

        async def consume() -> None:
            async for delta in provider.stream([{"role": "user", "content": "hi"}], MODEL, 64):
                received.append(delta)

        with self.assertRaises(AppError) as ctx:
            run(consume())
        self.assertEqual(received, ["สวัสดี"])  # the text produced before the drop is kept by the consumer
        self.assertTrue(THAI.search(ctx.exception.user_message))


class MissingRamTest(GuardedTestCase):
    def test_unknown_ram_does_not_block_an_installed_model(self) -> None:
        infos = run(make_provider(Recorder(lambda r: tags(MODEL)), ram=None).list_models())
        self.assertEqual(infos[0].status, ModelStatus.READY)

    def test_linux_meminfo_reports_available_gb(self) -> None:
        from app import local_provider

        data = "MemTotal:       16000000 kB\nMemAvailable:    8388608 kB\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=data)):
            self.assertEqual(local_provider._linux_available_ram_gb(), 8.0)

    def test_linux_meminfo_without_field_is_none(self) -> None:
        from app import local_provider

        with mock.patch("builtins.open", mock.mock_open(read_data="MemTotal: 16000000 kB\n")):
            self.assertIsNone(local_provider._linux_available_ram_gb())

    def test_unknown_platform_reports_none(self) -> None:
        from app import local_provider

        with mock.patch.object(local_provider.sys, "platform", "darwin"):
            self.assertIsNone(local_provider.system_available_ram_gb())


class StreamErrorsTest(GuardedTestCase):
    def _consume(self, provider: OllamaLocalProvider) -> None:
        async def take() -> None:
            async for _ in provider.stream([{"role": "user", "content": "hi"}], MODEL, 64):
                pass

        run(take())

    def test_disabled_stream_raises_without_a_call(self) -> None:
        recorder = Recorder(lambda r: ok_stream(["x"]))
        with self.assertRaises(AppError):
            self._consume(make_provider(recorder, enabled=False))
        self.assertEqual(recorder.requests, [])

    def test_server_error_status_raises_app_error(self) -> None:
        with self.assertRaises(AppError):
            self._consume(make_provider(Recorder(lambda r: httpx.Response(500, text="boom"))))

    def test_json_content_type_on_stream_request_raises_app_error(self) -> None:
        def as_json(r: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "not a stream"})

        with self.assertRaises(AppError):
            self._consume(make_provider(Recorder(as_json)))


class ConfigurationTest(GuardedTestCase):
    def test_base_url_is_fixed_to_loopback_by_default(self) -> None:
        provider = OllamaLocalProvider(
            transport=httpx.MockTransport(lambda r: tags()), catalog=CATALOG, available_ram_gb=lambda: 8.0
        )
        self.assertEqual(provider.base_url, "http://127.0.0.1:11434")
        for bad in ("http://localhost:11434", "http://example.com", "http://10.0.0.5:9999", "https://127.0.0.1:11434"):
            with self.subTest(base=bad), self.assertRaises(ValueError):
                OllamaLocalProvider(base_url=bad, catalog=CATALOG, available_ram_gb=lambda: 8.0)


class NetworkGuardTest(GuardedTestCase):
    def test_network_guard_blocks_real_sockets(self) -> None:
        with socket.socket() as sock, self.assertRaises(RuntimeError):
            sock.connect(("127.0.0.1", 9))


if __name__ == "__main__":
    unittest.main()
