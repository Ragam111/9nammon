"""test_feature_flags.py — ศูนย์กลางเปิด/ปิดฟีเจอร์ (is_on/status/set_flag)

Covers:
  FeatureFlagsTest      — defaults off, set/read, status shape, unknown key,
                          shares config key with cluster_forward module
  FeatureFlagsMetaTest  — FEATURES list structure, is_on returns bool,
                          status length, set_flag return dict, multi-flag isolation,
                          unknown is_on returns False not raise
"""

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
        from app import cluster_forward
        ff.set_flag(self.root, "cluster_forward", True)
        self.assertTrue(cluster_forward.is_enabled(self.root))

    def test_all_known_keys_readable(self):
        for f in ff.FEATURES:
            result = ff.is_on(self.root, f["key"])
            self.assertIsInstance(result, bool, f"is_on({f['key']!r}) ต้องคืน bool")

    def test_status_includes_all_features(self):
        statuses = ff.status(self.root)
        self.assertEqual(len(statuses), len(ff.FEATURES))

    def test_status_enabled_is_bool(self):
        for item in ff.status(self.root):
            self.assertIsInstance(item["enabled"], bool,
                                  f"status[{item['key']!r}][enabled] ต้องเป็น bool")

    def test_set_flag_returns_dict_with_enabled(self):
        result = ff.set_flag(self.root, "agent", True)
        self.assertIsInstance(result, dict)
        self.assertIn("enabled", result)
        self.assertTrue(result["enabled"])

    def test_multiple_flags_isolated(self):
        ff.set_flag(self.root, "watchdog", True)
        ff.set_flag(self.root, "agent", False)
        self.assertTrue(ff.is_on(self.root, "watchdog"))
        self.assertFalse(ff.is_on(self.root, "agent"))

    def test_unknown_is_on_returns_false(self):
        result = ff.is_on(self.root, "no-such-flag")
        self.assertFalse(result)

    def test_set_flag_error_message_contains_key(self):
        try:
            ff.set_flag(self.root, "bogus-key", True)
            self.fail("ต้อง raise ValueError")
        except ValueError as e:
            self.assertIn("bogus-key", str(e))


class FeatureFlagsMetaTest(unittest.TestCase):
    def test_features_is_nonempty_list(self):
        self.assertIsInstance(ff.FEATURES, list)
        self.assertGreater(len(ff.FEATURES), 0)

    def test_each_feature_has_required_keys(self):
        for f in ff.FEATURES:
            for key in ("key", "name", "desc", "default"):
                self.assertIn(key, f, f"ฟีเจอร์ {f.get('key', '?')} ขาด field: {key}")

    def test_each_feature_default_is_bool(self):
        for f in ff.FEATURES:
            self.assertIsInstance(f["default"], bool,
                                  f"ค่า default ของ {f['key']} ต้องเป็น bool")


if __name__ == "__main__":
    unittest.main()
