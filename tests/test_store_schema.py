"""test_store_schema.py — framework เวอร์ชัน + migration ของไฟล์ JSON store

ตรวจ: detect รูปไฟล์ (list เก่า vs envelope), migrate ทีละสเต็ปตามลำดับ, ไม่ downgrade
ไฟล์ที่ใหม่กว่า, load/dumps round-trip, และไฟล์พัง degrade เป็นว่าง (ไม่ crash)
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store_schema  # noqa: E402


class DetectTest(unittest.TestCase):
    def test_bare_list_is_baseline(self):
        v, recs = store_schema.detect([{"a": 1}])
        self.assertEqual(v, store_schema.BASELINE_VERSION)
        self.assertEqual(recs, [{"a": 1}])

    def test_envelope_reads_version(self):
        v, recs = store_schema.detect({"schema_version": 3, "records": [{"a": 1}]})
        self.assertEqual(v, 3)
        self.assertEqual(recs, [{"a": 1}])

    def test_envelope_bad_version_falls_back(self):
        v, recs = store_schema.detect({"schema_version": "x", "records": []})
        self.assertEqual(v, store_schema.BASELINE_VERSION)

    def test_garbage_degrades_to_empty(self):
        v, recs = store_schema.detect("not a store")
        self.assertEqual(recs, [])


class MigrateTest(unittest.TestCase):
    def test_runs_steps_in_order(self):
        calls = []
        migs = [
            lambda r: (calls.append("v1v2"), r)[1],
            lambda r: (calls.append("v2v3"), r)[1],
        ]
        recs, changed = store_schema.migrate([], 1, 3, migs)
        self.assertTrue(changed)
        self.assertEqual(calls, ["v1v2", "v2v3"])

    def test_partial_range(self):
        calls = []
        migs = [lambda r: (calls.append(0), r)[1], lambda r: (calls.append(1), r)[1]]
        store_schema.migrate([], 2, 3, migs)          # เริ่มที่ v2 → รันแค่ migrations[1]
        self.assertEqual(calls, [1])

    def test_no_change_when_current(self):
        recs, changed = store_schema.migrate([{"a": 1}], 2, 2, [])
        self.assertFalse(changed)

    def test_never_downgrades_newer_file(self):
        # ไฟล์ v5 แต่โปรแกรมรู้แค่ v2 → ไม่แตะ (กันข้อมูลหาย)
        recs, changed = store_schema.migrate([{"a": 1}], 5, 2, [])
        self.assertFalse(changed)
        self.assertEqual(recs, [{"a": 1}])

    def test_actual_transform_applied(self):
        def add_field(records):
            for r in records:
                r["added"] = True
            return records
        recs, _ = store_schema.migrate([{"a": 1}], 1, 2, [add_field])
        self.assertTrue(recs[0]["added"])


class LoadDumpTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "s.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_empty(self):
        recs, up = store_schema.load(self.path, 1, [])
        self.assertEqual(recs, [])
        self.assertFalse(up)

    def test_load_old_bare_list_upgrades(self):
        self.path.write_text(json.dumps([{"a": 1}]), encoding="utf-8")   # ไฟล์เก่า
        recs, up = store_schema.load(self.path, 2, [lambda r: [dict(x, v2=True) for x in r]])
        self.assertTrue(up)                                              # ถูกอัปเกรด
        self.assertTrue(recs[0]["v2"])

    def test_load_current_envelope_no_upgrade(self):
        self.path.write_text(store_schema.dumps([{"a": 1}], 2), encoding="utf-8")
        recs, up = store_schema.load(self.path, 2, [])
        self.assertFalse(up)
        self.assertEqual(recs, [{"a": 1}])

    def test_dumps_has_version_envelope(self):
        s = store_schema.dumps([{"a": 1}], 7)
        obj = json.loads(s)
        self.assertEqual(obj["schema_version"], 7)
        self.assertEqual(obj["records"], [{"a": 1}])

    def test_broken_json_degrades(self):
        self.path.write_text("{not json", encoding="utf-8")
        recs, up = store_schema.load(self.path, 1, [])
        self.assertEqual(recs, [])


if __name__ == "__main__":
    unittest.main()
