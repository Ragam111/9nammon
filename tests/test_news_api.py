"""
test_news_api.py — HTTP integration tests for GET /api/news
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

    def test_news_requires_auth(self):
        st, _ = self._get("/api/news", token="bad-token-xyz")
        self.assertIn(st, (401, 403), f"ต้องได้ 401/403 ด้วย token ผิด แต่ได้ {st}")

    def test_news_count_matches_articles(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertEqual(data["count"], len(data["articles"]))

    def test_news_articles_have_required_fields(self):
        _, data = self._get("/api/news", token=self.session_token)
        self.assertGreater(len(data["articles"]), 0)
        article = data["articles"][0]
        for field in ("title", "link", "pubDate", "source"):
            self.assertIn(field, article, f"missing field: {field}")


class NewsApiExtraTest(unittest.TestCase):
    def setUp(self):
        self._orig_fetch = news_store._fetch_feed
        news_store._fetch_feed = _mock_fetch
        news_store._cache.clear()

    def tearDown(self):
        news_store._fetch_feed = self._orig_fetch
        news_store._cache.clear()

    def test_get_news_returns_dict(self):
        result = news_store.get_news(["mock://feed"])
        self.assertIsInstance(result, dict)

    def test_get_news_has_articles_key(self):
        result = news_store.get_news(["mock://feed"])
        self.assertIn("articles", result)

    def test_get_news_count_is_int(self):
        result = news_store.get_news(["mock://feed"])
        self.assertIsInstance(result["count"], int)

    def test_get_news_errors_is_list(self):
        result = news_store.get_news(["mock://feed"])
        self.assertIsInstance(result["errors"], list)

    def test_get_news_feeds_is_int(self):
        result = news_store.get_news(["mock://feed"])
        self.assertIsInstance(result["feeds"], int)

    def test_mock_fetch_returns_two_articles(self):
        articles = _mock_fetch("mock://feed")
        self.assertEqual(len(articles), 2)


if __name__ == "__main__":
    unittest.main()
