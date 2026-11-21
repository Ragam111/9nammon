"""Security checklist (step 8): auth on every endpoint, rate limit on every endpoint, CORS limited to
the configured origins, the model key never in logs or responses, and no key material in the frontend.
"""

from __future__ import annotations

import io
import pathlib
import re
import unittest
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import Database
from app.main import create_app
from tests.helpers import FakeModel, make_settings, ok_stream

PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/oauth/providers"),
    ("GET", "/api/auth/oauth/{provider}/start"),
    ("GET", "/api/auth/oauth/{provider}/callback"),
}
PASSWORD = "correct-horse-battery"
SECRET = "sk-SECRETKEY-9999-do-not-leak"
FRONTEND_SRC = pathlib.Path(__file__).resolve().parents[1] / ".." / "frontend" / "src"


def endpoints(app: Any) -> list[tuple[str, str]]:
    """Every (method, path) the API exposes, read from the router."""
    found = []
    for route in app.routes[0].original_router.routes:
        for method in sorted(route.methods):
            found.append((method, route.path))
    return found


def concrete(path: str) -> str:
    return path.replace("{run_id}", "run_missing")


def build(model: FakeModel | None = None, **overrides: Any) -> tuple[TestClient, io.StringIO]:
    settings = make_settings(**overrides)
    create_user(Database(settings.data_dir / "app.db"), "alice", PASSWORD)
    logs = io.StringIO()
    transport = model.transport if model else FakeModel([ok_stream(["x"])]).transport
    client = TestClient(create_app(settings, transport, logs), base_url="http://127.0.0.1:8000")
    return client, logs


class AuthEverywhereTest(unittest.TestCase):
    def test_every_non_public_endpoint_rejects_anonymous_requests(self) -> None:
        client, _ = build()
        with client:
            for method, path in endpoints(client.app):
                if (method, path) in PUBLIC:
                    continue
                res = client.request(method, concrete(path), json={})
                self.assertEqual(res.status_code, 401, f"{method} {path} answered {res.status_code}")
                self.assertEqual(res.json()["error"]["type"], "auth", f"{method} {path}")

    def test_public_endpoints_are_exactly_the_expected_set(self) -> None:
        client, _ = build()
        with client:
            found = set(endpoints(client.app))
        self.assertTrue(PUBLIC <= found)
        # 16 = 6 public (health, login, logout, and the 3 OAuth routes) + 10 that need login.
        self.assertEqual(len(found), 16, "new endpoint added: add it to PUBLIC or check its auth here")

    def test_admin_only_endpoints_refuse_normal_users(self) -> None:
        client, _ = build()
        with client:
            client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
            for method, path in (("PUT", "/api/settings/key"), ("DELETE", "/api/settings/key")):
                res = client.request(method, path, json={"api_key": "sk-123456789"})
                self.assertEqual(res.status_code, 403, f"{method} {path}")

    def test_openapi_and_docs_are_disabled(self) -> None:
        client, _ = build()
        with client:
            for path in ("/docs", "/redoc", "/openapi.json"):
                self.assertEqual(client.get(path).status_code, 404, path)


class RateLimitEverywhereTest(unittest.TestCase):
    def test_every_endpoint_is_behind_the_ip_limit(self) -> None:
        """With a limit of one request per minute per IP, the second call to any endpoint (except health)
        must be refused with rate_limit before any handler runs."""
        client, _ = build(rate_limit_ip_per_min=1)
        with client:
            for method, path in endpoints(client.app):
                if (method, path) == ("GET", "/api/health"):
                    continue
                client.app.state.ctx.limiter = type(client.app.state.ctx.limiter)()  # fresh window per endpoint
                client.request(method, concrete(path), json={})
                res = client.request(method, concrete(path), json={})
                self.assertEqual(res.status_code, 429, f"{method} {path} is not rate limited")
                self.assertEqual(res.json()["error"]["type"], "rate_limit", f"{method} {path}")

    def test_login_is_limited_per_ip_and_per_username(self) -> None:
        client, _ = build()
        with client:
            codes = [client.post("/api/auth/login", json={"username": "alice", "password": "wrong-wrong-1"}).status_code
                     for _ in range(6)]
            self.assertEqual(codes[-1], 429)


class CorsTest(unittest.TestCase):
    def test_allowed_origin_is_echoed_and_foreign_origin_is_not(self) -> None:
        client, _ = build(cors_origins=["http://127.0.0.1:5173"])
        with client:
            ok = client.options("/api/run", headers={
                "Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST"})
            self.assertEqual(ok.headers.get("access-control-allow-origin"), "http://127.0.0.1:5173")
            bad = client.options("/api/run", headers={
                "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
            self.assertNotIn("access-control-allow-origin", bad.headers)

    def test_no_wildcard_origin_by_default(self) -> None:
        settings = make_settings()
        self.assertNotIn("*", settings.cors_origins)

    def test_foreign_origin_cannot_post_even_with_a_valid_session(self) -> None:
        client, _ = build()
        with client:
            client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
            res = client.post("/api/run", json={"prompt": "hi"}, headers={"Origin": "https://evil.example"})
            self.assertEqual(res.status_code, 401)


class KeySecrecyTest(unittest.TestCase):
    def test_model_key_never_reaches_logs_or_responses(self) -> None:
        responses = [
            ok_stream(["answer"]),
            httpx.Response(401),  # provider rejects the key
            httpx.Response(200, content=b"not a stream", headers={"content-type": "application/json"}),
        ]
        model = FakeModel(responses)
        client, logs = build(model, model_api_key=SECRET, model_max_retries=0)
        bodies: list[str] = []
        with client:
            client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
            bodies.append(client.post("/api/run", json={"prompt": "hello"}).text)
            bodies.append(client.post("/api/run", json={"prompt": "again"}).text)
            bodies.append(client.post("/api/run", json={"prompt": "third"}).text)
            bodies.append(client.get("/api/settings").text)
            bodies.append(client.get("/api/settings/key").text)
            bodies.append(client.get("/api/health").text)
            bodies.append(client.get("/api/history").text)
            bodies.append(client.post("/api/auth/login", json={"username": "x", "password": "y"}).text)

        # The key is used upstream, in the Authorization header only.
        self.assertEqual(model.requests[0].headers["authorization"], f"Bearer {SECRET}")
        for text in bodies + [logs.getvalue()]:
            self.assertNotIn(SECRET, text)
            self.assertNotIn(SECRET[-8:], text)  # not even a long fragment
        self.assertIn(f'"last4":"{SECRET[-4:]}"', bodies[4])  # only the last four are shown


class FrontendHasNoKeyTest(unittest.TestCase):
    def test_frontend_source_never_references_the_model_key(self) -> None:
        if not FRONTEND_SRC.exists():
            self.skipTest("frontend source not present")
        pattern = re.compile(r"MODEL_API_KEY|VITE_[A-Z_]*KEY|sk-[A-Za-z0-9_-]{12,}")
        offenders = []
        for path in FRONTEND_SRC.rglob("*"):
            if path.suffix in {".ts", ".tsx", ".css", ".html"} and path.is_file():
                if pattern.search(path.read_text(encoding="utf-8")):
                    offenders.append(str(path))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
