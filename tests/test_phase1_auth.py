# tests/test_phase1_auth.py
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.org_store import _hash_key, get_user_by_api_key, revoke_api_key
from app.usage_store import check_and_consume_quota
from app.admission import AdmissionController


class TestPhase1SecurityAndGuards(unittest.TestCase):

    def setUp(self):
        """จำลองไฟล์ฐานข้อมูลชั่วคราวก่อนรันเทสต์แต่ละข้อ (Isolation)"""
        self.org_file_backup = Path("org.json")
        self.usage_file_backup = Path("usage_quotas.json")

        self.org_data_orig = self.org_file_backup.read_text(encoding="utf-8") if self.org_file_backup.exists() else None
        self.usage_data_orig = self.usage_file_backup.read_text(encoding="utf-8") if self.usage_file_backup.exists() else None

    def tearDown(self):
        """คืนค่าไฟล์ฐานข้อมูลเดิมหลังเทสต์เสร็จ"""
        if self.org_data_orig is not None:
            Path("org.json").write_text(self.org_data_orig, encoding="utf-8")
        elif Path("org.json").exists():
            Path("org.json").unlink()

        if self.usage_data_orig is not None:
            Path("usage_quotas.json").write_text(self.usage_data_orig, encoding="utf-8")
        elif Path("usage_quotas.json").exists():
            Path("usage_quotas.json").unlink()

    def test_1_org_store_fail_closed_and_valid_key(self):
        """ทดสอบ org_store: Key ที่ถูกต้องผ่าน, Key ผิดหรือถูก Revoke ต้องปฏิเสธ (Fail-Closed)"""
        raw_key = "lca_f_testkey12345"
        hashed = _hash_key(raw_key)

        mock_org = {
            "users": {"dev_nammon": {"username": "dev_nammon", "role": "USER", "active": True}},
            "api_keys": {"k1": {"owner": "dev_nammon", "key_hash": hashed, "tier": "free", "active": True, "revoked": False}},
        }
        # org.json is imported once into data/lca.db (SQLite); use a temp project root
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "org.json").write_text(json.dumps(mock_org), encoding="utf-8")

            user = get_user_by_api_key(raw_key, root)
            self.assertIsNotNone(user)
            self.assertEqual(user["username"], "dev_nammon")
            self.assertEqual(user["tier"], "free")

            wrong_user = get_user_by_api_key("lca_f_wrongkey", root)
            self.assertIsNone(wrong_user)

            self.assertTrue(revoke_api_key(root, "k1", actor_role="CEO"))
            revoked_user = get_user_by_api_key(raw_key, root)
            self.assertIsNone(revoked_user)

    def test_2_usage_store_quota_guard(self):
        """ทดสอบ usage_store: Quota รายวัน (Free Tier 100 requests) เกินแล้วต้องตัด (429)"""
        username = "test_user"

        mock_usage = {username: {"date": "2026-06-07", "count": 100}}
        with patch("app.usage_store.datetime") as mock_date:
            mock_date.now().strftime.return_value = "2026-06-07"
            Path("usage_quotas.json").write_text(json.dumps(mock_usage), encoding="utf-8")

            passed = check_and_consume_quota(username, tier="free")
            self.assertFalse(passed)

            paid_passed = check_and_consume_quota("vip_user", tier="paid")
            self.assertTrue(paid_passed)

    def test_3_admission_controller_concurrency(self):
        """ทดสอบ admission: ควบคุม Concurrency Gate ป้องกัน RAM Spike"""
        controller = AdmissionController(max_concurrent=2)

        self.assertTrue(controller.acquire(timeout=0.1))
        self.assertTrue(controller.acquire(timeout=0.1))

        self.assertFalse(controller.acquire(timeout=0.1))

        controller.release()
        self.assertTrue(controller.acquire(timeout=0.1))

        controller.release()
        controller.release()


if __name__ == "__main__":
    unittest.main()
