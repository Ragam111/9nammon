"""API tests through FastAPI's TestClient, with the model faked by an httpx MockTransport."""

from __future__ import annotations

import asyncio
import io
import json
import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE, create_user
from app.db import Database
from app.main import create_app
from tests.helpers import FakeModel, make_settings, ok_stream, parse_sse

PASSWORD = "correct-horse-battery"


@contextmanager
def client_for(model: FakeModel, role: str = "user", **overrides: Any) -> Iterator[tuple[TestClient, io.StringIO]]:
    settings = make_settings(**overrides)
    create_user(Database(settings.data_dir / "app.db"), "alice", PASSWORD, role)
    logs = io.StringIO()
    with TestClient(create_app(settings, model.transport, logs), base_url="http://127.0.0.1:8000") as client:
        yield client, logs


def login(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
    assert res.status_code == 200, res.text


class AuthTest(unittest.TestCase):
    def test_login_sets_httponly_cookie_and_logout_clears_it(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])])) as (client, _):
            res = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD})
            self.assertEqual(res.status_code, 200)
            cookie = res.headers["set-cookie"]
            self.assertIn(f"{SESSION_COOKIE}=", cookie)
            self.assertIn("HttpOnly", cookie)
            self.assertIn("samesite=lax", cookie.lower())
            self.assertEqual(client.get("/api/auth/me").json()["user"]["username"], "alice")
            client.post("/api/auth/logout")
            self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_wrong_password_is_auth_error(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])])) as (client, _):
            res = client.post("/api/auth/login", json={"username": "alice", "password": "nope-nope-nope"})
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.json()["error"]["type"], "auth")

    def test_every_data_endpoint_requires_auth(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])])) as (client, _):
            for method, path in [("get", "/api/settings"), ("get", "/api/history"), ("post", "/api/run"),
                                 ("get", "/api/settings/key"), ("put", "/api/settings/key")]:
                body = {"prompt": "hi"} if path == "/api/run" else {"api_key": "sk-123456789"}
                res = client.request(method.upper(), path, json=body if method != "get" else None)
                self.assertEqual(res.status_code, 401, path)

    def test_ip_rate_limit_but_health_is_exempt(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])]), rate_limit_ip_per_min=2) as (client, _):
            for _ in range(5):
                self.assertEqual(client.get("/api/health").status_code, 200)
            client.get("/api/auth/me")
            client.get("/api/auth/me")
            res = client.get("/api/auth/me")
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (429, "rate_limit"))

    def test_login_is_limited_per_username(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])])) as (client, _):
            codes = [client.post("/api/auth/login", json={"username": "alice", "password": "wrong-wrong-1"}).status_code
                     for _ in range(6)]
            self.assertEqual(codes, [401] * 5 + [429])

    def test_chunked_body_without_length_is_refused(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])])) as (client, _):
            res = client.post("/api/auth/login", content=iter([b'{"username":"alice",', b'"password":"x"}']),
                              headers={"Content-Type": "application/json"})
            self.assertEqual(res.status_code, 411)

    def test_bad_json_message(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])])) as (client, _):
            res = client.post("/api/auth/login", content=b"{not json", headers={"Content-Type": "application/json"})
            self.assertEqual(res.json()["error"]["message"], "รูปแบบ JSON ไม่ถูกต้อง")

    def test_foreign_origin_is_refused_for_writes(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])])) as (client, _):
            res = client.post("/api/auth/login", json={"username": "alice", "password": PASSWORD},
                              headers={"Origin": "https://evil.example"})
            self.assertEqual(res.status_code, 401)


class KeyOnboardingTest(unittest.TestCase):
    def test_admin_sets_key_and_only_last4_comes_back(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])]), role="admin", model_api_key="") as (client, logs):
            login(client)
            res = client.put("/api/settings/key", json={"api_key": "sk-live-secret-WXYZ"})
            self.assertEqual(res.json(), {"configured": True, "last4": "WXYZ", "source": "stored"})
            self.assertNotIn("sk-live-secret", client.get("/api/settings").text)
            self.assertNotIn("sk-live-secret", logs.getvalue())

    def test_normal_user_cannot_set_key(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])]), model_api_key="") as (client, _):
            login(client)
            res = client.put("/api/settings/key", json={"api_key": "sk-123456789"})
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (403, "auth"))


