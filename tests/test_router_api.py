"""
test_router_api.py — HTTP integration tests for GET /api/models/recommend
"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import model_backend, router  # noqa: E402

_ORIG_GENERATE = model_backend.generate

_FAKE_RECOMMEND = {
    "tier": "workstation",
    "tier_reasons": ["4 core + 16GB + SSD"],
    "models": [
        {"name": "qwen2.5-coder:7b", "size_gb": 4.7,
         "description": "โมเดลกลาง coding", "priority": 1, "installed": True},
        {"name": "codellama:7b", "size_gb": 3.8,
         "description": "CodeLlama", "priority": 2, "installed": False},
    ],
    "top_pick": "qwen2.5-coder:7b",
    "ollama_running": True,
    "installed": ["qwen2.5-coder:7b"],
    "cached_until": 9999999999.0,
}


def _mock_recommend(project_root, ollama_base="http://127.0.0.1:11434"):
    return dict(_FAKE_RECOMMEND)


def _make_server(tmp_dir: Path):
    handler = server.make_handler(tmp_dir, None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, handler.session_token


class RouterApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: f"MODEL={model}"
        )
        cls._orig_recommend = router.recommend
        router.recommend = _mock_recommend

    @classmethod
    def tearDownClass(cls):
        model_backend.generate = _ORIG_GENERATE
        router.recommend = cls._orig_recommend

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.httpd, self.port, self.session_token = _make_server(self.root)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = {}
        if token:
            hdrs["X-Auth-Token"] = token
        conn.request("GET", path, headers=hdrs)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, json.loads(body) if body else {}

    def test_recommend_returns_200(self):
        st, _ = self._get("/api/models/recommend", token=self.session_token)
        self.assertEqual(st, 200)

    def test_recommend_shape(self):
        _, data = self._get("/api/models/recommend", token=self.session_token)
        for key in ("tier", "models", "top_pick", "ollama_running", "installed"):
            self.assertIn(key, data, f"missing key: {key}")

    def test_recommend_requires_auth(self):
        st, _ = self._get("/api/models/recommend", token="bad-token-xyz")
        self.assertIn(st, (401, 403))

    def test_recommend_tier_is_string(self):
        _, data = self._get("/api/models/recommend", token=self.session_token)
        self.assertIsInstance(data["tier"], str)

    def test_recommend_models_is_list(self):
        _, data = self._get("/api/models/recommend", token=self.session_token)
        self.assertIsInstance(data["models"], list)
        self.assertGreater(len(data["models"]), 0)

    def test_recommend_top_pick_is_string(self):
        _, data = self._get("/api/models/recommend", token=self.session_token)
        self.assertIsInstance(data["top_pick"], str)

    def test_recommend_ollama_running_is_bool(self):
        _, data = self._get("/api/models/recommend", token=self.session_token)
        self.assertIsInstance(data["ollama_running"], bool)

    def test_recommend_installed_is_list(self):
        _, data = self._get("/api/models/recommend", token=self.session_token)
        self.assertIsInstance(data["installed"], list)


class RouterUnitTest(unittest.TestCase):
    """Unit tests สำหรับ router.recommend() ตรงๆ — ไม่ผ่าน HTTP"""

    def _make_recommend_no_ollama(self, project_root):
        """patch _ollama_installed_models ให้คืน offline"""
        orig = router._ollama_installed_models
        router._ollama_installed_models = lambda base_url=None, timeout=3: (False, [])
        try:
            # flush cache ก่อน
            with router._cache_lock:
                router._cache.clear()
            return router.recommend(project_root)
        finally:
            router._ollama_installed_models = orig

    def test_unit_tier_in_known_tiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._make_recommend_no_ollama(tmp)
        self.assertIn(result["tier"], ("netbook", "workstation", "server", "unknown"))

    def test_unit_ollama_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._make_recommend_no_ollama(tmp)
        self.assertFalse(result["ollama_running"])

    def test_unit_models_have_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._make_recommend_no_ollama(tmp)
        for m in result["models"]:
            self.assertIn("name", m)
            self.assertIn("size_gb", m)
            self.assertIn("priority", m)
            self.assertIn("installed", m)


if __name__ == "__main__":
    unittest.main()
