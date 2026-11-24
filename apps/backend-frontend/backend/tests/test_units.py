"""Unit tests: quota, rate limit, error mapping, retry/backoff, key store, JSON log redaction."""

from __future__ import annotations

import asyncio
import io
import json
import unittest

import httpx

from app import quota
from app.auth import create_user
from app.db import Database
from app.errors import AppError, from_exception, from_upstream_status, is_retryable_exception
from app.keystore import KeyStore
from app.logging_json import log_event
from app.ratelimit import RateLimiter
from app.retry import backoff_delay, with_retry
from tests.helpers import make_settings


class QuotaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(make_settings().data_dir / "app.db")
        self.uid = create_user(self.db, "alice", "correct-horse-1").id

    def test_record_accumulates_per_day(self) -> None:
        quota.record(self.db, self.uid, 300, window="2026-11-20T05")
        quota.record(self.db, self.uid, 200, window="2026-11-20T05")
        quota.record(self.db, self.uid, 999, window="2026-11-20T10")
        self.assertEqual(quota.used(self.db, self.uid, "2026-11-20T05"), 500)
        self.assertEqual(quota.remaining(self.db, self.uid, 1000, "2026-11-20T05"), 500)

    def test_check_raises_quota_when_used_up(self) -> None:
        quota.record(self.db, self.uid, 1000, window="2026-11-20T05")
        with self.assertRaises(AppError) as ctx:
            quota.check(self.db, self.uid, 1000, window="2026-11-20T05")
        self.assertEqual(ctx.exception.type, "quota")
        self.assertFalse(ctx.exception.retryable)

    def test_zero_and_negative_are_ignored(self) -> None:
        quota.record(self.db, self.uid, 0)
        quota.record(self.db, self.uid, -5)
        self.assertEqual(quota.used(self.db, self.uid), 0)

    def test_users_are_counted_separately(self) -> None:
        other = create_user(self.db, "bob", "correct-horse-2").id
        quota.record(self.db, self.uid, 700, window="d")
        self.assertEqual(quota.used(self.db, other, "d"), 0)


class RateLimitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1000.0
        self.limiter = RateLimiter(clock=lambda: self.now)

    def test_blocks_after_limit_with_retry_after(self) -> None:
        for _ in range(3):
            self.limiter.hit("user:1", 3)
        with self.assertRaises(AppError) as ctx:
            self.limiter.hit("user:1", 3)
        self.assertEqual(ctx.exception.type, "rate_limit")
        self.assertEqual(ctx.exception.retry_after_s, 60)

    def test_window_slides(self) -> None:
        for _ in range(3):
            self.limiter.hit("ip:a", 3)
        self.now += 60
        self.limiter.hit("ip:a", 3)  # old hits expired
        self.assertEqual(self.limiter.remaining("ip:a", 3), 2)

    def test_keys_are_independent(self) -> None:
        self.limiter.hit("user:1", 1)
        self.limiter.hit("user:2", 1)
        self.limiter.hit("ip:x", 1)

    def test_old_keys_are_swept(self) -> None:
        for i in range(50):
            self.limiter.hit(f"ip:{i}", 5)
        self.now += 61
        self.limiter.hit("ip:new", 5)
        self.assertEqual(self.limiter.key_count(), 1)

    def test_quota_need_larger_than_remaining(self) -> None:
        db = Database(make_settings().data_dir / "app.db")
        uid = create_user(db, "carol", "correct-horse-3").id
        quota.record(db, uid, 950, window="d")
        with self.assertRaises(AppError) as ctx:
            quota.check(db, uid, 1000, window="d", need=100)
        self.assertIn("50", ctx.exception.user_message)


class ErrorMappingTest(unittest.TestCase):
    def test_every_type_has_status_and_thai_message(self) -> None:
        for t, status in {"auth": 401, "quota": 429, "rate_limit": 429, "timeout": 504,
                          "validation": 422, "upstream": 502, "unknown": 500}.items():
            err = AppError(t)
            self.assertEqual(err.status, status)
            self.assertTrue(err.user_message)

    def test_unknown_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AppError("bogus")

    def test_upstream_statuses(self) -> None:
        self.assertEqual(from_upstream_status(401).type, "upstream")
        self.assertIn("API key", from_upstream_status(401).user_message)
        self.assertEqual(from_upstream_status(429).type, "rate_limit")
        self.assertEqual(from_upstream_status(400).type, "validation")
        self.assertEqual(from_upstream_status(503).type, "upstream")

    def test_exceptions(self) -> None:
        req = httpx.Request("POST", "https://x.test")
        self.assertEqual(from_exception(httpx.ReadTimeout("t", request=req)).type, "timeout")
        self.assertEqual(from_exception(httpx.ConnectError("c", request=req)).type, "upstream")
        self.assertEqual(from_exception(RuntimeError("boom")).type, "unknown")

    def test_retryable_classification(self) -> None:
        req = httpx.Request("POST", "https://x.test")

        def status_error(code: int) -> httpx.HTTPStatusError:
            return httpx.HTTPStatusError("e", request=req, response=httpx.Response(code, request=req))

        self.assertTrue(is_retryable_exception(httpx.ConnectTimeout("t", request=req)))
        self.assertTrue(is_retryable_exception(status_error(503)))
        self.assertTrue(is_retryable_exception(status_error(429)))
        self.assertFalse(is_retryable_exception(status_error(401)))
        self.assertFalse(is_retryable_exception(status_error(400)))
        self.assertFalse(is_retryable_exception(ValueError("x")))

    def test_to_dict_has_no_internal_detail(self) -> None:
        body = AppError("rate_limit", retry_after_s=7).to_dict("req1")
        self.assertEqual(body, {"type": "rate_limit", "message": body["message"], "retryable": True,
                                "request_id": "req1", "retry_after_s": 7})


