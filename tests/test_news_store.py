"""Unit tests for app/news_store.py — RSS feed fetcher with 15-min cache."""

import time
import unittest
from unittest.mock import MagicMock, patch

import app.news_store as news_store
from app.news_store import _fetch_feed, get_news


# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

_RSS_ONE_ITEM = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Test Article</title>
      <link>https://example.com/article1</link>
      <pubDate>Wed, 05 Nov 2026 04:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""

_RSS_NO_TITLE = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <link>https://example.com/no-title</link>
    </item>
  </channel>
</rss>"""

_ATOM_ONE_ENTRY = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom Title</title>
    <link href="https://example.com/atom1"/>
    <published>2026-11-05T04:00:00Z</published>
  </entry>
</feed>"""

_items_xml = "".join(
    f"<item><title>Item {i}</title><link>https://x.com/{i}</link></item>"
    for i in range(25)
)
_RSS_MANY_ITEMS = (
    f'<?xml version="1.0"?><rss version="2.0"><channel>{_items_xml}</channel></rss>'
).encode()


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------

def _mock_urlopen(data: bytes):
    """Return a context-manager mock whose .read() yields data."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    cm.read = MagicMock(return_value=data)
    return cm


# ---------------------------------------------------------------------------
# _fetch_feed
# ---------------------------------------------------------------------------

class TestFetchFeed(unittest.TestCase):
    def test_returns_list_on_success(self):
        with patch("app.news_store.urlopen", return_value=_mock_urlopen(_RSS_ONE_ITEM)):
            result = _fetch_feed("https://example.com/feed")
        self.assertIsInstance(result, list)

    def test_returns_empty_on_network_error(self):
        with patch("app.news_store.urlopen", side_effect=OSError("timeout")):
            result = _fetch_feed("https://example.com/feed")
        self.assertEqual(result, [])

    def test_returns_empty_on_parse_error(self):
        with patch("app.news_store.urlopen", return_value=_mock_urlopen(b"not xml")):
            result = _fetch_feed("https://example.com/feed")
        self.assertEqual(result, [])

    def test_article_has_required_keys(self):
        with patch("app.news_store.urlopen", return_value=_mock_urlopen(_RSS_ONE_ITEM)):
            result = _fetch_feed("https://example.com/feed")
        self.assertEqual(len(result), 1)
        for key in ("title", "link", "pubDate", "source"):
            self.assertIn(key, result[0])

    def test_article_title_correct(self):
        with patch("app.news_store.urlopen", return_value=_mock_urlopen(_RSS_ONE_ITEM)):
            result = _fetch_feed("https://example.com/feed")
        self.assertEqual(result[0]["title"], "Test Article")

    def test_article_source_is_url(self):
        url = "https://example.com/feed"
        with patch("app.news_store.urlopen", return_value=_mock_urlopen(_RSS_ONE_ITEM)):
            result = _fetch_feed(url)
        self.assertEqual(result[0]["source"], url)

    def test_skips_item_without_title(self):
        with patch("app.news_store.urlopen", return_value=_mock_urlopen(_RSS_NO_TITLE)):
            result = _fetch_feed("https://example.com/feed")
        self.assertEqual(result, [])

    def test_caps_at_20_articles(self):
        with patch("app.news_store.urlopen", return_value=_mock_urlopen(_RSS_MANY_ITEMS)):
            result = _fetch_feed("https://example.com/feed")
        self.assertLessEqual(len(result), 20)

    def test_parses_atom_feed(self):
        with patch("app.news_store.urlopen", return_value=_mock_urlopen(_ATOM_ONE_ENTRY)):
            result = _fetch_feed("https://example.com/atom")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Atom Title")


# ---------------------------------------------------------------------------
# get_news
# ---------------------------------------------------------------------------

class TestGetNews(unittest.TestCase):
    def setUp(self):
        news_store._cache.clear()

    def test_returns_dict(self):
        with patch("app.news_store._fetch_feed", return_value=[]):
            result = get_news(["https://example.com/feed"])
        self.assertIsInstance(result, dict)

    def test_has_required_keys(self):
        with patch("app.news_store._fetch_feed", return_value=[]):
            result = get_news(["https://example.com/feed"])
        for key in ("articles", "count", "feeds", "errors", "cached_until"):
            self.assertIn(key, result)

    def test_count_matches_articles(self):
        article = {"title": "T", "link": "https://x.com", "pubDate": "", "source": "u"}
        with patch("app.news_store._fetch_feed", return_value=[article]):
            result = get_news(["https://example.com/feed"])
        self.assertEqual(result["count"], len(result["articles"]))

    def test_feeds_count_matches_input(self):
        with patch("app.news_store._fetch_feed", return_value=[]):
            result = get_news(["https://a.com/f", "https://b.com/f"])
        self.assertEqual(result["feeds"], 2)

    def test_cached_until_is_int(self):
        with patch("app.news_store._fetch_feed", return_value=[]):
            result = get_news(["https://example.com/feed"])
        self.assertIsInstance(result["cached_until"], int)

    def test_cached_until_in_future(self):
        with patch("app.news_store._fetch_feed", return_value=[]):
            result = get_news(["https://example.com/feed"])
        self.assertGreater(result["cached_until"], int(time.time()))

    def test_failed_feed_url_in_errors(self):
        url = "https://example.com/bad"
        with patch("app.news_store._fetch_feed", return_value=[]):
            result = get_news([url])
        self.assertIn(url, result["errors"])

    def test_successful_feed_not_in_errors(self):
        url = "https://example.com/good"
        article = {"title": "T", "link": "u", "pubDate": "", "source": url}
        with patch("app.news_store._fetch_feed", return_value=[article]):
            result = get_news([url])
        self.assertNotIn(url, result["errors"])

    def test_cache_hit_skips_fetch(self):
        url = "https://example.com/cached"
        article = {"title": "Cached", "link": "u", "pubDate": "", "source": url}
        news_store._cache[url] = (time.time(), [article])
        with patch("app.news_store._fetch_feed") as mock_fetch:
            result = get_news([url])
            mock_fetch.assert_not_called()
        self.assertEqual(result["count"], 1)

    def test_none_feeds_uses_default(self):
        with patch("app.news_store._fetch_feed", return_value=[]):
            result = get_news(None)
        self.assertEqual(result["feeds"], len(news_store.DEFAULT_FEEDS))


if __name__ == "__main__":
    unittest.main()
