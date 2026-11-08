"""Tests for app/cloud_tunnel.py and /api/admin/tunnel/* routes."""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
from app import cloud_tunnel


# ---------------------------------------------------------------------------
# Unit tests for cloud_tunnel module
# ---------------------------------------------------------------------------

class TestCloudTunnelStatus(unittest.TestCase):
    def setUp(self):
        cloud_tunnel.stop()

    def tearDown(self):
        cloud_tunnel.stop()

    def test_status_stopped_returns_running_false(self):
        s = cloud_tunnel.status()
        self.assertFalse(s["running"])
        self.assertIsNone(s["url"])
        self.assertIsNone(s["port"])

    def test_status_has_required_keys(self):
        s = cloud_tunnel.status()
        self.assertIn("running", s)
        self.assertIn("url", s)
        self.assertIn("port", s)

    def test_stop_idempotent(self):
        cloud_tunnel.stop()
        cloud_tunnel.stop()  # should not raise

    def test_start_missing_cloudflared_raises(self):
        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError) as ctx:
                cloud_tunnel.start(8420, timeout=1.0)
        self.assertIn("cloudflared not found", str(ctx.exception))

    def test_start_process_exits_early_raises(self):
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = ""  # EOF immediately
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0
        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(RuntimeError) as ctx:
                cloud_tunnel.start(8420, timeout=1.0)
        self.assertIn("exited before", str(ctx.exception))

    def test_start_timeout_raises(self):
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = "no url here\n"
        mock_proc.poll.return_value = None
        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(RuntimeError) as ctx:
                cloud_tunnel.start(8420, timeout=0.01)
        self.assertIn("did not provide URL", str(ctx.exception))

    def test_start_returns_url_from_cloudflared_output(self):
        fake_url = "https://test-abc-def.trycloudflare.com"
        mock_proc = MagicMock()
        lines = iter([
            "2026-11-08T00:00:00Z INF Starting tunnel\n",
            f"2026-11-08T00:00:01Z INF | {fake_url} |\n",
        ])
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.poll.return_value = None
        with patch("subprocess.Popen", return_value=mock_proc):
            url = cloud_tunnel.start(8420, timeout=5.0)
        self.assertEqual(url, fake_url)

    def test_status_running_after_successful_start(self):
        fake_url = "https://abc123.trycloudflare.com"
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = iter([fake_url + "\n"])
        mock_proc.poll.return_value = None
        with patch("subprocess.Popen", return_value=mock_proc):
            cloud_tunnel.start(9000, timeout=5.0)
        s = cloud_tunnel.status()
        self.assertTrue(s["running"])
        self.assertEqual(s["url"], fake_url)
        self.assertEqual(s["port"], 9000)

    def test_status_stopped_after_stop(self):
        fake_url = "https://abc123.trycloudflare.com"
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = iter([fake_url + "\n"])
        mock_proc.poll.return_value = None
        with patch("subprocess.Popen", return_value=mock_proc):
            cloud_tunnel.start(9000, timeout=5.0)
        cloud_tunnel.stop()
        s = cloud_tunnel.status()
        self.assertFalse(s["running"])
        self.assertIsNone(s["url"])

    def test_url_only_matches_trycloudflare_domain(self):
        """URL regex must only capture *.trycloudflare.com, not other hosts."""
        import re
        pattern = cloud_tunnel._URL_RE
        self.assertIsNotNone(pattern.search("https://abc-123.trycloudflare.com"))
        self.assertIsNone(pattern.search("https://evil.com"))
        self.assertIsNone(pattern.search("http://abc.trycloudflare.com"))  # must be https


if __name__ == "__main__":
    unittest.main()
