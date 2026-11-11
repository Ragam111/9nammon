"""tests for app/session_store.py — session token หลัง login + brute-force guard"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import session_store  # noqa: E402


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        session_store.clear()

    def tearDown(self):
        session_store.clear()

    def test_create_and_verify(self):
        sess = session_store.create("alice", "USER")
        self.assertTrue(sess["token"].startswith(session_store.TOKEN_PREFIX))
        ident = session_store.verify(sess["token"])
        self.assertEqual(ident["username"], "alice")
        self.assertEqual(ident["role"], "USER")
        self.assertEqual(ident["source"], "session")
        self.assertIsNone(ident["key_id"])

    def test_unknown_or_wrong_prefix_token_rejected(self):
        session_store.create("alice", "USER")
        self.assertIsNone(session_store.verify("lcs_not-a-real-token"))
        self.assertIsNone(session_store.verify("master-token-looking"))
        self.assertIsNone(session_store.verify(None))
        self.assertIsNone(session_store.verify(""))

    def test_expiry(self):
        sess = session_store.create("alice", "USER", ttl=10, now=1000.0)
        self.assertIsNotNone(session_store.verify(sess["token"], now=1005.0))
        self.assertIsNone(session_store.verify(sess["token"], now=1010.0))
        # หมดอายุแล้วถูกลบทิ้งจริง
        self.assertEqual(session_store.count(), 0)

    def test_revoke(self):
        sess = session_store.create("alice", "ADMIN")
        self.assertTrue(session_store.revoke(sess["token"]))
        self.assertFalse(session_store.revoke(sess["token"]))
        self.assertIsNone(session_store.verify(sess["token"]))

    def test_revoke_user_drops_all_sessions_of_that_user(self):
        a1 = session_store.create("alice", "USER")
        a2 = session_store.create("alice", "USER")
        b = session_store.create("bob", "USER")
        self.assertEqual(session_store.revoke_user("alice"), 2)
        self.assertIsNone(session_store.verify(a1["token"]))
        self.assertIsNone(session_store.verify(a2["token"]))
        self.assertIsNotNone(session_store.verify(b["token"]))

    def test_login_limiter(self):
        ip = "10.0.0.9"
        for i in range(session_store.LOGIN_MAX_FAILURES):
            self.assertTrue(session_store.login_allowed(ip, now=100.0 + i))
            session_store.record_failure(ip, now=100.0 + i)
        self.assertFalse(session_store.login_allowed(ip, now=110.0))
        # พ้นหน้าต่างเวลาแล้วลองใหม่ได้
        self.assertTrue(session_store.login_allowed(ip, now=100.0 + session_store.LOGIN_WINDOW_SECONDS + 1))
        session_store.record_failure(ip)
        session_store.reset_failures(ip)
        self.assertTrue(session_store.login_allowed(ip))


if __name__ == "__main__":
    unittest.main()
