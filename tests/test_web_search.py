"""test_web_search.py — Brave Search: key validation, mock fetch, format

Covers:
  search_web()               — no key/empty key raise, URLError raises, bad JSON raises,
                               empty results, missing web key, result field shape,
                               max_results cap
  format_results_for_context() — empty input, header line, title/url/snippet in output,
                                  numbered (1./2./…), single item
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from app import web_search  # noqa: E402


def _mock_urlopen(payload: bytes):
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# search_web — key validation
# ---------------------------------------------------------------------------

class TestSearchWebKeyValidation(unittest.TestCase):
    @patch("app.web_search.get_key", return_value=None)
    def test_no_key_raises(self, _mock):
        with self.assertRaises(RuntimeError):
            web_search.search_web("test", Path("/tmp"))

    @patch("app.web_search.get_key", return_value="")
    def test_empty_key_raises(self, _mock):
        with self.assertRaises(RuntimeError):
            web_search.search_web("test", Path("/tmp"))


# ---------------------------------------------------------------------------
# search_web — network errors
# ---------------------------------------------------------------------------

class TestSearchWebNetworkErrors(unittest.TestCase):
    @patch("urllib.request.urlopen",
           side_effect=urllib.error.URLError("connection refused"))
    @patch("app.web_search.get_key", return_value="brave-key")
    def test_url_error_raises_runtime_error(self, _key, _urlopen):
        with self.assertRaises(RuntimeError):
            web_search.search_web("query", Path("/tmp"))

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="brave-key")
    def test_bad_json_raises_runtime_error(self, _key, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(b"not-json")
        with self.assertRaises(RuntimeError):
            web_search.search_web("query", Path("/tmp"))


# ---------------------------------------------------------------------------
# search_web — result shape and content
# ---------------------------------------------------------------------------

class TestSearchWebResults(unittest.TestCase):
    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="brave-key")
    def test_success_returns_list(self, _key, mock_urlopen):
        data = {"web": {"results": [
            {"title": "R1", "url": "https://r1.com", "description": "d1"},
        ]}}
        mock_urlopen.return_value = _mock_urlopen(json.dumps(data).encode())
        results = web_search.search_web("query", Path("/tmp"))
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="brave-key")
    def test_result_has_title_url_snippet(self, _key, mock_urlopen):
        data = {"web": {"results": [
            {"title": "Result 1", "url": "https://example.com", "description": "desc 1"},
        ]}}
        mock_urlopen.return_value = _mock_urlopen(json.dumps(data).encode())
        results = web_search.search_web("query", Path("/tmp"))
        for field in ("title", "url", "snippet"):
            self.assertIn(field, results[0])

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="brave-key")
    def test_description_mapped_to_snippet(self, _key, mock_urlopen):
        data = {"web": {"results": [
            {"title": "T", "url": "u", "description": "my_snippet"},
        ]}}
        mock_urlopen.return_value = _mock_urlopen(json.dumps(data).encode())
        results = web_search.search_web("q", Path("/tmp"))
        self.assertEqual(results[0]["snippet"], "my_snippet")

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="brave-key")
    def test_max_results_capped(self, _key, mock_urlopen):
        items = [{"title": f"R{i}", "url": f"u{i}", "description": f"d{i}"}
                 for i in range(10)]
        data = {"web": {"results": items}}
        mock_urlopen.return_value = _mock_urlopen(json.dumps(data).encode())
        results = web_search.search_web("q", Path("/tmp"))
        self.assertLessEqual(len(results), web_search.MAX_RESULTS)

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="brave-key")
    def test_empty_results_returns_empty_list(self, _key, mock_urlopen):
        data = {"web": {"results": []}}
        mock_urlopen.return_value = _mock_urlopen(json.dumps(data).encode())
        results = web_search.search_web("q", Path("/tmp"))
        self.assertEqual(results, [])

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="brave-key")
    def test_missing_web_key_returns_empty_list(self, _key, mock_urlopen):
        data = {}
        mock_urlopen.return_value = _mock_urlopen(json.dumps(data).encode())
        results = web_search.search_web("q", Path("/tmp"))
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# format_results_for_context
# ---------------------------------------------------------------------------

class TestFormatResults(unittest.TestCase):
    def test_empty_results_message(self):
        out = web_search.format_results_for_context([])
        self.assertIn("ไม่พบผลลัพธ์", out)

    def test_format_includes_title_url_snippet(self):
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

    def test_format_has_header_line(self):
        results = [{"title": "T", "url": "u", "snippet": "s"}]
        out = web_search.format_results_for_context(results)
        lines = out.splitlines()
        self.assertGreater(len(lines), 1)

    def test_format_single_item_no_second_number(self):
        results = [{"title": "T", "url": "u", "snippet": "s"}]
        out = web_search.format_results_for_context(results)
        self.assertIn("1.", out)
        self.assertNotIn("2.", out)


if __name__ == "__main__":
    unittest.main()
