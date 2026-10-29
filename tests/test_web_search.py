"""test_web_search.py — Brave Search: key validation, mock fetch, format"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from app import web_search  # noqa: E402


class SearchWebKeyTest(unittest.TestCase):
    @patch("app.web_search.get_key", return_value=None)
    def test_no_key_raises(self, _mock):
        with self.assertRaises(RuntimeError):
            web_search.search_web("test", Path("/tmp"))

    @patch("app.web_search.get_key", return_value="")
    def test_empty_key_raises(self, _mock):
        with self.assertRaises(RuntimeError):
            web_search.search_web("test", Path("/tmp"))


class SearchWebMockTest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="brave-test-key")
    def test_success_returns_results(self, _mock_key, mock_urlopen):
        resp_data = {"web": {"results": [
            {"title": "Result 1", "url": "https://example.com", "description": "desc 1"},
            {"title": "Result 2", "url": "https://example.org", "description": "desc 2"},
        ]}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = web_search.search_web("python tutorial", Path("/tmp"))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Result 1")
        self.assertEqual(results[0]["snippet"], "desc 1")

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="key")
    def test_max_results_capped(self, _mock_key, mock_urlopen):
        items = [{"title": f"R{i}", "url": f"https://r{i}.com", "description": f"d{i}"}
                 for i in range(10)]
        resp_data = {"web": {"results": items}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        results = web_search.search_web("query", Path("/tmp"))
        self.assertLessEqual(len(results), web_search.MAX_RESULTS)


class FormatResultsTest(unittest.TestCase):
    def test_empty_results(self):
        out = web_search.format_results_for_context([])
        self.assertIn("ไม่พบผลลัพธ์", out)

    def test_format_includes_title_and_url(self):
        results = [{"title": "Title", "url": "https://x.com", "snippet": "snip"}]
        out = web_search.format_results_for_context(results)
        self.assertIn("Title", out)
        self.assertIn("https://x.com", out)
        self.assertIn("snip", out)

    def test_format_numbered(self):
        results = [
            {"title": "A", "url": "u1", "snippet": "s1"},
            {"title": "B", "url": "u2", "snippet": "s2"},
        ]
        out = web_search.format_results_for_context(results)
        self.assertIn("1.", out)
        self.assertIn("2.", out)


if __name__ == "__main__":
    unittest.main()
