"""Regression tests for bug sweep ORG-1..ORG-5 (app/org_store.py)."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import org_store  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        org_store.create_user(self.root, "ceo", "password123", "CEO")
        org_store.create_user(self.root, "adm", "password123", "ADMIN", "CEO")
        org_store.create_user(self.root, "adm2", "password123", "ADMIN", "CEO")
        org_store.create_user(self.root, "u", "password123", "USER", "CEO")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class RevokeOwnerRoleTest(_Base):
    def test_org1_admin_cannot_revoke_ceo_key(self) -> None:
        k = org_store.create_api_key(self.root, "ceo", "paid", "CEO")
        with self.assertRaises(PermissionError):
            org_store.revoke_api_key(self.root, k["key_id"], "ADMIN")

    def test_org1_admin_can_revoke_user_key(self) -> None:
        k = org_store.create_api_key(self.root, "u", "free", "CEO")
        self.assertTrue(org_store.revoke_api_key(self.root, k["key_id"], "ADMIN"))


class SetActiveTest(_Base):
    def test_org2_admin_cannot_disable_peer_admin(self) -> None:
        with self.assertRaises(ValueError):
            org_store.set_user_active(self.root, "adm2", False, "ADMIN")

    def test_org2_admin_can_disable_user(self) -> None:
        self.assertTrue(org_store.set_user_active(self.root, "u", False, "ADMIN"))

    def test_org3_last_ceo_cannot_disable_self(self) -> None:
        with self.assertRaises(ValueError):
            org_store.set_user_active(self.root, "ceo", False, "CEO")


class DailyLimitTest(_Base):
    def test_org4_create_returns_stored_limit(self) -> None:
        org_store.run_write(self.root, lambda c: org_store.set_plan_limit_in(
            c, "u", "pro", 500, "o1", time.time() + 3600))
        k = org_store.create_api_key(self.root, "u", "free", "CEO")
        listed = [r for r in org_store.list_api_keys(self.root) if r["key_id"] == k["key_id"]]
        self.assertEqual(k["daily_limit"], listed[0]["daily_limit"])
        self.assertEqual(k["daily_limit"], 500)


class UnknownTierTest(_Base):
    def test_org5_unknown_tier_fails_closed_as_free(self) -> None:
        results = [org_store.check_and_consume_quota("u", "bogus", self.root)
                   for _ in range(org_store.TIER_DAILY_LIMIT["free"] + 1)]
        self.assertFalse(results[-1])


if __name__ == "__main__":
    unittest.main()
