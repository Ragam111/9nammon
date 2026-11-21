"""Admin back-office API (phase 1): role checks, list paging and search, detail, stats, and no prompt leaks."""

from __future__ import annotations

import io
import unittest

from fastapi.testclient import TestClient

from app import history
from app.auth import create_user
from app.db import Database
from app.main import create_app
from tests.helpers import FakeModel, make_settings, ok_stream

ADMIN_PW = "admin-password-123"
USER_PW = "user-password-456"
SECRET_PROMPT = "ข้อความลับของผู้ใช้ทดสอบ"


class AdminApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = make_settings()
        self.db = Database(self.settings.data_dir / "app.db")
        self.admin = create_user(self.db, "root", ADMIN_PW, role="admin")
        self.alice = create_user(self.db, "alice", USER_PW)
        self.app = create_app(self.settings, FakeModel([ok_stream(["x"])]).transport, io.StringIO())

    def client(self, username: str | None = None, password: str = "") -> TestClient:
        client = TestClient(self.app, base_url="http://127.0.0.1:8000")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        if username:
            res = client.post("/api/auth/login", json={"username": username, "password": password})
            self.assertEqual(res.status_code, 200)
        return client

    def test_anonymous_is_401_and_normal_user_is_403(self) -> None:
        anon = self.client()
        for path in ("/api/admin/stats", "/api/admin/users", f"/api/admin/users/{self.alice.id}"):
            res = anon.get(path)
            self.assertEqual(res.status_code, 401, path)
            self.assertEqual(res.json()["error"]["type"], "auth", path)
        normal = self.client("alice", USER_PW)
        for path in ("/api/admin/stats", "/api/admin/users", f"/api/admin/users/{self.alice.id}"):
            res = normal.get(path)
            self.assertEqual(res.status_code, 403, path)
            self.assertEqual(res.json()["error"]["type"], "auth", path)

    def test_list_returns_accounts_without_password_hashes(self) -> None:
        admin = self.client("root", ADMIN_PW)
        body = admin.get("/api/admin/users").json()
        self.assertEqual(body["total"], 2)
        self.assertEqual({u["username"] for u in body["items"]}, {"root", "alice"})
        self.assertNotIn("password_hash", admin.get("/api/admin/users").text)
        self.assertNotIn("scrypt$", admin.get("/api/admin/users").text)

    def test_search_treats_wildcards_literally_and_filters_by_role(self) -> None:
        admin = self.client("root", ADMIN_PW)
        self.assertEqual(admin.get("/api/admin/users", params={"q": "%"}).json()["total"], 0)
        self.assertEqual(admin.get("/api/admin/users", params={"q": "ali"}).json()["total"], 1)
        only_admins = admin.get("/api/admin/users", params={"role": "admin"}).json()
        self.assertEqual([u["username"] for u in only_admins["items"]], ["root"])

    def test_paging_and_sort_are_whitelisted(self) -> None:
        admin = self.client("root", ADMIN_PW)
        page = admin.get("/api/admin/users", params={"sort": "username", "order": "asc", "limit": 1}).json()
        self.assertEqual([u["username"] for u in page["items"]], ["alice"])
        self.assertEqual(page["total"], 2)
        second = admin.get("/api/admin/users", params={"sort": "username", "order": "asc", "limit": 1, "offset": 1})
        self.assertEqual([u["username"] for u in second.json()["items"]], ["root"])
        self.assertEqual(admin.get("/api/admin/users", params={"sort": "password_hash"}).status_code, 422)
        self.assertEqual(admin.get("/api/admin/users", params={"limit": 500}).status_code, 422)

    def test_detail_hides_prompts_and_outputs(self) -> None:
        run_id = history.start(self.db, self.alice.id, "test-model", SECRET_PROMPT)
        history.finish(self.db, run_id, status="ok", output="คำตอบลับ", error_type=None,
                       tokens_in=3, tokens_out=4, latency_ms=10)
        admin = self.client("root", ADMIN_PW)
        res = admin.get(f"/api/admin/users/{self.alice.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["run_count"], 1)
        self.assertNotIn(SECRET_PROMPT, res.text)
        self.assertNotIn("คำตอบลับ", res.text)

    def test_unknown_user_is_404(self) -> None:
        admin = self.client("root", ADMIN_PW)
        res = admin.get("/api/admin/users/99999")
        self.assertEqual(res.status_code, 404)

    def test_stats_counts_accounts_and_recent_runs(self) -> None:
        history.start(self.db, self.alice.id, "test-model", "สั้น")
        admin = self.client("root", ADMIN_PW)
        body = admin.get("/api/admin/stats").json()
        self.assertEqual(body["users"], {"total": 2, "admins": 1, "with_sign_in_provider": 0})
        self.assertEqual(body["active_users_24h"], 1)
        self.assertEqual(body["runs_24h"]["ok"], 0)
        self.assertIn("window", body)
        self.assertNotIn("สั้น", admin.get("/api/admin/stats").text)


if __name__ == "__main__":
    unittest.main()
