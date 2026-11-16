"""Local vs cloud: only a localhost / 127.0.0.1 / ::1 base_url is local.

No network, no API keys.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import chat_hub, config_manager  # noqa: E402
from app.providers import locality  # noqa: E402


class LoopbackUrlTest(unittest.TestCase):
    def test_localhost_is_local(self):
        self.assertTrue(locality.is_loopback_url("http://localhost:11434"))
        self.assertTrue(locality.is_loopback_url("http://LOCALHOST:8000/v1"))
        self.assertTrue(locality.is_loopback_url("localhost:11434"))

    def test_127_0_0_1_is_local(self):
        self.assertTrue(locality.is_loopback_url("http://127.0.0.1:8000/v1"))
        self.assertTrue(locality.is_loopback_url("https://127.0.0.1/v1"))

    def test_ipv6_loopback_is_local(self):
        self.assertTrue(locality.is_loopback_url("http://[::1]:11434"))
        self.assertTrue(locality.is_loopback_url("[::1]:8000"))
        self.assertTrue(locality.is_loopback_url("::1"))

    def test_lan_ip_is_cloud(self):
        self.assertFalse(locality.is_loopback_url("http://192.168.1.5:11434"))
        self.assertFalse(locality.is_loopback_url("http://10.0.0.7:8000/v1"))

    def test_remote_host_is_cloud(self):
        self.assertFalse(locality.is_loopback_url("https://api.example.com/v1"))
        self.assertFalse(locality.is_loopback_url("https://openrouter.ai/api/v1"))

    def test_lookalikes_are_cloud(self):
        for url in (
            "http://127.0.0.1.nip.io:8000",
            "http://localhost.evil.example",
            "http://127.0.0.2:8000",
            "http://0.0.0.0:11434",
            "http://[::ffff:127.0.0.1]:8000",
            "",
            None,
        ):
            with self.subTest(url=url):
                self.assertFalse(locality.is_loopback_url(url))


class ProviderLocalityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _set(self, key, value):
        config_manager.set_key(self.root, key, value)

    def test_defaults_are_local(self):
        self.assertTrue(locality.is_local_provider("ollama", self.root))
        self.assertTrue(locality.is_local_provider("openai_compat", self.root))
        self.assertTrue(locality.is_local_provider(None, self.root))

    def test_ollama_localhost_127_and_ipv6_are_local(self):
        for url in ("http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"):
            with self.subTest(url=url):
                self._set("OLLAMA_BASE_URL", url)
                self.assertTrue(locality.is_local_provider("ollama", self.root))

    def test_ollama_on_lan_ip_is_cloud(self):
        self._set("OLLAMA_BASE_URL", "http://192.168.1.5:11434")
        self.assertFalse(locality.is_local_provider("ollama", self.root))

    def test_openai_compat_lan_and_remote_are_cloud(self):
        for url in ("http://192.168.1.5:8000/v1", "https://api.together.xyz/v1"):
            with self.subTest(url=url):
                self._set("OPENAI_BASE_URL", url)
                self.assertFalse(locality.is_local_provider("openai_compat", self.root))

    def test_openai_compat_loopback_is_local(self):
        for url in ("http://localhost:8000/v1", "http://127.0.0.1:1234/v1", "http://[::1]:8000/v1"):
            with self.subTest(url=url):
                self._set("OPENAI_BASE_URL", url)
                self.assertTrue(locality.is_local_provider("openai_compat", self.root))

    def test_vendor_apis_are_cloud_even_behind_localhost_proxy(self):
        for name in ("anthropic", "openai", "gemini", "xai"):
            with self.subTest(name=name):
                self.assertFalse(locality.is_local_provider(name, self.root))
        self._set("ANTHROPIC_BASE_URL", "http://127.0.0.1:9000")
        self.assertFalse(locality.is_local_provider("anthropic", self.root))

    def test_unknown_provider_is_cloud(self):
        self.assertFalse(locality.is_local_provider("nope", self.root))

    def test_legacy_backend_follows_openai_base_url(self):
        self._set("MODEL_BACKEND", "openai")
        self._set("OPENAI_BASE_URL", "http://192.168.1.5:8000/v1")
        self.assertFalse(locality.is_local_provider(None, self.root))
        self._set("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1")
        self.assertTrue(locality.is_local_provider(None, self.root))

    def test_catalog_local_flag_uses_base_url(self):
        self._set("OLLAMA_BASE_URL", "http://192.168.1.5:11434")
        self._set("OPENAI_BASE_URL", "http://localhost:8000/v1")
        flags = {p["id"]: p["local"] for p in chat_hub._provider_catalog(self.root)}
        self.assertFalse(flags["ollama"])
        self.assertTrue(flags["openai_compat"])
        self.assertFalse(flags["anthropic"])


if __name__ == "__main__":
    unittest.main()