class RunTest(unittest.TestCase):
    def test_streams_deltas_records_history_quota_and_log(self) -> None:
        model = FakeModel([ok_stream(["สวัส", "ดี"], usage={"prompt_tokens": 3, "completion_tokens": 2})])
        with client_for(model) as (client, logs):
            login(client)
            res = client.post("/api/run", json={"prompt": "ทักทาย"})
            events = parse_sse(res.text)
            self.assertEqual([e[0] for e in events], ["start", "delta", "delta", "done"])
            self.assertEqual("".join(str(e[1]["text"]) for e in events if e[0] == "delta"), "สวัสดี")
            self.assertEqual(model.requests[0].headers["authorization"], "Bearer sk-test-secret-1234")
            run_id = events[0][1]["run_id"]
            detail = client.get(f"/api/history/{run_id}").json()
            self.assertEqual((detail["status"], detail["output"], detail["tokens_out"]), ("ok", "สวัสดี", 2))
            self.assertEqual(client.get("/api/settings").json()["quota"]["used"], 5)
            run_log = [json.loads(line) for line in logs.getvalue().splitlines() if '"event": "run"' in line][0]
            self.assertEqual(run_log["tokens_in"] + run_log["tokens_out"], 5)
            self.assertIn("cost_estimate", run_log)
            self.assertNotIn("ทักทาย", logs.getvalue())
            self.assertNotIn("sk-test-secret", logs.getvalue())

    def test_retries_503_then_succeeds(self) -> None:
        model = FakeModel([httpx.Response(503), ok_stream(["ok"])])
        with client_for(model) as (client, _):
            login(client)
            events = parse_sse(client.post("/api/run", json={"prompt": "hi"}).text)
            self.assertEqual(events[-1][0], "done")
            self.assertEqual(len(model.requests), 2)

    def test_invalid_model_key_is_not_retried(self) -> None:
        model = FakeModel([httpx.Response(401)])
        with client_for(model) as (client, _):
            login(client)
            res = client.post("/api/run", json={"prompt": "hi"})
            self.assertEqual(res.status_code, 502)
            self.assertIn("API key", res.json()["error"]["message"])
            self.assertEqual(len(model.requests), 1)

    def test_timeout_after_retries_is_timeout_error(self) -> None:
        model = FakeModel([httpx.ReadTimeout("slow")])
        with client_for(model) as (client, _):
            login(client)
            res = client.post("/api/run", json={"prompt": "hi"})
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (504, "timeout"))
            self.assertEqual(len(model.requests), 3)  # 1 try + 2 retries

    def test_quota_full_blocks_run(self) -> None:
        model = FakeModel([ok_stream(["x"], usage={"prompt_tokens": 10, "completion_tokens": 60})])
        with client_for(model, quota_tokens_per_day=100) as (client, _):
            login(client)
            self.assertEqual(parse_sse(client.post("/api/run", json={"prompt": "hello there"}).text)[-1][0], "done")
            res = client.post("/api/run", json={"prompt": "again"})  # 30 left < prompt + 64 output cap
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (429, "quota"))
            self.assertEqual(len(model.requests), 1)

    def test_upstream_429_is_retried(self) -> None:
        model = FakeModel([httpx.Response(429), ok_stream(["ok"])])
        with client_for(model) as (client, _):
            login(client)
            self.assertEqual(parse_sse(client.post("/api/run", json={"prompt": "hi"}).text)[-1][0], "done")
            self.assertEqual(len(model.requests), 2)

    def test_empty_stream_is_an_error_not_ok(self) -> None:
        with client_for(FakeModel([ok_stream([])])) as (client, _):
            login(client)
            events = parse_sse(client.post("/api/run", json={"prompt": "hi"}).text)
            self.assertEqual([e[0] for e in events], ["start", "error"])
            self.assertFalse(events[-1][1]["partial"])
            self.assertEqual(client.get("/api/history").json()["items"][0]["status"], "error")
            self.assertEqual(client.get("/api/settings").json()["quota"]["used"], 0)

    def test_error_object_inside_stream(self) -> None:
        body = b'data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: {"error":{"message":"overloaded"}}\n\n'
        model = FakeModel([httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})])
        with client_for(model) as (client, _):
            login(client)
            events = parse_sse(client.post("/api/run", json={"prompt": "hi"}).text)
            self.assertEqual([e[0] for e in events], ["start", "delta", "error"])
            self.assertTrue(events[-1][1]["partial"])

    def test_stream_without_done_marker_is_partial(self) -> None:
        body = b'data: {"choices":[{"delta":{"content":"cut"}}]}\n\n'
        model = FakeModel([httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})])
        with client_for(model) as (client, _):
            login(client)
            events = parse_sse(client.post("/api/run", json={"prompt": "hi"}).text)
            self.assertEqual(events[-1][0], "error")
            self.assertEqual(client.get("/api/history").json()["items"][0]["status"], "partial")

    def test_output_cap_is_marked_truncated(self) -> None:
        with client_for(FakeModel([ok_stream(["x" * 40])]), max_output_tokens=2) as (client, _):
            login(client)
            events = parse_sse(client.post("/api/run", json={"prompt": "hi"}).text)
            self.assertEqual(events[-1][0], "done")
            self.assertTrue(events[-1][1]["truncated"])
            self.assertEqual("".join(str(e[1]["text"]) for e in events if e[0] == "delta"), "x" * 16)
            self.assertEqual(client.get("/api/history").json()["items"][0]["status"], "partial")

    def test_total_deadline_stops_a_slow_stream(self) -> None:
        class Slow(httpx.AsyncByteStream):
            async def __aiter__(self):  # type: ignore[override]
                yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                await asyncio.sleep(5)
                yield b"data: [DONE]\n\n"

        model = FakeModel([httpx.Response(200, stream=Slow(), headers={"content-type": "text/event-stream"})])
        with client_for(model, model_timeout_s=1.0) as (client, _):
            login(client)
            started = time.monotonic()
            events = parse_sse(client.post("/api/run", json={"prompt": "hi"}).text)
            self.assertLess(time.monotonic() - started, 4)
            last_name, last = events[-1]
            self.assertEqual((last_name, last["type"], last["partial"]), ("error", "timeout", True))

    def test_user_rate_limit(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])]), rate_limit_user_per_min=1) as (client, _):
            login(client)
            client.post("/api/run", json={"prompt": "one"})
            res = client.post("/api/run", json={"prompt": "two"})
            self.assertEqual(res.json()["error"]["type"], "rate_limit")
            self.assertIn("retry-after", res.headers)

    def test_input_too_long_is_validation(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])])) as (client, _):
            login(client)
            res = client.post("/api/run", json={"prompt": "x" * 201})
            self.assertEqual((res.status_code, res.json()["error"]["type"]), (422, "validation"))

    def test_mid_stream_drop_keeps_partial_output(self) -> None:
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):  # type: ignore[override]
                yield b'data: {"choices":[{"delta":{"content":"half"}}]}\n\n'
                raise httpx.ReadError("connection reset")

        model = FakeModel([httpx.Response(200, stream=Broken())])
        with client_for(model) as (client, _):
            login(client)
            events = parse_sse(client.post("/api/run", json={"prompt": "hi"}).text)
            self.assertEqual([e[0] for e in events], ["start", "delta", "error"])
            self.assertTrue(events[-1][1]["partial"])
            self.assertTrue(events[-1][1]["retryable"])
            items = client.get("/api/history").json()["items"]
            self.assertEqual((items[0]["status"], items[0]["error_type"]), ("partial", "upstream"))


