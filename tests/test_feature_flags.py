"""test_feature_flags.py — ศูนย์กลางเปิด/ปิดฟีเจอร์ (is_on/status/set_flag)

Covers:
  is_on()     — defaults off, unknown key, toggles (on/off)
  set_flag()  — unknown key raises, return shape/values
  status()    — list type, all keys present, required fields, count matches FEATURES
  FEATURES    — registry completeness, _BY_KEY lookup
  integration — config_key shared with module (cluster_forward)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import feature_flags as ff  # noqa: E402


class _TmpRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Registry structure
# ---------------------------------------------------------------------------

class TestFeaturesRegistry(unittest.TestCase):
    def test_features_is_non_empty_list(self):
        self.assertIsInstance(ff.FEATURES, list)
        self.assertGreater(len(ff.FEATURES), 0)

    def test_each_feature_has_required_keys(self):
        for f in ff.FEATURES:
            for k in ("key", "config_key", "name", "desc", "default"):
                self.assertIn(k, f, f"feature {f!r} missing {k!r}")

    def test_all_feature_keys_in_by_key(self):
        for f in ff.FEATURES:
            self.assertIn(f["key"], ff._BY_KEY)

    def test_by_key_count_matches_features(self):
        self.assertEqual(len(ff._BY_KEY), len(ff.FEATURES))


# ---------------------------------------------------------------------------
# is_on
# ---------------------------------------------------------------------------

class TestIsOn(_TmpRoot):
    def test_all_features_off_by_default(self):
        for f in ff.FEATURES:
            self.assertFalse(ff.is_on(self.root, f["key"]), f["key"])

    def test_unknown_key_returns_false(self):
        self.assertFalse(ff.is_on(self.root, "no_such_feature"))

    def test_set_then_is_on_returns_true(self):
        ff.set_flag(self.root, "watchdog", True)
        self.assertTrue(ff.is_on(self.root, "watchdog"))

    def test_set_off_returns_false(self):
        ff.set_flag(self.root, "watchdog", True)
        ff.set_flag(self.root, "watchdog", False)
        self.assertFalse(ff.is_on(self.root, "watchdog"))

    def test_toggle_all_features(self):
        for f in ff.FEATURES:
            ff.set_flag(self.root, f["key"], True)
            self.assertTrue(ff.is_on(self.root, f["key"]), f["key"])
            ff.set_flag(self.root, f["key"], False)
            self.assertFalse(ff.is_on(self.root, f["key"]), f["key"])


# ---------------------------------------------------------------------------
# set_flag
# ---------------------------------------------------------------------------

class TestSetFlag(_TmpRoot):
    def test_unknown_key_raises_value_error(self):
        with self.assertRaises(ValueError):
            ff.set_flag(self.root, "no_such_flag", True)

    def test_returns_dict(self):
        result = ff.set_flag(self.root, "agent", True)
        self.assertIsInstance(result, dict)

    def test_return_has_key_name_enabled(self):
        result = ff.set_flag(self.root, "agent", True)
        for k in ("key", "name", "enabled"):
            self.assertIn(k, result)

    def test_return_key_matches_input(self):
        result = ff.set_flag(self.root, "connections", True)
        self.assertEqual(result["key"], "connections")

    def test_return_enabled_true_when_set_true(self):
        result = ff.set_flag(self.root, "agent", True)
        self.assertTrue(result["enabled"])

    def test_return_enabled_false_when_set_false(self):
        ff.set_flag(self.root, "agent", True)
        result = ff.set_flag(self.root, "agent", False)
        self.assertFalse(result["enabled"])


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestStatus(_TmpRoot):
    def test_returns_list(self):
        self.assertIsInstance(ff.status(self.root), list)

    def test_count_matches_features(self):
        self.assertEqual(len(ff.status(self.root)), len(ff.FEATURES))

    def test_all_feature_keys_present(self):
        keys = {e["key"] for e in ff.status(self.root)}
        for f in ff.FEATURES:
            self.assertIn(f["key"], keys)

    def test_each_entry_has_required_fields(self):
        for entry in ff.status(self.root):
            for k in ("key", "name", "desc", "enabled"):
                self.assertIn(k, entry)

    def test_enabled_reflects_set_flag(self):
        ff.set_flag(self.root, "cluster_forward", True)
        status_map = {e["key"]: e for e in ff.status(self.root)}
        self.assertTrue(status_map["cluster_forward"]["enabled"])
        self.assertFalse(status_map["watchdog"]["enabled"])


# ---------------------------------------------------------------------------
# Integration — config_key shared with feature module
# ---------------------------------------------------------------------------

class TestIntegration(_TmpRoot):
    def test_shares_config_key_with_cluster_forward_module(self):
        from app import cluster_forward
        ff.set_flag(self.root, "cluster_forward", True)
        self.assertTrue(cluster_forward.is_enabled(self.root))


if __name__ == "__main__":
    unittest.main()
