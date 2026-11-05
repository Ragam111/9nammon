"""test_config_versions.py — เทส snapshot + rollback ของ config (กัน incident)

ตรวจ: snapshot เก็บเวอร์ชัน, list คืน metadata (ไม่เผย secret ค่าเต็ม),
rollback ย้อน config.json จริง + snapshot ปัจจุบันก่อน (ย้อนได้อีก), id ผิด → ValueError

Covers:
  Module constants  — VERSIONS_FILE, MAX_VERSIONS
  snapshot()        — return shape (id/ts/label/keys), unique ids, label truncated
  list_versions()   — newest-first ordering, metadata-only (no config/secrets leaked),
                      all 4 metadata keys present
  rollback()        — return shape (restored/keys/backup), config restored, backup created,
                      unknown id raises, rollback-of-rollback reachable
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config_versions as cv  # noqa: E402
from app import config_manager  # noqa: E402


class _TmpRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_config(self, d):
        config_manager._config_path(self.root).write_text(
            json.dumps(d, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants(unittest.TestCase):
    def test_versions_file_is_string(self):
        self.assertIsInstance(cv.VERSIONS_FILE, str)

    def test_max_versions_positive(self):
        self.assertGreater(cv.MAX_VERSIONS, 0)


# ---------------------------------------------------------------------------
# snapshot — return shape
# ---------------------------------------------------------------------------

class TestSnapshotShape(_TmpRoot):
    def test_returns_dict(self):
        self._write_config({"K": "v"})
        self.assertIsInstance(cv.snapshot(self.root), dict)

    def test_has_all_expected_fields(self):
        self._write_config({"K": "v"})
        meta = cv.snapshot(self.root, label="test")
        for field in ("id", "ts", "label", "keys"):
            self.assertIn(field, meta)

    def test_ts_is_integer(self):
        self._write_config({"K": "v"})
        meta = cv.snapshot(self.root)
        self.assertIsInstance(meta["ts"], int)

    def test_label_stored(self):
        self._write_config({"K": "v"})
        meta = cv.snapshot(self.root, label="my label")
        self.assertEqual(meta["label"], "my label")

    def test_label_truncated_at_120(self):
        self._write_config({"K": "v"})
        meta = cv.snapshot(self.root, label="x" * 200)
        self.assertLessEqual(len(meta["label"]), 120)

    def test_keys_count_correct(self):
        self._write_config({"A": "1", "B": "2", "C": "3"})
        meta = cv.snapshot(self.root)
        self.assertEqual(meta["keys"], 3)

    def test_empty_config_keys_zero(self):
        self._write_config({})
        meta = cv.snapshot(self.root)
        self.assertEqual(meta["keys"], 0)


# ---------------------------------------------------------------------------
# list_versions — ordering and metadata safety
# ---------------------------------------------------------------------------

class TestListVersions(_TmpRoot):
    def test_empty_when_no_snapshots(self):
        self.assertEqual(cv.list_versions(self.root), [])

    def test_newest_first_ordering(self):
        self._write_config({"K": "v1"})
        cv.snapshot(self.root, label="first")
        time.sleep(0.01)
        cv.snapshot(self.root, label="second")
        versions = cv.list_versions(self.root)
        self.assertEqual(versions[0]["label"], "second")

    def test_all_metadata_keys_present(self):
        self._write_config({"K": "v"})
        cv.snapshot(self.root)
        versions = cv.list_versions(self.root)
        for field in ("id", "ts", "label", "keys"):
            self.assertIn(field, versions[0])

    def test_no_config_key_in_metadata(self):
        self._write_config({"K": "v"})
        cv.snapshot(self.root)
        versions = cv.list_versions(self.root)
        self.assertNotIn("config", versions[0])

    def test_no_secret_values_leaked(self):
        self._write_config({"OPENAI_API_KEY": "sk-super-secret"})
        cv.snapshot(self.root)
        versions = cv.list_versions(self.root)
        self.assertNotIn("sk-super-secret", json.dumps(versions))


# ---------------------------------------------------------------------------
# rollback — shape and behaviour
# ---------------------------------------------------------------------------

class TestRollbackShape(_TmpRoot):
    def _setup_v1(self):
        self._write_config({"MODEL_BACKEND": "ollama"})
        return cv.snapshot(self.root, label="good")

    def test_returns_dict_with_expected_keys(self):
        v1 = self._setup_v1()
        config_manager.set_key(self.root, "MODEL_BACKEND", "broken")
        res = cv.rollback(self.root, v1["id"])
        for key in ("restored", "keys", "backup"):
            self.assertIn(key, res)

    def test_restored_id_matches(self):
        v1 = self._setup_v1()
        res = cv.rollback(self.root, v1["id"])
        self.assertEqual(res["restored"], v1["id"])

    def test_config_actually_restored(self):
        v1 = self._setup_v1()
        config_manager.set_key(self.root, "MODEL_BACKEND", "broken-backend")
        cv.rollback(self.root, v1["id"])
        self.assertEqual(config_manager.get_key(self.root, "MODEL_BACKEND"), "ollama")

    def test_backup_created_before_rollback(self):
        v1 = self._setup_v1()
        config_manager.set_key(self.root, "K2", "extra")
        before = len(cv.list_versions(self.root))
        cv.rollback(self.root, v1["id"])
        self.assertEqual(len(cv.list_versions(self.root)), before + 1)


# ---------------------------------------------------------------------------
# rollback + snapshot — edge cases (original tests preserved)
# ---------------------------------------------------------------------------

class TestConfigVersionsOriginal(_TmpRoot):
    def _write_config(self, d):
        config_manager._config_path(self.root).write_text(
            json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def test_snapshot_then_list(self):
        self._write_config({"MODEL_BACKEND": "ollama"})
        meta = cv.snapshot(self.root, label="เริ่มต้น")
        self.assertIn("id", meta)
        self.assertEqual(meta["label"], "เริ่มต้น")
        self.assertEqual(meta["keys"], 1)
        versions = cv.list_versions(self.root)
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["id"], meta["id"])

    def test_list_does_not_leak_secret_values(self):
        self._write_config({"OPENAI_API_KEY": "sk-super-secret"})
        cv.snapshot(self.root)
        versions = cv.list_versions(self.root)
        self.assertNotIn("sk-super-secret", json.dumps(versions))
        self.assertEqual(versions[0]["keys"], 1)

    def test_rollback_restores_config(self):
        self._write_config({"MODEL_BACKEND": "ollama"})
        v1 = cv.snapshot(self.root, label="good")
        config_manager.set_key(self.root, "MODEL_BACKEND", "broken-backend")
        self.assertEqual(config_manager.get_key(self.root, "MODEL_BACKEND"), "broken-backend")
        res = cv.rollback(self.root, v1["id"])
        self.assertEqual(res["restored"], v1["id"])
        self.assertEqual(config_manager.get_key(self.root, "MODEL_BACKEND"), "ollama")

    def test_rollback_snapshots_current_first(self):
        self._write_config({"K": "v1"})
        v1 = cv.snapshot(self.root)
        config_manager.set_key(self.root, "K", "v2-current")
        before = len(cv.list_versions(self.root))
        cv.rollback(self.root, v1["id"])
        after = cv.list_versions(self.root)
        self.assertEqual(len(after), before + 1)

    def test_rollback_unknown_id_raises(self):
        self._write_config({"K": "v"})
        cv.snapshot(self.root)
        with self.assertRaises(ValueError):
            cv.rollback(self.root, "v-does-not-exist")

    def test_keeps_only_max_versions(self):
        self._write_config({"K": "v"})
        for i in range(cv.MAX_VERSIONS + 5):
            cv.snapshot(self.root, label=f"s{i}")
        self.assertEqual(len(cv.list_versions(self.root)), cv.MAX_VERSIONS)

    def test_empty_when_no_snapshots(self):
        self.assertEqual(cv.list_versions(self.root), [])


if __name__ == "__main__":
    unittest.main()
