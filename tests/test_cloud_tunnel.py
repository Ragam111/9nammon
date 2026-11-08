"""test_cloud_tunnel.py — unit tests for app/cloud_tunnel.py

All subprocess calls are mocked — no real cloudflared needed.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cloud_tunnel  # noqa: E402


def _reset():
    """Reset module-level state between tests."""
    cloud_tunnel._state.update(
        proc=None, url=None, provider=None, started_at=None, error=None
    )


class CloudTunnelTest(unittest.TestCase):

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    # --- status() ---

    def test_status_not_running_by_default(self):
        self.assertFalse(cloud_tunnel.status()["running"])

    def test_status_url_none_when_stopped(self):
        self.assertIsNone(cloud_tunnel.status()["url"])

    def test_status_provider_none_when_stopped(self):
        self.assertIsNone(cloud_tunnel.status()["provider"])

    def test_status_has_required_keys(self):
        s = cloud_tunnel.status()
        for k in ("running", "url", "provider", "started_at", "error"):
            self.assertIn(k, s)

    # --- stop() ---

    def test_stop_false_when_not_running(self):
        self.assertFalse(cloud_tunnel.stop())

    def test_stop_terminates_proc(self):
        fake = MagicMock()
        fake.poll.return_value = None
        cloud_tunnel._state.update(
            proc=fake, url="https://x.trycloudflare.com",
            provider="cloudflare", started_at=1.0, error=None,
        )
        self.assertTrue(cloud_tunnel.stop())
        fake.terminate.assert_called_once()

    # --- start() ---

    def test_start_no_binary_returns_error(self):
        with patch.object(cloud_tunnel, "_find", return_value=None):
            r = cloud_tunnel.start(8420)
        self.assertIsNone(r["url"])
        self.assertIsNotNone(r["error"])

    def test_start_returns_dict(self):
        with patch.object(cloud_tunnel, "_find", return_value=None):
            r = cloud_tunnel.start(8420)
        self.assertIsInstance(r, dict)

    def test_start_already_running_returns_cached(self):
        fake = MagicMock()
        fake.poll.return_value = None
        cloud_tunnel._state.update(
            proc=fake, url="https://test.trycloudflare.com",
            provider="cloudflare", started_at=1.0, error=None,
        )
        r = cloud_tunnel.start(8420)
        self.assertEqual(r["url"], "https://test.trycloudflare.com")
        self.assertIsNone(r["error"])

    # --- helper: _find ---

    def test_find_returns_none_for_nonexistent(self):
        self.assertIsNone(cloud_tunnel._find("__nonexistent_xyz_123__"))

    # --- helper: _CF_URL_RE ---

    def test_regex_matches_trycloudflare_url(self):
        m = cloud_tunnel._CF_URL_RE.search(
            "2026 INFO https://abc-def.trycloudflare.com registered"
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.group(0), "https://abc-def.trycloudflare.com")

    # --- status() with live proc ---

    def test_status_running_when_proc_alive(self):
        fake = MagicMock()
        fake.poll.return_value = None
        cloud_tunnel._state.update(
            proc=fake, url="https://y.trycloudflare.com",
            provider="cloudflare", started_at=99.0, error=None,
        )
        s = cloud_tunnel.status()
        self.assertTrue(s["running"])
        self.assertEqual(s["url"], "https://y.trycloudflare.com")

    def test_status_not_running_when_proc_dead(self):
        fake = MagicMock()
        fake.poll.return_value = 1
        cloud_tunnel._state.update(
            proc=fake, url="https://z.trycloudflare.com",
            provider="cloudflare", started_at=99.0, error=None,
        )
        s = cloud_tunnel.status()
        self.assertFalse(s["running"])
        self.assertIsNone(s["url"])


if __name__ == "__main__":
    unittest.main()
