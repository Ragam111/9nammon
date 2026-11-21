"""OAuth sign-in with GitHub against a mocked provider: start, callback, state checks and account reuse."""

from __future__ import annotations

import io
import unittest
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from app import auth
from app.auth import create_user
from app.db import Database
from app.errors import AppError
from app.main import create_app
from tests.helpers import make_settings

GH_ID = "gh-client-id-123"
GH_SECRET = "gh-client-secret-xyz"
ERROR_PAGE = "/#/login?error=oauth"


def provider_transport(seen: list[httpx.Request], token_ok: bool = True) -> httpx.MockTransport:
    """Answers the GitHub token and profile endpoints; records every request it sees."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "github.com" and request.url.path == "/login/oauth/access_token":
            if not token_ok:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            return httpx.Response(200, json={"access_token": "tok-1"})
        if request.url.host == "api.github.com" and request.url.path == "/user":
            if request.headers.get("authorization") != "Bearer tok-1":
                return httpx.Response(401, json={})
            return httpx.Response(200, json={"id": 42, "login": "octo"})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


class OAuthRoutesTest(unittest.TestCase):
    def client(self, seen: list[httpx.Request] | None = None, token_ok: bool = True) -> TestClient:
        settings = make_settings(
            oauth_github_client_id=GH_ID,
            oauth_github_client_secret=GH_SECRET,
            public_base_url="http://127.0.0.1:8000",
        )
        seen = [] if seen is None else seen
        app = create_app(settings, provider_transport(seen, token_ok), io.StringIO())
        return TestClient(app, base_url="http://127.0.0.1:8000")

    def _start_state(self, client: TestClient) -> str:
        start = client.get("/api/auth/oauth/github/start", follow_redirects=False)
        return parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    def test_providers_lists_only_configured_ones(self) -> None:
        with self.client() as client:
            self.assertEqual(client.get("/api/auth/oauth/providers").json(), {"providers": ["github"]})

    def test_start_redirects_to_github_with_state_and_never_the_secret(self) -> None:
        with self.client() as client:
            res = client.get("/api/auth/oauth/github/start", follow_redirects=False)
            self.assertEqual(res.status_code, 302)
            target = urlparse(res.headers["location"])
            query = parse_qs(target.query)
            self.assertEqual(target.netloc, "github.com")
            self.assertEqual(query["client_id"], [GH_ID])
            self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:8000/api/auth/oauth/github/callback"])
            self.assertIn("bf_oauth_state=", res.headers["set-cookie"])
            self.assertNotIn(GH_SECRET, res.headers["location"] + res.headers["set-cookie"])

    def test_unconfigured_or_unknown_provider_is_404(self) -> None:
        with self.client() as client:
            self.assertEqual(client.get("/api/auth/oauth/google/start", follow_redirects=False).status_code, 404)
            self.assertEqual(client.get("/api/auth/oauth/apple/start", follow_redirects=False).status_code, 404)

    def test_full_sign_in_creates_a_session_and_sends_the_secret_only_to_the_provider(self) -> None:
        seen: list[httpx.Request] = []
        with self.client(seen) as client:
            state = self._start_state(client)
            res = client.get(f"/api/auth/oauth/github/callback?code=abc&state={state}", follow_redirects=False)
            self.assertEqual(res.headers["location"], "/#/")
            self.assertIn("bf_session=", res.headers["set-cookie"])
            self.assertEqual(client.get("/api/auth/me").json()["user"]["username"], "github:octo")
            token_call = next(r for r in seen if r.url.host == "github.com")
            self.assertIn(b"client_secret=gh-client-secret-xyz", token_call.content)
            self.assertNotIn(GH_SECRET.encode(), res.content)

    def test_mismatched_state_is_refused(self) -> None:
        with self.client() as client:
            self._start_state(client)
            res = client.get("/api/auth/oauth/github/callback?code=abc&state=forged", follow_redirects=False)
            self.assertEqual(res.headers["location"], ERROR_PAGE)
            self.assertNotIn("bf_session=", res.headers.get("set-cookie", ""))
            self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_callback_without_start_is_refused(self) -> None:
        with self.client() as client:
            res = client.get("/api/auth/oauth/github/callback?code=abc&state=anything", follow_redirects=False)
            self.assertEqual(res.headers["location"], ERROR_PAGE)

    def test_provider_rejecting_the_code_gives_the_error_page(self) -> None:
        with self.client(token_ok=False) as client:
            state = self._start_state(client)
            res = client.get(f"/api/auth/oauth/github/callback?code=bad&state={state}", follow_redirects=False)
            self.assertEqual(res.headers["location"], ERROR_PAGE)
            self.assertEqual(client.get("/api/auth/me").status_code, 401)


class OAuthAccountTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(make_settings().data_dir / "app.db")

    def _count(self, username: str) -> int:
        with self.db.session() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM users WHERE username = ?", (username,)).fetchone()["n"])

    def test_same_identity_reuses_its_user(self) -> None:
        auth.login_oauth(self.db, "github", "42", "octo", 1)
        auth.login_oauth(self.db, "github", "42", "octo", 1)
        self.assertEqual(self._count("github:octo"), 1)

    def test_taken_display_name_falls_back_to_the_subject(self) -> None:
        create_user(self.db, "github:octo", "correct-horse-7")  # an unrelated account with that name
        auth.login_oauth(self.db, "github", "42", "octo", 1)
        self.assertEqual(self._count("github:42"), 1)

    def test_provider_user_cannot_log_in_with_a_password(self) -> None:
        auth.login_oauth(self.db, "github", "42", "octo", 1)
        with self.assertRaises(AppError) as ctx:
            auth.login(self.db, "github:octo", "anything-at-all", 1)
        self.assertEqual(ctx.exception.type, "auth")


if __name__ == "__main__":
    unittest.main()