class RetryTest(unittest.TestCase):
    def test_backoff_doubles_and_caps(self) -> None:
        self.assertEqual([backoff_delay(n, 0.5) for n in (1, 2, 3, 4)], [0.5, 1.0, 2.0, 4.0])
        self.assertEqual(backoff_delay(10, 0.5), 8.0)
        with self.assertRaises(ValueError):
            backoff_delay(0, 0.5)

    def _run(self, failures: list[Exception], max_retries: int) -> tuple[object, list[float], int]:
        calls = {"n": 0}
        slept: list[float] = []

        async def call() -> str:
            calls["n"] += 1
            if failures:
                raise failures.pop(0)
            return "ok"

        async def sleep(s: float) -> None:
            slept.append(s)

        async def go() -> object:
            return await with_retry(call, max_retries=max_retries, base_delay_s=1.0,
                                    is_retryable=lambda e: isinstance(e, TimeoutError), sleep=sleep)

        try:
            result: object = asyncio.run(go())
        except Exception as exc:  # returned so the test can assert on it
            result = exc
        return result, slept, calls["n"]

    def test_retries_retryable_then_succeeds(self) -> None:
        result, slept, calls = self._run([TimeoutError(), TimeoutError()], max_retries=2)
        self.assertEqual((result, slept, calls), ("ok", [1.0, 2.0], 3))

    def test_gives_up_after_max_retries(self) -> None:
        result, slept, calls = self._run([TimeoutError()] * 5, max_retries=2)
        self.assertIsInstance(result, TimeoutError)
        self.assertEqual((slept, calls), ([1.0, 2.0], 3))

    def test_non_retryable_is_not_retried(self) -> None:
        result, slept, calls = self._run([ValueError("bad input")], max_retries=3)
        self.assertIsInstance(result, ValueError)
        self.assertEqual((slept, calls), ([], 1))


class ClientIpTest(unittest.TestCase):
    def setUp(self) -> None:
        from app.clientip import parse_networks

        self.proxy = parse_networks(["172.28.0.10/32"])

    def test_untrusted_peer_cannot_spoof_its_ip(self) -> None:
        from app.clientip import resolve_client_ip

        self.assertEqual(resolve_client_ip("203.0.113.5", {"x-real-ip": "10.9.9.9"}, self.proxy), "203.0.113.5")

    def test_trusted_proxy_passes_the_real_client(self) -> None:
        from app.clientip import resolve_client_ip

        self.assertEqual(resolve_client_ip("172.28.0.10", {"x-real-ip": "203.0.113.5"}, self.proxy), "203.0.113.5")

    def test_trusted_proxy_with_bad_header_falls_back_to_peer(self) -> None:
        from app.clientip import resolve_client_ip

        self.assertEqual(resolve_client_ip("172.28.0.10", {"x-real-ip": "not-an-ip"}, self.proxy), "172.28.0.10")
        self.assertEqual(resolve_client_ip("172.28.0.10", {}, self.proxy), "172.28.0.10")

    def test_no_peer_and_non_ip_peer(self) -> None:
        from app.clientip import resolve_client_ip

        self.assertEqual(resolve_client_ip(None, {}, self.proxy), "unknown")
        self.assertEqual(resolve_client_ip("testclient", {}, self.proxy), "testclient")

    def test_default_trusts_nobody(self) -> None:
        from app.clientip import resolve_client_ip

        self.assertEqual(resolve_client_ip("172.28.0.10", {"x-real-ip": "203.0.113.5"}, []), "172.28.0.10")


class RequireKeyTest(unittest.TestCase):
    def test_local_hosts_need_no_key(self) -> None:
        from app.model_client import require_key

        for url in ("http://127.0.0.1:11434/v1", "http://localhost:11434/v1", "http://host.docker.internal:11434/v1"):
            require_key("", url)  # must not raise

    def test_remote_host_needs_a_key(self) -> None:
        from app.model_client import require_key

        with self.assertRaises(AppError):
            require_key("", "https://api.example.com/v1")
        require_key("sk-x", "https://api.example.com/v1")


class KeyStoreTest(unittest.TestCase):
    def test_env_key_wins_and_only_last4_is_exposed(self) -> None:
        store = KeyStore("sk-env-abcd9876", make_settings().data_dir)
        self.assertEqual(store.status().to_dict(), {"configured": True, "last4": "9876", "source": "env"})
        with self.assertRaises(AppError):
            store.save("sk-other-key-1111")

    def test_save_and_clear_stored_key(self) -> None:
        store = KeyStore("", make_settings().data_dir)
        self.assertFalse(store.status().configured)
        self.assertEqual(store.save("  sk-stored-key-4321 ").last4, "4321")
        self.assertEqual(store.get(), "sk-stored-key-4321")
        self.assertFalse(store.clear().configured)

    def test_rejects_bad_keys(self) -> None:
        store = KeyStore("", make_settings().data_dir)
        for bad in ("short", "has space inside key", "x" * 600):
            with self.assertRaises(AppError):
                store.save(bad)


class JsonLogTest(unittest.TestCase):
    def test_sensitive_fields_are_dropped(self) -> None:
        out = io.StringIO()
        log_event("run", out, request_id="r1", prompt="secret prompt", api_key="sk-x", Authorization="b", latency_ms=5)
        record = json.loads(out.getvalue())
        self.assertEqual(record["request_id"], "r1")
        self.assertEqual(record["latency_ms"], 5)
        for name in ("prompt", "api_key", "Authorization"):
            self.assertNotIn(name, record)
        self.assertNotIn("sk-x", out.getvalue())


if __name__ == "__main__":
    unittest.main()
