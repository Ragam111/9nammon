"""test_config_manager.py — config.json read/write/env fallback"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config_manager  # noqa: E402


class GetKeyTest(unittest.TestCase):
    def test_key_from_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cfg = {"API_KEY": "sk-test-123"}
            (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            self.assertEqual(config_manager.get_key(p, "API_KEY"), "sk-test-123")

    def test_missing_key_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(config_manager.get_key(Path(tmp), "NONEXISTENT"))

    def test_env_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_key = "LCA_TEST_ENV_FALLBACK_12345"
            os.environ[env_key] = "from-env"
            try:
                result = config_manager.get_key(Path(tmp), env_key)
                self.assertEqual(result, "from-env")
            finally:
                del os.environ[env_key]

    def test_config_file_takes_precedence_over_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            env_key = "LCA_TEST_PRIORITY_KEY"
            os.environ[env_key] = "from-env"
            try:
                cfg = {env_key: "from-file"}
                (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
                self.assertEqual(config_manager.get_key(p, env_key), "from-file")
            finally:
                del os.environ[env_key]

    def test_no_config_file_no_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(config_manager.get_key(Path(tmp), "TRULY_MISSING"))

    def test_config_file_name_constant(self):
        self.assertEqual(config_manager.CONFIG_FILE_NAME, "config.json")

    def test_corrupted_json_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config.json").write_text("{bad json!!!", encoding="utf-8")
            self.assertIsNone(config_manager.get_key(p, "ANYTHING"))

    def test_non_dict_json_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            self.assertIsNone(config_manager.get_key(p, "ANYTHING"))

    def test_empty_env_value_returns_none(self):
        # env var exists but is empty string → treat as not set
        with tempfile.TemporaryDirectory() as tmp:
            env_key = "LCA_TEST_EMPTY_VALUE_XYZ"
            os.environ[env_key] = ""
            try:
                result = config_manager.get_key(Path(tmp), env_key)
                self.assertIsNone(result)
            finally:
                del os.environ[env_key]


class SetKeyTest(unittest.TestCase):
    def test_set_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config_manager.set_key(p, "NEW_KEY", "new_value")
            self.assertEqual(config_manager.get_key(p, "NEW_KEY"), "new_value")

    def test_set_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cfg = {"EXISTING": "keep"}
            (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            config_manager.set_key(p, "ADDED", "new")
            self.assertEqual(config_manager.get_key(p, "EXISTING"), "keep")
            self.assertEqual(config_manager.get_key(p, "ADDED"), "new")

    def test_overwrite_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config_manager.set_key(p, "K", "old")
            config_manager.set_key(p, "K", "new")
            self.assertEqual(config_manager.get_key(p, "K"), "new")

    def test_set_creates_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self.assertFalse((p / "config.json").exists())
            config_manager.set_key(p, "X", "y")
            self.assertTrue((p / "config.json").exists())

    def test_set_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = config_manager.set_key(Path(tmp), "K", "v")
            self.assertIsNone(result)

    def test_multiple_keys_coexist(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config_manager.set_key(p, "A", "1")
            config_manager.set_key(p, "B", "2")
            config_manager.set_key(p, "C", "3")
            self.assertEqual(config_manager.get_key(p, "A"), "1")
            self.assertEqual(config_manager.get_key(p, "B"), "2")
            self.assertEqual(config_manager.get_key(p, "C"), "3")


class ListKeysTest(unittest.TestCase):
    def test_list_configured_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cfg = {"A": "1", "B": "2"}
            (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            keys = config_manager.list_configured_keys(p)
            self.assertIn("A", keys)
            self.assertIn("B", keys)

    def test_list_no_config_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            keys = config_manager.list_configured_keys(Path(tmp))
            self.assertEqual(keys, [])

    def test_list_does_not_return_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cfg = {"SECRET": "should-not-appear"}
            (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            keys = config_manager.list_configured_keys(p)
            for k in keys:
                self.assertNotEqual(k, "should-not-appear")

    def test_list_returns_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = config_manager.list_configured_keys(Path(tmp))
            self.assertIsInstance(result, list)

    def test_list_returns_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config_manager.set_key(p, "MYKEY", "myval")
            keys = config_manager.list_configured_keys(p)
            for k in keys:
                self.assertIsInstance(k, str)


if __name__ == "__main__":
    unittest.main()
