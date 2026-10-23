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
import urllib.error
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

    def test_generate_stream_yields_chunks(self):
        b = mb.OllamaBackend()
        lines = [
            '{"message":{"content":"def "}}\n',
            '{"message":{"content":"foo"}}\n',
            '\n',                                  # บรรทัดว่าง — ต้องข้าม ไม่ล้ม
            'not-json\n',                          # บรรทัดพัง — ต้องข้าม ไม่ล้ม
            '{"message":{"content":"():"}}\n',
            '{"done":true}\n',                     # chunk จบ ไม่มี content
        ]
        with mock.patch("app.model_backend.urllib.request.urlopen",
                        return_value=_fake_stream(lines)):
            out = list(b.generate_stream("m", [{"role": "user", "content": "x"}]))
        self.assertEqual(out, ["def ", "foo", "():"])

    def test_generate_stream_urlerror_raises(self):
        b = mb.OllamaBackend()
        with mock.patch("app.model_backend.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("down")):
            with self.assertRaises(mb.BackendError):
                list(b.generate_stream("m", [{"role": "user", "content": "x"}]))


def _fake_resp(body: str):
    """สร้าง object ที่ทำตัวเหมือน response ของ urlopen (มี read + context manager)"""
    m = mock.MagicMock()
    m.read.return_value = body.encode("utf-8")
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def _fake_stream(lines):
    """response แบบ stream: iterate ได้ทีละบรรทัด (bytes) + เป็น context manager"""
    m = mock.MagicMock()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    m.__iter__.return_value = iter([ln.encode("utf-8") for ln in lines])
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

    def test_generate_stream_parses_sse(self):
        b = mb.OpenAICompatBackend("http://127.0.0.1:8000/v1")
        lines = [
            'data: {"choices":[{"delta":{"content":"Hel"}}]}\n',
            'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
            '\n',                                              # keep-alive ว่าง — ข้าม
            'data: {"choices":[{"delta":{}}]}\n',              # delta ไม่มี content — ข้าม
            'data: [DONE]\n',                                  # จบ — หยุด
            'data: {"choices":[{"delta":{"content":"X"}}]}\n', # หลัง DONE — ไม่ควรถึง
        ]
        with mock.patch("app.model_backend.urllib.request.urlopen",
                        return_value=_fake_stream(lines)):
            out = list(b.generate_stream("m", [{"role": "user", "content": "x"}]))
        self.assertEqual(out, ["Hel", "lo"])


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

    def test_module_generate_stream_yields_from_backend(self):
        # default ollama -> generate_stream() ไป stream จาก Ollama (mock NDJSON)
        lines = ['{"message":{"content":"a"}}\n', '{"message":{"content":"b"}}\n']
        with mock.patch("app.model_backend.urllib.request.urlopen",
                        return_value=_fake_stream(lines)):
            out = list(mb.generate_stream(self.root, "m", [{"role": "user", "content": "x"}]))
        self.assertEqual(out, ["a", "b"])

    def test_base_generate_stream_falls_back_to_generate(self):
        # backend ที่ไม่ override generate_stream ต้อง yield ก้อนเดียวจาก generate()
        class OneShot(mb.Backend):
            def generate(self, model, messages, num_ctx=8192, options=None):
                return "whole-answer"

        self.assertEqual(list(OneShot().generate_stream("m", [])), ["whole-answer"])


class BackendSettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_defaults_ollama_key_hidden(self):
        s = mb.get_backend_settings(self.root)
        self.assertEqual(s["MODEL_BACKEND"], "ollama")
        self.assertFalse(s["openai_api_key_set"])
        self.assertNotIn("OPENAI_API_KEY", s)        # ไม่เผย key เต็ม

    def test_set_openai_and_readback(self):
        mb.set_backend_settings(self.root, {
            "MODEL_BACKEND": "openai",
            "OPENAI_BASE_URL": "http://gpu-cloud:8000/v1/",
            "OPENAI_API_KEY": "sk-secret",
        })
        s = mb.get_backend_settings(self.root)
        self.assertEqual(s["MODEL_BACKEND"], "openai")
        self.assertEqual(s["OPENAI_BASE_URL"], "http://gpu-cloud:8000/v1")   # trailing slash ตัด
        self.assertTrue(s["openai_api_key_set"])                             # ตั้งแล้ว ไม่คืนค่า
        # เสียบจริง: get_backend ต้องได้ OpenAICompat ชี้ cloud
        b = mb.get_backend(self.root)
        self.assertIsInstance(b, mb.OpenAICompatBackend)
        self.assertEqual(b.base_url, "http://gpu-cloud:8000/v1")

    def test_set_rejects_bad_backend(self):
        with self.assertRaises(ValueError):
            mb.set_backend_settings(self.root, {"MODEL_BACKEND": "magic-gpu"})

    def test_set_rejects_bad_url(self):
        with self.assertRaises(ValueError):
            mb.set_backend_settings(self.root, {"OPENAI_BASE_URL": "ftp://x"})

    def test_empty_key_does_not_overwrite(self):
        mb.set_backend_settings(self.root, {"OPENAI_API_KEY": "sk-keep"})
        mb.set_backend_settings(self.root, {"MODEL_BACKEND": "openai"})   # ไม่ส่ง key
        self.assertTrue(mb.get_backend_settings(self.root)["openai_api_key_set"])

    def test_probe_reports_availability(self):
        with mock.patch.object(mb.OllamaBackend, "is_available", lambda self, **k: True):
            r = mb.probe_backend(self.root)
        self.assertEqual(r["backend"], "ollama")
        self.assertTrue(r["available"])


if __name__ == "__main__":
    unittest.main()
