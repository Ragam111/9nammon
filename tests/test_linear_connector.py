"""test_linear_connector.py — API key validation, update gate, mock fetch"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import linear_connector  # noqa: E402


class GetApiKeyTest(unittest.TestCase):
    def test_missing_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LINEAR_API_KEY", None)
            with self.assertRaises(RuntimeError):
                linear_connector._get_api_key()

    def test_empty_key_raises(self):
        with patch.dict(os.environ, {"LINEAR_API_KEY": "   "}):
            with self.assertRaises(RuntimeError):
                linear_connector._get_api_key()

    def test_valid_key_returned(self):
        with patch.dict(os.environ, {"LINEAR_API_KEY": "lin_test_key"}):
            self.assertEqual(linear_connector._get_api_key(), "lin_test_key")


class FetchMyIssuesTest(unittest.TestCase):
    def test_no_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LINEAR_API_KEY", None)
            with self.assertRaises(RuntimeError):
                linear_connector.fetch_my_issues()

    @patch("urllib.request.urlopen")
    def test_success_returns_nodes(self, mock_urlopen):
        nodes = [
            {"identifier": "ENG-1", "title": "Fix bug", "url": "https://linear.app/1",
             "state": {"name": "In Progress"}},
        ]
        resp_data = {"data": {"viewer": {"assignedIssues": {"nodes": nodes}}}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        with patch.dict(os.environ, {"LINEAR_API_KEY": "test-key"}):
            result = linear_connector.fetch_my_issues()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["identifier"], "ENG-1")

    @patch("urllib.request.urlopen")
    def test_api_errors_raise(self, mock_urlopen):
        resp_data = {"errors": [{"message": "Unauthorized"}]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        with patch.dict(os.environ, {"LINEAR_API_KEY": "test-key"}):
            with self.assertRaises(RuntimeError):
                linear_connector.fetch_my_issues()

    @patch("urllib.request.urlopen")
    def test_malformed_json_raises(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"NOT JSON"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        with patch.dict(os.environ, {"LINEAR_API_KEY": "test-key"}):
            with self.assertRaises(RuntimeError):
                linear_connector.fetch_my_issues()


class UpdateIssueStatusTest(unittest.TestCase):
    def test_no_confirm_raises(self):
        with self.assertRaises(RuntimeError):
            linear_connector.update_issue_status("ENG-1", "state-id")

    def test_confirm_false_raises(self):
        with self.assertRaises(RuntimeError):
            linear_connector.update_issue_status("ENG-1", "state-id", confirm=False)

    def test_confirm_true_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            linear_connector.update_issue_status("ENG-1", "state-id", confirm=True)


if __name__ == "__main__":
    unittest.main()
