"""test_adapters.py — เทส Notifier adapter (Storage/Auth adapter ที่ไม่มีใครใช้ถูกลบใน 0.2.x)

pattern เดียวกับ test_model_backend: ทดสอบแต่ละ impl + ตัวเลือกจาก config
โดยไม่ต้องมีดิสก์จริงเยอะ/เครือข่ายจริง (ใช้ tmp dir + mock)
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import notifier as nf  # noqa: E402
from app import config_manager  # noqa: E402


# ---------------- Notifier ----------------

class NotifierAdapterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_null_notifier_records_and_sends_nothing(self):
        n = nf.NullNotifier()
        n.send("JOB_DONE", "เสร็จแล้ว")
        self.assertEqual(len(n.sent), 1)
        self.assertEqual(n.sent[0]["event"], "JOB_DONE")

    def test_multichannel_wraps_notify(self):
        n = nf.MultiChannelNotifier(self.root, channels=("discord",))
        with mock.patch.object(nf, "notify", return_value={"discord": "sent"}) as m:
            self.assertEqual(n.send("E", "hi"), {"discord": "sent"})
        m.assert_called_once()

    def test_default_is_multichannel(self):
        self.assertIsInstance(nf.get_notifier(self.root), nf.MultiChannelNotifier)

    def test_null_selected_from_config(self):
        config_manager.set_key(self.root, "NOTIFIER_BACKEND", "null")
        self.assertIsInstance(nf.get_notifier(self.root), nf.NullNotifier)

    def test_channels_filtered_from_config(self):
        config_manager.set_key(self.root, "NOTIFIER_CHANNELS", "discord, bogus")
        n = nf.get_notifier(self.root)
        self.assertEqual(n.channels, ("discord",))


if __name__ == "__main__":
    unittest.main()
