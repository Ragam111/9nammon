"""Static regression checks for server.py bug sweep (BF4-1, ORG-1 wiring)."""

import re
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")


def _method(name: str) -> str:
    m = re.search(rf"def {name}\(self.*?(?=\n        def )", SRC, re.S)
    assert m, name
    return m.group(0)


class ServerWiringTest(unittest.TestCase):
    def test_bf4_1_disable_revokes_sessions(self) -> None:
        self.assertIn("session_store.revoke_user(username)", _method("_handle_users_set_active"))

    def test_org1_revoke_permission_maps_to_403(self) -> None:
        body = _method("_handle_apikeys_revoke")
        self.assertIn("except PermissionError", body)
        self.assertIn("403", body)


if __name__ == "__main__":
    unittest.main()


class GuestQuotaAtomicTest(unittest.TestCase):
    """BF1-1: guest quota is reserved atomically at check time and refundable."""

    def setUp(self):
        import server as srv
        self.srv = srv
        srv._guest_quota_reset()

    def tearDown(self):
        self.srv._guest_quota_reset()

    def test_concurrent_checks_never_exceed_limit(self):
        import threading
        ok = []
        def hit():
            ok.append(self.srv._guest_quota_ok("1.2.3.4"))
        ts = [threading.Thread(target=hit) for _ in range(self.srv.GUEST_DAILY_LIMIT + 15)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sum(ok), self.srv.GUEST_DAILY_LIMIT)

    def test_refund_returns_unit(self):
        for _ in range(self.srv.GUEST_DAILY_LIMIT):
            self.assertTrue(self.srv._guest_quota_ok("9.9.9.9"))
        self.assertFalse(self.srv._guest_quota_ok("9.9.9.9"))
        self.srv._guest_quota_refund("9.9.9.9")
        self.assertTrue(self.srv._guest_quota_ok("9.9.9.9"))


class SessionTierLiveTest(unittest.TestCase):
    def test_bf4_2_identity_recomputes_session_tier(self) -> None:
        body = _method("_identity")
        self.assertIn('org_store.user_tier(project_root, sess["username"])', body)
