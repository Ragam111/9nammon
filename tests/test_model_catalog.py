"""
test_model_catalog.py — /api/chat/providers must list only models that really exist.

- local: names come from a fake Ollama /api/tags (temp config points OLLAMA_BASE_URL at it)
- Ollama down: empty model list + status, never a made-up list
- cloud providers without a configured key are not listed
No real Ollama, no real keys, temp dir only.
"""

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import chat_hub, config_manager  # noqa: E402
from app.providers.keys import PROVIDER_KEY_NAMES  # noqa: E402

FAKE_MODELS = ["qwen2.5:1.5b", "qwen2.5-coder:1.5b", "qwen2.5-coder:0.5b"]
CLOUD = ("anthropic", "openai", "gemini", "xai")


class _FakeOllama(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path != "/api/tags":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"models": [{"name": n} for n in FAKE_MODELS]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _no_key_env() -> dict:
    names = {n for names in PROVIDER_KEY_NAMES.values() for n in names}
    return {k: v for k, v in os.environ.items() if k not in names}


class ModelCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, _no_key_env(), clear=True)
        self._env.start()
        getattr(chat_hub, "_OLLAMA_CACHE", {}).clear()

    def tearDown(self) -> None:
        self._env.stop()
        getattr(chat_hub, "_OLLAMA_CACHE", {}).clear()
        self._tmp.cleanup()

    def _fake_ollama(self) -> str:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _catalog(self) -> dict:
        return {p["id"]: p for p in chat_hub._provider_catalog(self.root)}

    def test_ollama_models_come_from_api_tags(self) -> None:
        config_manager.set_key(self.root, "OLLAMA_BASE_URL", self._fake_ollama())
        # a recommendation for a model that is not installed must not be injected
        with mock.patch("app.resource_budget.pick_model",
                        return_value={"model": "qwen2.5-coder:3b"}):
            ollama = self._catalog()["ollama"]
        self.assertEqual(sorted(ollama["models"]), sorted(FAKE_MODELS))
        self.assertEqual(ollama["status"], "ok")
        self.assertNotIn("qwen2.5-coder:3b", ollama["models"])

    def test_ollama_down_returns_empty_list_with_status(self) -> None:
        config_manager.set_key(self.root, "OLLAMA_BASE_URL", f"http://127.0.0.1:{_free_port()}")
        ollama = self._catalog()["ollama"]
        self.assertEqual(ollama["models"], [])
        self.assertEqual(ollama["status"], "unreachable")

    def test_cloud_provider_without_key_is_hidden(self) -> None:
        config_manager.set_key(self.root, "OLLAMA_BASE_URL", self._fake_ollama())
        cat = self._catalog()
        for name in CLOUD:
            with self.subTest(name=name):
                self.assertNotIn(name, cat)

    def test_cloud_provider_with_key_is_listed(self) -> None:
        config_manager.set_key(self.root, "OLLAMA_BASE_URL", self._fake_ollama())
        config_manager.set_key(self.root, "ANTHROPIC_API_KEY", "test-not-a-real-key")
        cat = self._catalog()
        self.assertIn("anthropic", cat)
        self.assertTrue(cat["anthropic"]["models"])
        self.assertNotIn("openai", cat)
        self.assertNotIn("test-not-a-real-key", json.dumps(cat))  # key value never exposed


if __name__ == "__main__":
    unittest.main()
