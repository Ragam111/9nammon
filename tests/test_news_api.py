"""
test_news_api.py — HTTP integration tests for GET /api/news

ตรวจว่า server คืนข่าว RSS ถูกต้อง:
- 200 + โครงข้อมูล, RBAC, field types
- articles มี required fields, count ตรง, cache ทำงาน
- feeds/errors/cached_until types ถูกต้อง
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
from app import model_backend, news_store  # noqa: E402

_FAKE_ARTICLES = [
    {"title": "Test Article", "link": "http://example.com/1",
     "pubDate": "Mon, 04 Nov 2026 00:00:00 GMT", "source": "mock://feed"},
    {"title": "Second Article", "link": "http://example.com/2",
     "pubDate": "Mon, 04 Nov 2026 00:00:00 GMT", "source": "mock://feed"},
]

_ORIG_FETCH = news_store._fetch_feed
_ORIG_GENERATE = model_backend.generate


def _mock_fetch(url: str, timeout: int = 10) -> list:
    return list(_FAKE_ARTICLES)


def _make_server(tmp_dir: Path):
    handler = server.make_handler(tmp_dir, None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, handler.session_token


class NewsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: f"MODEL={model}"
        )
        news_store._fetch_feed = _mock_fetch

    @classmethod
    def tearDownClass(cls):
        model_backend.generate = _ORIG_GENERATE
        news_store._fetch_feed = _ORIG_FETCH

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.httpd, self.port, self.session_token = _make_server(self.root)
        news_store._cache.clear()

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

    # ── basic 200 + shape ───────────────────────────────────────────────────

    def test_news_returns_200(self):
        st, _ = self._get("/api/news", token=self.session_token)
        self.assertEqual(st, 200)

    def test_news_shape(self):
        _, data = self._get("/api/news", token=self.session_token)
        for key in ("articles", "count", "feeds", "errors", "cached_until"):
            self.assertIn(key, data, f"missing key: {key}")

    def test_news_articles_is_list(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertIsInstance(data["articles"], list)

    # ── RBAC ────────────────────────────────────────────────────────────────

    def test_news_requires_auth(self):
        st, _ = self._get("/api/news", token="bad-token-xyz")
        self.assertIn(st, (401, 403), f"ต้องได้ 401/403 ด้วย token ผิด แต่ได้ {st}")

    def test_news_bad_token_gets_error(self):
        st, data = self._get("/api/news", token="wrong-token")
        self.assertIn(st, (401, 403))

    # ── content ─────────────────────────────────────────────────────────────

    def test_news_count_matches_articles(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertEqual(data["count"], len(data["articles"]))

    def test_news_articles_have_required_fields(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertGreater(len(data["articles"]), 0)
        article = data["articles"][0]
        for field in ("title", "link", "pubDate", "source"):
            self.assertIn(field, article, f"missing field: {field}")

    def test_news_count_at_least_fake_articles(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertGreaterEqual(data["count"], len(_FAKE_ARTICLES))

    def test_news_articles_title_is_nonempty_string(self):
        _, data = self._get("/api/news", token=self.session_token)
        article = data["articles"][0]
        self.assertIsInstance(article["title"], str)
        self.assertGreater(len(article["title"]), 0)

    def test_news_articles_link_is_nonempty_string(self):
        _, data = self._get("/api/news", token=self.session_token)
        article = data["articles"][0]
        self.assertIsInstance(article["link"], str)
        self.assertGreater(len(article["link"]), 0)

    # ── field types ─────────────────────────────────────────────────────────

    def test_news_feeds_is_list_or_int(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertIsInstance(data["feeds"], (list, int))

    def test_news_errors_is_list(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertIsInstance(data["errors"], list)

    def test_news_cached_until_is_number(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertIsInstance(data["cached_until"], (int, float))

    def test_news_count_is_int(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertIsInstance(data["count"], int)

    # ── cache ────────────────────────────────────────────────────────────────

    def test_news_second_call_returns_same_count(self):
        _, first = self._get("/api/news", token=self.session_token)
        _, second = self._get("/api/news", token=self.session_token)
        self.assertEqual(first["count"], second["count"])


if __name__ == "__main__":
    unittest.main()
