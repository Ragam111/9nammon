"""
test_org_store.py — unittest สำหรับระบบองค์กร (stdlib เท่านั้น ไม่ใช้ pytest)

ทดสอบบน temp dir แยกทุกเคส ไม่แตะ org.json จริงของโปรเจกต์
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import org_store  # noqa: E402


class OrgStoreTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class BootstrapTest(OrgStoreTestBase):
    def test_bootstrap_needed_on_empty(self):
        self.assertTrue(org_store.bootstrap_needed(self.root))

    def test_first_user_must_be_ceo(self):
        with self.assertRaises(ValueError):
            org_store.create_user(self.root, "boss", "password123", "ADMIN")
        # CEO ได้
        rec = org_store.create_user(self.root, "boss", "password123", "CEO")
        self.assertEqual(rec["role"], "CEO")
        self.assertFalse(org_store.bootstrap_needed(self.root))


class PasswordTest(OrgStoreTestBase):
    def setUp(self):
        super().setUp()
        org_store.create_user(self.root, "ceo", "password123", "CEO")

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            org_store.create_user(self.root, "u1", "short", "USER", created_by_role="CEO")

    def test_password_never_stored_plaintext(self):
        raw = (self.root / "org.json").read_text(encoding="utf-8")
        self.assertNotIn("password123", raw)
        self.assertIn("pbkdf2_sha256", raw)

    def test_verify_password_roundtrip(self):
        self.assertIsNotNone(org_store.verify_password(self.root, "ceo", "password123"))
        self.assertIsNone(org_store.verify_password(self.root, "ceo", "wrongpass"))
        self.assertIsNone(org_store.verify_password(self.root, "nobody", "password123"))

    def test_inactive_user_cannot_login(self):
        org_store.create_user(self.root, "u1", "password123", "USER", created_by_role="CEO")
        org_store.set_user_active(self.root, "u1", False, actor_role="CEO")
        self.assertIsNone(org_store.verify_password(self.root, "u1", "password123"))


class RolePermissionTest(OrgStoreTestBase):
    def setUp(self):
        super().setUp()
        org_store.create_user(self.root, "ceo", "password123", "CEO")
        org_store.create_user(self.root, "admin", "password123", "ADMIN", created_by_role="CEO")

    def test_admin_cannot_create_admin_or_ceo(self):
        with self.assertRaises(ValueError):
            org_store.create_user(self.root, "x", "password123", "ADMIN", created_by_role="ADMIN")
        with self.assertRaises(ValueError):
            org_store.create_user(self.root, "y", "password123", "CEO", created_by_role="ADMIN")

    def test_admin_can_create_user(self):
        rec = org_store.create_user(self.root, "u1", "password123", "USER", created_by_role="ADMIN")
        self.assertEqual(rec["role"], "USER")

    def test_ceo_can_create_admin(self):
        rec = org_store.create_user(self.root, "a2", "password123", "ADMIN", created_by_role="CEO")
        self.assertEqual(rec["role"], "ADMIN")

    def test_role_at_least(self):
        self.assertTrue(org_store.role_at_least("CEO", "ADMIN"))
        self.assertTrue(org_store.role_at_least("ADMIN", "ADMIN"))
        self.assertFalse(org_store.role_at_least("USER", "ADMIN"))

    def test_admin_cannot_disable_ceo(self):
        with self.assertRaises(ValueError):
            org_store.set_user_active(self.root, "ceo", False, actor_role="ADMIN")


class ApiKeyTest(OrgStoreTestBase):
    def setUp(self):
        super().setUp()
        org_store.create_user(self.root, "ceo", "password123", "CEO")
        org_store.create_user(self.root, "dev", "password123", "USER", created_by_role="CEO")

    def test_create_and_verify_key(self):
        issued = org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        self.assertIn("key", issued)
        self.assertTrue(issued["key"].startswith("lca_f_"))
        rec = org_store.verify_api_key(self.root, issued["key"])
        self.assertIsNotNone(rec)
        self.assertEqual(rec["owner"], "dev")
        self.assertEqual(rec["role"], "USER")
        self.assertEqual(rec["tier"], "free")

    def test_key_full_value_not_stored(self):
        issued = org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        raw = (self.root / "org.json").read_text(encoding="utf-8")
        self.assertNotIn(issued["key"], raw)  # ต้องไม่มี key เต็มในไฟล์
        self.assertIn("sha256:", raw)         # มีแต่ hash

    def test_wrong_key_rejected(self):
        self.assertIsNone(org_store.verify_api_key(self.root, "lca_f_totallywrong"))
        self.assertIsNone(org_store.verify_api_key(self.root, ""))

    def test_user_must_have_min_role_to_issue(self):
        # USER ออก key ไม่ได้
        with self.assertRaises(ValueError):
            org_store.create_api_key(self.root, "dev", "free", actor_role="USER")

    def test_revoke_key(self):
        issued = org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        self.assertTrue(org_store.revoke_api_key(self.root, issued["key_id"], actor_role="CEO"))
        self.assertIsNone(org_store.verify_api_key(self.root, issued["key"]))

    def test_disabled_owner_invalidates_key(self):
        issued = org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        org_store.set_user_active(self.root, "dev", False, actor_role="CEO")
        self.assertIsNone(org_store.verify_api_key(self.root, issued["key"]))

    def test_verify_key_includes_username(self):
        issued = org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        rec = org_store.verify_api_key(self.root, issued["key"])
        self.assertEqual(rec["username"], "dev")

    def test_list_keys_hides_secret(self):
        org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        keys = org_store.list_api_keys(self.root)
        self.assertEqual(len(keys), 1)
        self.assertNotIn("key", keys[0])
        self.assertNotIn("key_hash", keys[0])
        self.assertIn("prefix", keys[0])


class QuotaTest(OrgStoreTestBase):
    def setUp(self):
        super().setUp()
        org_store.create_user(self.root, "ceo", "password123", "CEO")
        org_store.create_user(self.root, "dev", "password123", "USER", created_by_role="CEO")

    def test_free_tier_consumes_and_limits(self):
        issued = org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        kid = issued["key_id"]
        limit = org_store.TIER_DAILY_LIMIT["free"]
        for i in range(limit):
            ok, remaining = org_store.consume_quota(self.root, kid)
            self.assertTrue(ok)
            self.assertEqual(remaining, limit - (i + 1))
        # ครั้งถัดไปต้องเกินโควตา
        ok, remaining = org_store.consume_quota(self.root, kid)
        self.assertFalse(ok)
        self.assertEqual(remaining, 0)

    def test_has_quota_peek_does_not_consume(self):
        issued = org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        kid = issued["key_id"]
        for _ in range(10):
            self.assertTrue(org_store.has_quota(self.root, kid))  # peek ซ้ำ ไม่หัก
        limit = org_store.TIER_DAILY_LIMIT["free"]
        ok, remaining = org_store.consume_quota(self.root, kid)
        self.assertTrue(ok)
        self.assertEqual(remaining, limit - 1)  # เพิ่งหักครั้งแรก

    def test_has_quota_false_when_exhausted(self):
        issued = org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        kid = issued["key_id"]
        for _ in range(org_store.TIER_DAILY_LIMIT["free"]):
            org_store.consume_quota(self.root, kid)
        self.assertFalse(org_store.has_quota(self.root, kid))

    def test_has_quota_paid_always_true(self):
        issued = org_store.create_api_key(self.root, "dev", "paid", actor_role="CEO")
        self.assertTrue(org_store.has_quota(self.root, issued["key_id"]))

    def test_paid_tier_unlimited(self):
        issued = org_store.create_api_key(self.root, "dev", "paid", actor_role="CEO")
        kid = issued["key_id"]
        for _ in range(500):
            ok, remaining = org_store.consume_quota(self.root, kid)
            self.assertTrue(ok)
            self.assertEqual(remaining, -1)

    def test_daily_reset(self):
        issued = org_store.create_api_key(self.root, "dev", "free", actor_role="CEO")
        kid = issued["key_id"]
        org_store.consume_quota(self.root, kid)
        # จำลองข้ามวัน: แก้ usage_date ให้เป็นเมื่อวาน
        import json
        p = self.root / "org.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data["api_keys"][kid]["usage_date"] = "2000-01-01"
        data["api_keys"][kid]["used_today"] = 999
        p.write_text(json.dumps(data), encoding="utf-8")
        ok, remaining = org_store.consume_quota(self.root, kid)
        self.assertTrue(ok)  # รีเซ็ตแล้วใช้ได้
        self.assertEqual(remaining, org_store.TIER_DAILY_LIMIT["free"] - 1)


if __name__ == "__main__":
    unittest.main()
