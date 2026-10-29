"""test_tavily_search.py — Tavily Search: key validation, mock fetch, format"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from app import tavily_search  # noqa: E402


class SearchWebKeyTest(unittest.TestCase):
    @patch("app.tavily_search.get_key", return_value=None)
    def test_no_key_raises(self, _mock):
        with self.assertRaises(RuntimeError):
            tavily_search.search_web("test", Path("/tmp"))

    @patch("app.tavily_search.get_key", return_value="")
    def test_empty_key_raises(self, _mock):
        with self.assertRaises(RuntimeError):
            tavily_search.search_web("test", Path("/tmp"))


class SearchWebMockTest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    @patch("app.tavily_search.get_key", return_value="tvly-test-key")
    def test_success_returns_results(self, _mock_key, mock_urlopen):
        resp_data = {"results": [
            {"title": "Tavily 1", "url": "https://tavily.com/1", "content": "content 1"},
            {"title": "Tavily 2", "url": "https://tavily.com/2", "content": "content 2"},
        ]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = tavily_search.search_web("python", Path("/tmp"))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Tavily 1")
        self.assertEqual(results[0]["snippet"], "content 1")

    @patch("urllib.request.urlopen")
    @patch("app.tavily_search.get_key", return_value="key")
    def test_max_results_capped(self, _mock_key, mock_urlopen):
        items = [{"title": f"T{i}", "url": f"https://t{i}.com", "content": f"c{i}"}
                 for i in range(10)]
        resp_data = {"results": items}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = tavily_search.search_web("query", Path("/tmp"))
        self.assertLessEqual(len(results), tavily_search.MAX_RESULTS)

    @patch("urllib.request.urlopen")
    @patch("app.tavily_search.get_key", return_value="key")
    def test_malformed_json_raises(self, _mock_key, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"NOT JSON"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        with self.assertRaises(RuntimeError):
            tavily_search.search_web("query", Path("/tmp"))


class FormatResultsTest(unittest.TestCase):
    def test_empty_results(self):
        out = tavily_search.format_results_for_context([])
        self.assertIn("ไม่พบผลลัพธ์", out)

    def test_format_includes_title_and_url(self):
        results = [{"title": "Title", "url": "https://x.com", "snippet": "snip"}]
        out = tavily_search.format_results_for_context(results)
        self.assertIn("Title", out)
        self.assertIn("https://x.com", out)
        self.assertIn("snip", out)

    def test_format_mentions_tavily(self):
        results = [{"title": "A", "url": "u", "snippet": "s"}]
        out = tavily_search.format_results_for_context(results)
        self.assertIn("Tavily", out)


if __name__ == "__main__":
    unittest.main()
