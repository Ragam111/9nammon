"""Tests for app/cloud_tunnel.py HTTP routes — complements test_cloud_tunnel.py."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
from app import cloud_tunnel


def _reset():
    cloud_tunnel._state.update(
        proc=None, url=None, provider=None, started_at=None, error=None
    )


class TestCloudTunnelRoutes(unittest.TestCase):
    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_status_stopped_returns_running_false(self):
        s = cloud_tunnel.status()
        self.assertFalse(s["running"])
        self.assertIsNone(s["url"])
        self.assertIsNone(s["provider"])

    def test_status_has_required_keys(self):
        s = cloud_tunnel.status()
        for k in ("running", "url", "provider", "started_at", "error"):
            self.assertIn(k, s)

    def test_stop_idempotent(self):
        self.assertFalse(cloud_tunnel.stop())
        self.assertFalse(cloud_tunnel.stop())

    def test_start_missing_cloudflared_returns_error_dict(self):
        with patch.object(cloud_tunnel, "_find", return_value=None):
            r = cloud_tunnel.start(8420, timeout=1.0)
        self.assertFalse(r["running"])
        self.assertIsNone(r["url"])
        self.assertIsNotNone(r["error"])

    def test_start_process_exits_early_returns_error(self):
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = ""
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0
        with patch.object(cloud_tunnel, "_find", return_value="/usr/bin/cloudflared"):
            with patch("subprocess.Popen", return_value=mock_proc):
                r = cloud_tunnel.start(8420, timeout=1.0)
        self.assertFalse(r["running"])
        self.assertIn("exited before", r["error"])

    def test_start_timeout_returns_error(self):
        mock_proc = MagicMock()
        mock_proc.stdout.readline.return_value = "no url here\n"
        mock_proc.poll.return_value = None
        with patch.object(cloud_tunnel, "_find", return_value="/usr/bin/cloudflared"):
            with patch("subprocess.Popen", return_value=mock_proc):
                r = cloud_tunnel.start(8420, timeout=0.01)
        self.assertFalse(r["running"])
        self.assertIn("did not provide URL", r["error"])

    def test_start_returns_url_from_cloudflared_output(self):
        fake_url = "https://test-abc-def.trycloudflare.com"
        mock_proc = MagicMock()
        lines = iter([
            "2026-11-08T00:00:00Z INF Starting tunnel\n",
            f"2026-11-08T00:00:01Z INF | {fake_url} |\n",
        ])
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.poll.return_value = None
        with patch.object(cloud_tunnel, "_find", return_value="/usr/bin/cloudflared"):
            with patch("subprocess.Popen", return_value=mock_proc):
                r = cloud_tunnel.start(8420, timeout=5.0)
        self.assertTrue(r["running"])
        self.assertEqual(r["url"], fake_url)
        self.assertIsNone(r["error"])

    def test_status_running_after_successful_start(self):
        fake_url = "https://abc123.trycloudflare.com"
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = iter([fake_url + "\n"])
        mock_proc.poll.return_value = None
        with patch.object(cloud_tunnel, "_find", return_value="/usr/bin/cloudflared"):
            with patch("subprocess.Popen", return_value=mock_proc):
                cloud_tunnel.start(9000, timeout=5.0)
        s = cloud_tunnel.status()
        self.assertTrue(s["running"])
        self.assertEqual(s["url"], fake_url)
        self.assertEqual(s["provider"], "cloudflare")

    def test_status_stopped_after_stop(self):
        fake_url = "https://abc123.trycloudflare.com"
        mock_proc = MagicMock()
        mock_proc.stdout.readline.side_effect = iter([fake_url + "\n"])
        mock_proc.poll.return_value = None
        with patch.object(cloud_tunnel, "_find", return_value="/usr/bin/cloudflared"):
            with patch("subprocess.Popen", return_value=mock_proc):
                cloud_tunnel.start(9000, timeout=5.0)
        cloud_tunnel.stop()
        s = cloud_tunnel.status()
        self.assertFalse(s["running"])
        self.assertIsNone(s["url"])

    def test_url_regex_only_matches_trycloudflare_domain(self):
        """_CF_URL_RE must only capture https://*.trycloudflare.com."""
        pattern = cloud_tunnel._CF_URL_RE
        self.assertIsNotNone(pattern.search("https://abc-123.trycloudflare.com"))
        self.assertIsNone(pattern.search("https://evil.com"))
        self.assertIsNone(pattern.search("http://abc.trycloudflare.com"))


if __name__ == "__main__":
    unittest.main()
