"""test_tavily_search.py — Tavily Search: key validation, mock fetch, format

Covers:
  SearchWebKeyTest    — no key raises, empty key raises
  SearchWebMockTest   — success returns results, max_results capped, malformed json raises,
                        network error raises RuntimeError, result dict has required fields,
                        empty results returns [], missing content uses empty string
  FormatResultsTest   — empty results, includes title+url+snippet, mentions Tavily,
                        numbered, single result, returns str
  TavilyMetaTest      — MAX_RESULTS positive int, TAVILY_SEARCH_URL is https,
                        format returns str for empty, format numbered both items
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from app import tavily_search  # noqa: E402


def _mock_urlopen(resp_data: dict):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


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
        mock_urlopen.return_value = _mock_urlopen(resp_data)

        results = tavily_search.search_web("python", Path("/tmp"))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Tavily 1")
        self.assertEqual(results[0]["snippet"], "content 1")

    @patch("urllib.request.urlopen")
    @patch("app.tavily_search.get_key", return_value="key")
    def test_max_results_capped(self, _mock_key, mock_urlopen):
        items = [{"title": f"T{i}", "url": f"https://t{i}.com", "content": f"c{i}"}
                 for i in range(10)]
        mock_urlopen.return_value = _mock_urlopen({"results": items})

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

    @patch("app.tavily_search.get_key", return_value="key")
    def test_network_error_raises_runtime(self, _mock_key):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("connection refused")):
            with self.assertRaises(RuntimeError):
                tavily_search.search_web("fail", Path("/tmp"))

    @patch("urllib.request.urlopen")
    @patch("app.tavily_search.get_key", return_value="key")
    def test_result_dict_has_required_fields(self, _mock_key, mock_urlopen):
        resp_data = {"results": [
            {"title": "T", "url": "https://x.com", "content": "c"}
        ]}
        mock_urlopen.return_value = _mock_urlopen(resp_data)
        results = tavily_search.search_web("q", Path("/tmp"))
        self.assertEqual(len(results), 1)
        for field in ("title", "url", "snippet"):
            self.assertIn(field, results[0], f"result ต้องมี field: {field}")

    @patch("urllib.request.urlopen")
    @patch("app.tavily_search.get_key", return_value="key")
    def test_empty_results_returns_empty_list(self, _mock_key, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({"results": []})
        results = tavily_search.search_web("empty", Path("/tmp"))
        self.assertEqual(results, [])

    @patch("urllib.request.urlopen")
    @patch("app.tavily_search.get_key", return_value="key")
    def test_missing_content_uses_empty_string(self, _mock_key, mock_urlopen):
        resp_data = {"results": [{"title": "T", "url": "u"}]}
        mock_urlopen.return_value = _mock_urlopen(resp_data)
        results = tavily_search.search_web("q", Path("/tmp"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["snippet"], "")


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

    def test_format_numbered(self):
        results = [
            {"title": "A", "url": "u1", "snippet": "s1"},
            {"title": "B", "url": "u2", "snippet": "s2"},
        ]
        out = tavily_search.format_results_for_context(results)
        self.assertIn("1.", out)
        self.assertIn("2.", out)

    def test_format_single_result(self):
        results = [{"title": "Only", "url": "https://only.com", "snippet": "one"}]
        out = tavily_search.format_results_for_context(results)
        self.assertIn("1.", out)

    def test_format_returns_string(self):
        out = tavily_search.format_results_for_context([])
        self.assertIsInstance(out, str)


class TavilyMetaTest(unittest.TestCase):
    def test_max_results_is_positive_int(self):
        self.assertIsInstance(tavily_search.MAX_RESULTS, int)
        self.assertGreater(tavily_search.MAX_RESULTS, 0)

    def test_tavily_search_url_is_https(self):
        self.assertTrue(tavily_search.TAVILY_SEARCH_URL.startswith("https://"))

    def test_search_raises_runtime_not_bare_exception(self):
        with patch("app.tavily_search.get_key", return_value=None):
            try:
                tavily_search.search_web("q", Path("/tmp"))
                self.fail("ต้อง raise RuntimeError")
            except RuntimeError:
                pass
            except Exception as e:
                self.fail(f"ต้อง raise RuntimeError ไม่ใช่ {type(e).__name__}")


if __name__ == "__main__":
    unittest.main()
