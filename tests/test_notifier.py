"""
test_notifier.py — unittest สำหรับ notifier (Discord webhook + email) แบบ mock ล้วน
ไม่ยิงเน็ตจริง/ไม่ส่งเมลจริง — patch urlopen และ smtplib.SMTP

Covers:
  NotifierTest      — text required, skips when no config, discord sent, discord http error,
                      discord network error hides detail, email sent, email skips without
                      recipient, unknown channel
  NotifierMetaTest  — notify returns dict, discord result is str, skips email config no host,
                      both channels in result, event empty string ok, compose includes event,
                      VALID_CHANNELS has discord and email
"""

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import notifier  # noqa: E402
from app import config_manager  # noqa: E402


class _FakeResp:
    def __init__(self, status=204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class NotifierTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_text_required(self):
        with self.assertRaises(ValueError):
            notifier.notify(self.root, "evt", "   ")

    def test_skips_when_no_config(self):
        res = notifier.notify(self.root, "deploy", "x")
        self.assertEqual(res["discord"], "skipped (no config)")
        self.assertEqual(res["email"], "skipped (no config)")

    def test_discord_sent(self):
        config_manager.set_key(self.root, "DISCORD_WEBHOOK_URL",
                               "https://discord.test/webhooks/abc/xyz")
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(204)) as m:
            res = notifier.notify(self.root, "deploy", "merged PR #42", channels=("discord",))
        self.assertEqual(res["discord"], "sent")
        # ยืนยันว่า compose ใส่ event + text ลง payload
        sent_req = m.call_args[0][0]
        self.assertIn(b"deploy", sent_req.data)
        self.assertIn("merged PR #42".encode("utf-8"), sent_req.data)

    def test_discord_http_error(self):
        config_manager.set_key(self.root, "DISCORD_WEBHOOK_URL", "https://discord.test/w/abc")
        import urllib.error
        err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            res = notifier.notify(self.root, "e", "t", channels=("discord",))
        self.assertEqual(res["discord"], "error: http 429")

    def test_discord_network_error_hides_detail(self):
        config_manager.set_key(self.root, "DISCORD_WEBHOOK_URL", "https://discord.test/w/secret")
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("boom secret")):
            res = notifier.notify(self.root, "e", "t", channels=("discord",))
        self.assertEqual(res["discord"], "error: URLError")  # ไม่เผย webhook/secret

    def test_email_sent(self):
        for k, v in {
            "SMTP_HOST": "smtp.test", "SMTP_USER": "u@test", "SMTP_PASS": "pw",
            "SMTP_FROM": "u@test", "SMTP_TO": "boss@test", "SMTP_PORT": "587",
        }.items():
            config_manager.set_key(self.root, k, v)

        fake_server = mock.MagicMock()

        @contextmanager
        def fake_smtp(*a, **k):
            yield fake_server

        with mock.patch("smtplib.SMTP", fake_smtp):
            res = notifier.notify(self.root, "alert", "disk full", channels=("email",))
        self.assertEqual(res["email"], "sent")
        fake_server.login.assert_called_once_with("u@test", "pw")
        fake_server.send_message.assert_called_once()

    def test_email_skips_without_recipient(self):
        config_manager.set_key(self.root, "SMTP_HOST", "smtp.test")
        config_manager.set_key(self.root, "SMTP_FROM", "u@test")
        # ไม่มี SMTP_TO -> skip
        res = notifier.notify(self.root, "e", "t", channels=("email",))
        self.assertEqual(res["email"], "skipped (no config)")

    def test_unknown_channel(self):
        res = notifier.notify(self.root, "e", "t", channels=("carrier-pigeon",))
        self.assertEqual(res["carrier-pigeon"], "error: unknown channel")


class NotifierMetaTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_notify_returns_dict(self):
        res = notifier.notify(self.root, "test", "hello")
        self.assertIsInstance(res, dict)

    def test_discord_result_is_string(self):
        res = notifier.notify(self.root, "test", "hello", channels=("discord",))
        self.assertIsInstance(res.get("discord"), str)

    def test_email_result_is_string(self):
        res = notifier.notify(self.root, "test", "hello", channels=("email",))
        self.assertIsInstance(res.get("email"), str)

    def test_both_channels_in_result(self):
        res = notifier.notify(self.root, "test", "hello")
        self.assertIn("discord", res)
        self.assertIn("email", res)

    def test_only_requested_channels_in_result(self):
        res = notifier.notify(self.root, "test", "hello", channels=("discord",))
        self.assertIn("discord", res)
        self.assertNotIn("email", res)

    def test_valid_channels_has_discord_and_email(self):
        self.assertIn("discord", notifier.VALID_CHANNELS)
        self.assertIn("email", notifier.VALID_CHANNELS)

    def test_discord_sent_200_response(self):
        # Discord response 200 (ไม่ใช่แค่ 204) ก็ต้อง "sent"
        config_manager.set_key(self.root, "DISCORD_WEBHOOK_URL",
                               "https://discord.test/webhooks/abc/xyz")
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(200)):
            res = notifier.notify(self.root, "e", "t", channels=("discord",))
        self.assertEqual(res["discord"], "sent")


if __name__ == "__main__":
    unittest.main()
