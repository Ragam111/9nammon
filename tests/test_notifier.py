"""
test_notifier.py — unittest สำหรับ notifier (Discord webhook + email) แบบ mock ล้วน
ไม่ยิงเน็ตจริง/ไม่ส่งเมลจริง — patch urlopen และ smtplib.SMTP
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


if __name__ == "__main__":
    unittest.main()
