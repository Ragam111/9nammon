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
