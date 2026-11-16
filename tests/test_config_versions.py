"""test_config_versions.py — เทส snapshot + rollback ของ config (กัน incident)

ตรวจ: snapshot เก็บเวอร์ชัน, list คืน metadata (ไม่เผย secret ค่าเต็ม),
rollback ย้อน config.json จริง + snapshot ปัจจุบันก่อน (ย้อนได้อีก), id ผิด → ValueError
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config_versions as cv  # noqa: E402
from app import config_manager  # noqa: E402


class ConfigVersionsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

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
        # metadata ต้องไม่มีค่า secret โผล่
        self.assertNotIn("sk-super-secret", json.dumps(versions))
        self.assertEqual(versions[0]["keys"], 1)

    def test_rollback_restores_config(self):
        self._write_config({"MODEL_BACKEND": "ollama"})
        v1 = cv.snapshot(self.root, label="good")
        # จำลองของพัง: เปลี่ยน config เป็นค่าผิด
        config_manager.set_key(self.root, "MODEL_BACKEND", "broken-backend")
        self.assertEqual(config_manager.get_key(self.root, "MODEL_BACKEND"), "broken-backend")
        # rollback กลับ v1
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
        # มีเวอร์ชันเพิ่ม (backup ของ v2 ก่อน rollback) → ย้อนของ rollback ได้อีก
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