class HistoryTest(unittest.TestCase):
    def test_search_filter_detail_delete_and_isolation(self) -> None:
        with client_for(FakeModel([ok_stream(["answer"])])) as (client, _):
            login(client)
            for prompt in ("alpha question", "beta question", "gamma 100%"):
                client.post("/api/run", json={"prompt": prompt})
            self.assertEqual(client.get("/api/history").json()["total"], 3)
            self.assertEqual(client.get("/api/history", params={"q": "beta"}).json()["total"], 1)
            self.assertEqual(client.get("/api/history", params={"q": "100%"}).json()["total"], 1)
            self.assertEqual(client.get("/api/history", params={"status": "error"}).json()["total"], 0)
            run_id = client.get("/api/history").json()["items"][0]["id"]
            self.assertTrue(client.delete(f"/api/history/{run_id}").json()["ok"])
            self.assertEqual(client.get(f"/api/history/{run_id}").status_code, 404)

    def test_health_is_public_and_hides_key(self) -> None:
        with client_for(FakeModel([ok_stream(["x"])])) as (client, _):
            res = client.get("/api/health")
            self.assertEqual(res.json()["status"], "ok")
            self.assertNotIn("sk-test-secret", res.text)
            self.assertTrue(res.headers["x-request-id"])


if __name__ == "__main__":
    unittest.main()
