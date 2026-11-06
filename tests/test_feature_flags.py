"""test_feature_flags.py — ศูนย์กลางเปิด/ปิดฟีเจอร์ (is_on/status/set_flag)"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import feature_flags as ff  # noqa: E402


class FeatureFlagsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_defaults_off(self):
        # ฟีเจอร์เสี่ยง/กินแรง ปิดเป็นค่าเริ่มต้น
        for f in ff.FEATURES:
            self.assertFalse(ff.is_on(self.root, f["key"]), f["key"])

    def test_set_and_read(self):
        ff.set_flag(self.root, "watchdog", True)
        self.assertTrue(ff.is_on(self.root, "watchdog"))
        ff.set_flag(self.root, "watchdog", False)
        self.assertFalse(ff.is_on(self.root, "watchdog"))

    def test_status_shape(self):
        ff.set_flag(self.root, "cluster_forward", True)
        st = {f["key"]: f for f in ff.status(self.root)}
        self.assertTrue(st["cluster_forward"]["enabled"])
        self.assertIn("name", st["cluster_forward"])
        self.assertIn("desc", st["cluster_forward"])

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            ff.set_flag(self.root, "ไม่มีฟีเจอร์นี้", True)
        self.assertFalse(ff.is_on(self.root, "ไม่มีฟีเจอร์นี้"))

    def test_shares_config_key_with_module(self):
        # feature_flags เขียน key เดียวกับที่โมดูลฟีเจอร์อ่าน (cluster_forward)
        from app import cluster_forward
        ff.set_flag(self.root, "cluster_forward", True)
        self.assertTrue(cluster_forward.is_enabled(self.root))


class FeatureFlagsExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_features_list_is_nonempty(self):
        self.assertGreater(len(ff.FEATURES), 0)

    def test_each_feature_has_key_field(self):
        for feat in ff.FEATURES:
            self.assertIn("key", feat)

    def test_each_feature_has_name_field(self):
        for feat in ff.FEATURES:
            self.assertIn("name", feat)

    def test_each_feature_has_desc_field(self):
        for feat in ff.FEATURES:
            self.assertIn("desc", feat)

    def test_is_on_unknown_key_returns_false(self):
        self.assertFalse(ff.is_on(self.root, "no-such-flag-xyz"))

    def test_set_flag_persists_on_repeated_call(self):
        ff.set_flag(self.root, "watchdog", True)
        ff.set_flag(self.root, "watchdog", True)
        self.assertTrue(ff.is_on(self.root, "watchdog"))


if __name__ == "__main__":
    unittest.main()
