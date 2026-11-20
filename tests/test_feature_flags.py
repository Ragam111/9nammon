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

    def test_features_is_list(self):
        self.assertIsInstance(ff.FEATURES, list)
        self.assertGreater(len(ff.FEATURES), 0)

    def test_each_feature_has_required_keys(self):
        for f in ff.FEATURES:
            self.assertIn("key", f)
            self.assertIn("name", f)
            self.assertIn("desc", f)

    def test_is_on_returns_bool(self):
        result = ff.is_on(self.root, "watchdog")
        self.assertIsInstance(result, bool)

    def test_status_returns_list(self):
        result = ff.status(self.root)
        self.assertIsInstance(result, list)

    def test_status_length_matches_features(self):
        result = ff.status(self.root)
        self.assertEqual(len(result), len(ff.FEATURES))

    def test_toggle_persists(self):
        # Set then verify it survives a fresh call
        ff.set_flag(self.root, "agent", True)
        self.assertTrue(ff.is_on(self.root, "agent"))
        ff.set_flag(self.root, "agent", False)
        self.assertFalse(ff.is_on(self.root, "agent"))

    def test_multiple_flags_independent(self):
        ff.set_flag(self.root, "watchdog", True)
        ff.set_flag(self.root, "agent", False)
        self.assertTrue(ff.is_on(self.root, "watchdog"))
        self.assertFalse(ff.is_on(self.root, "agent"))


if __name__ == "__main__":
    unittest.main()
