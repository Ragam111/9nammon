"""
test_model_backend.py — เทส adapter library โดย *ไม่ต้องมี server/Ollama จริง*

- OllamaBackend: mock call_ollama (patch) + ตรวจว่าแปลง SystemExit เป็น BackendError
- OpenAICompatBackend: mock urlopen (patch) + ตรวจ parse และ error path
- get_backend: เลือกตาม config (default ollama / openai เมื่อสั่ง)
"""

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import model_backend as mb  # noqa: E402
from app import config_manager  # noqa: E402
import local_coder  # noqa: E402


class OllamaBackendTest(unittest.TestCase):
    def test_generate_passes_through(self):
        b = mb.OllamaBackend()
        with mock.patch.object(mb, "call_ollama",
                               lambda model, messages, num_ctx=8192, options=None: f"R:{model}"):
            self.assertEqual(b.generate("qwen2.5-coder:0.5b", [{"role": "user", "content": "hi"}]),
                             "R:qwen2.5-coder:0.5b")

    def test_systemexit_becomes_backend_error(self):
        b = mb.OllamaBackend()

        def boom(*a, **k):
            raise SystemExit(1)

        with mock.patch.object(mb, "call_ollama", boom):
            with self.assertRaises(mb.BackendError):
                b.generate("m", [{"role": "user", "content": "x"}])

    def test_name(self):
        self.assertEqual(mb.OllamaBackend().name, "ollama")


def _fake_resp(body: str):
    """สร้าง object ที่ทำตัวเหมือน response ของ urlopen (มี read + context manager)"""
    m = mock.MagicMock()
    m.read.return_value = body.encode("utf-8")
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


class OpenAICompatBackendTest(unittest.TestCase):
    def test_generate_parses_openai_response(self):
        b = mb.OpenAICompatBackend("http://127.0.0.1:8000/v1", api_key="sk-x")
        body = '{"choices":[{"message":{"role":"assistant","content":"hello world"}}]}'
        with mock.patch("app.model_backend.urllib.request.urlopen", return_value=_fake_resp(body)):
            self.assertEqual(b.generate("gpt-x", [{"role": "user", "content": "hi"}]), "hello world")

    def test_malformed_response_raises(self):
        b = mb.OpenAICompatBackend()
        with mock.patch("app.model_backend.urllib.request.urlopen",
                        return_value=_fake_resp('{"nope":1}')):
            with self.assertRaises(mb.BackendError):
                b.generate("m", [{"role": "user", "content": "x"}])

    def test_connection_error_raises(self):
        import urllib.error
        b = mb.OpenAICompatBackend()
        with mock.patch("app.model_backend.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("down")):
            with self.assertRaises(mb.BackendError):
                b.generate("m", [{"role": "user", "content": "x"}])

    def test_name(self):
        self.assertEqual(mb.OpenAICompatBackend().name, "openai_compat")


class GetBackendTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_is_ollama(self):
        self.assertIsInstance(mb.get_backend(self.root), mb.OllamaBackend)

    def test_openai_selected_from_config(self):
        config_manager.set_key(self.root, "MODEL_BACKEND", "openai")
        config_manager.set_key(self.root, "OPENAI_BASE_URL", "http://127.0.0.1:9000/v1")
        b = mb.get_backend(self.root)
        self.assertIsInstance(b, mb.OpenAICompatBackend)
        self.assertEqual(b.base_url, "http://127.0.0.1:9000/v1")

    def test_module_generate_uses_selected_backend(self):
        # default ollama -> generate() ไปเรียก call_ollama (mock ไว้)
        with mock.patch.object(mb, "call_ollama",
                               lambda model, messages, num_ctx=8192, options=None: "OK"):
            self.assertEqual(mb.generate(self.root, "m", [{"role": "user", "content": "x"}]), "OK")


if __name__ == "__main__":
    unittest.main()
