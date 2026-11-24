"""
test_usage_quota_safe.py — เทสต์ความปลอดภัยของโควตา (fail-closed, atomic, lock)

ครอบคลุม:
- ไฟล์โควตาเสีย -> raise QuotaStoreError, เก็บสำเนา .corrupt-<เวลา>, ไม่รีเซ็ตโควตา
- consume เกินโควตา -> False และไม่หักเพิ่ม
- เขียนพร้อมกันหลายเธรด -> ไม่มี lost update (ใช้ lock ไฟล์ .lock)
ทั้งหมดใช้โฟลเดอร์ชั่วคราว ไม่แตะ usage_quotas.json จริง
"""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import usage_store  # noqa: E402
from app.usage_store import QuotaStoreError, check_and_consume_quota  # noqa: E402

USER = "alice"
TODAY_KEY = "usage_quotas.json"


class QuotaSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / TODAY_KEY

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _count(self) -> int:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return int(data[USER]["count"])

    def test_corrupt_file_is_kept_and_quota_not_reset(self) -> None:
        garbage = '{"alice": {"date": "2099-01-01", "count": 100}'  # JSON ไม่ครบ
        self.path.write_text(garbage, encoding="utf-8")

        with self.assertRaises(QuotaStoreError):
            check_and_consume_quota(USER, tier="free", project_root=self.root)

        # ต้องมีสำเนาไฟล์เสียชื่อ .corrupt-<เวลา> และเนื้อหาตรงกับต้นฉบับ
        copies = list(self.root.glob(f"{TODAY_KEY}.corrupt-*"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_text(encoding="utf-8"), garbage)

        # ไฟล์เดิมยังอยู่ จึงยัง fail-closed ต่อไป (ไม่กลายเป็นไฟล์ว่างแล้วรีเซ็ต)
        self.assertEqual(self.path.read_text(encoding="utf-8"), garbage)
        with self.assertRaises(QuotaStoreError):
            check_and_consume_quota(USER, tier="free", project_root=self.root)

    def test_malformed_entry_is_treated_as_corrupt(self) -> None:
        self.path.write_text(json.dumps({USER: "not-a-dict"}), encoding="utf-8")
        with self.assertRaises(QuotaStoreError):
            check_and_consume_quota(USER, tier="free", project_root=self.root)

    def test_consume_over_limit_is_rejected(self) -> None:
        limit = usage_store.FREE_DAILY_LIMIT
        results = [check_and_consume_quota(USER, tier="free", project_root=self.root)
                   for _ in range(limit + 5)]
        self.assertEqual(results.count(True), limit)
        self.assertEqual(results.count(False), 5)
        self.assertFalse(results[-1])
        self.assertEqual(self._count(), limit)

    def test_paid_tier_is_unlimited(self) -> None:
        for _ in range(usage_store.FREE_DAILY_LIMIT + 3):
            self.assertTrue(check_and_consume_quota(USER, tier="paid", project_root=self.root))
        self.assertFalse(self.path.exists())

    def test_concurrent_writes_do_not_lose_updates(self) -> None:
        threads_n, per_thread = 8, 20  # 160 คำขอ, limit 100 -> ต้องผ่านพอดี 100
        outcomes: list[bool] = []
        errors: list[BaseException] = []
        out_lock = threading.Lock()

        def worker() -> None:
            try:
                for _ in range(per_thread):
                    ok = check_and_consume_quota(USER, tier="free", project_root=self.root)
                    with out_lock:
                        outcomes.append(ok)
            except BaseException as e:  # เก็บไว้ให้เทสต์ตรวจ
                with out_lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(threads_n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(outcomes), threads_n * per_thread)
        self.assertEqual(outcomes.count(True), usage_store.FREE_DAILY_LIMIT)
        self.assertEqual(self._count(), usage_store.FREE_DAILY_LIMIT)

    def test_no_leftover_tmp_or_lock_files(self) -> None:
        for _ in range(3):
            check_and_consume_quota(USER, tier="free", project_root=self.root)
        leftovers = [p.name for p in self.root.iterdir()
                     if p.name.endswith(".tmp") or p.name.endswith(".lock")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
