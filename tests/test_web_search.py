"""test_web_search.py — Brave Search: key validation, mock fetch, format

Covers:
  SearchWebKeyTest    — no key raises, empty key raises
  SearchWebMockTest   — success returns results, max_results capped, network error raises,
                        URL error raises RuntimeError, result dict has required fields,
                        empty web results returns empty list, missing description handled
  FormatResultsTest   — empty results, includes title+url+snippet, numbered, single result,
                        multi-result header present, result index starts at 1
  WebSearchMetaTest   — MAX_RESULTS positive int, BRAVE_SEARCH_URL is https,
                        format returns str
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


def _mock_urlopen(resp_data: dict):
    """helper: สร้าง mock urlopen ที่คืน resp_data เป็น JSON"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


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
        mock_urlopen.return_value = _mock_urlopen(resp_data)

        results = web_search.search_web("python tutorial", Path("/tmp"))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Result 1")
        self.assertEqual(results[0]["snippet"], "desc 1")

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="key")
    def test_max_results_capped(self, _mock_key, mock_urlopen):
        items = [{"title": f"R{i}", "url": f"https://r{i}.com", "description": f"d{i}"}
                 for i in range(10)]
        mock_urlopen.return_value = _mock_urlopen({"web": {"results": items}})

        results = web_search.search_web("query", Path("/tmp"))
        self.assertLessEqual(len(results), web_search.MAX_RESULTS)

    @patch("app.web_search.get_key", return_value="key")
    def test_network_error_raises_runtime(self, _mock_key):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("connection refused")):
            with self.assertRaises(RuntimeError):
                web_search.search_web("fail", Path("/tmp"))

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="key")
    def test_result_dict_has_required_fields(self, _mock_key, mock_urlopen):
        resp_data = {"web": {"results": [
            {"title": "T", "url": "https://x.com", "description": "d"}
        ]}}
        mock_urlopen.return_value = _mock_urlopen(resp_data)
        results = web_search.search_web("q", Path("/tmp"))
        self.assertEqual(len(results), 1)
        for field in ("title", "url", "snippet"):
            self.assertIn(field, results[0], f"result ต้องมี field: {field}")

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="key")
    def test_empty_web_results_returns_empty_list(self, _mock_key, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({"web": {"results": []}})
        results = web_search.search_web("empty", Path("/tmp"))
        self.assertEqual(results, [])

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="key")
    def test_missing_description_uses_empty_string(self, _mock_key, mock_urlopen):
        # description อาจไม่มีใน response → ต้องไม่ crash, snippet = ""
        resp_data = {"web": {"results": [{"title": "T", "url": "u"}]}}
        mock_urlopen.return_value = _mock_urlopen(resp_data)
        results = web_search.search_web("q", Path("/tmp"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["snippet"], "")

    @patch("urllib.request.urlopen")
    @patch("app.web_search.get_key", return_value="key")
    def test_missing_web_key_returns_empty_list(self, _mock_key, mock_urlopen):
        # response ไม่มี "web" key
        mock_urlopen.return_value = _mock_urlopen({})
        results = web_search.search_web("q", Path("/tmp"))
        self.assertEqual(results, [])


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

    def test_format_single_result(self):
        results = [{"title": "Only", "url": "https://only.com", "snippet": "one"}]
        out = web_search.format_results_for_context(results)
        self.assertIn("1.", out)
        self.assertNotIn("2.", out)

    def test_format_has_header(self):
        results = [{"title": "T", "url": "u", "snippet": "s"}]
        out = web_search.format_results_for_context(results)
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 10)

    def test_format_returns_string(self):
        out = web_search.format_results_for_context([])
        self.assertIsInstance(out, str)


class WebSearchMetaTest(unittest.TestCase):
    def test_max_results_is_positive_int(self):
        self.assertIsInstance(web_search.MAX_RESULTS, int)
        self.assertGreater(web_search.MAX_RESULTS, 0)

    def test_brave_search_url_is_https(self):
        self.assertTrue(web_search.BRAVE_SEARCH_URL.startswith("https://"))

    def test_search_raises_runtime_not_bare_exception(self):
        with patch("app.web_search.get_key", return_value=None):
            try:
                web_search.search_web("q", Path("/tmp"))
                self.fail("ต้อง raise RuntimeError")
            except RuntimeError:
                pass
            except Exception as e:
                self.fail(f"ต้อง raise RuntimeError ไม่ใช่ {type(e).__name__}")


if __name__ == "__main__":
    unittest.main()
