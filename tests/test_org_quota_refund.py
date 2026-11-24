"""
test_org_quota_refund.py — reserve-then-refund quota contract (org_store + server) and
usage_store lock ownership. Everything runs in a temp dir; never touches real org.json.

Covers:
- (a) _save failure => consume_quota must not report ok=True
- (b) reserve then refund => used_today back to the original value
- (c) refund never goes negative
- (d) chat path where the model fails (502 / stream error / chat_hub provider error)
      leaves the quota unchanged
- usage_store: lock file carries an owner token, release removes only its own lock,
  OSError is wrapped as QuotaStoreError
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import model_backend, org_store, usage_store  # noqa: E402

MASTER = "master-secret-token"


def _make_key(root: Path) -> str:
    org_store.create_user(root, "boss", "password123", "CEO")
    org_store.create_user(root, "dev", "password123", "USER", created_by_role="CEO")
    return org_store.create_api_key(root, "dev", "free", "CEO")["key_id"]


def _used(root: Path, key_id: str) -> int:
    rec = [k for k in org_store.list_api_keys(root) if k["key_id"] == key_id][0]
    return rec["used_today"]


class OrgQuotaStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.key_id = _make_key(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_failure_consume_not_ok(self) -> None:
        # (a) os.replace keeps failing (Windows reader holding org.json) => not persisted
        with mock.patch("app.org_store.os.replace", side_effect=PermissionError("locked")), \
                mock.patch("app.org_store.time.sleep", lambda s: None):
            ok, _ = org_store.consume_quota(self.root, self.key_id)
        self.assertFalse(ok)
        self.assertEqual(_used(self.root, self.key_id), 0)

    def test_save_transient_permission_error_is_retried(self) -> None:
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("transient")
            return real(src, dst)

        with mock.patch("app.org_store.os.replace", side_effect=flaky):
            ok, remaining = org_store.consume_quota(self.root, self.key_id)
        self.assertTrue(ok)
        self.assertEqual(_used(self.root, self.key_id), 1)
        self.assertEqual(remaining, org_store.TIER_DAILY_LIMIT["free"] - 1)

    def test_reserve_then_refund_restores_count(self) -> None:
        # (b)
        org_store.consume_quota(self.root, self.key_id)
        before = _used(self.root, self.key_id)
        ok, _ = org_store.consume_quota(self.root, self.key_id)
        self.assertTrue(ok)
        self.assertEqual(_used(self.root, self.key_id), before + 1)
        self.assertTrue(org_store.refund_quota(self.root, self.key_id))
        self.assertEqual(_used(self.root, self.key_id), before)

    def test_refund_never_negative(self) -> None:
        # (c)
        org_store.refund_quota(self.root, self.key_id)
        org_store.refund_quota(self.root, self.key_id)
        self.assertEqual(_used(self.root, self.key_id), 0)

    def test_refund_distinguishes_nothing_from_save_failed(self) -> None:
        self.assertIs(org_store.refund_quota(self.root, self.key_id),
                      org_store.RefundResult.NOTHING)
        org_store.consume_quota(self.root, self.key_id)
        with mock.patch("app.org_store.os.replace", side_effect=PermissionError("locked")), \
                mock.patch("app.org_store.time.sleep", lambda s: None):
            res = org_store.refund_quota(self.root, self.key_id)
        self.assertIs(res, org_store.RefundResult.SAVE_FAILED)
        self.assertFalse(res)
        self.assertIs(org_store.refund_quota(self.root, self.key_id),
                      org_store.RefundResult.REFUNDED)


class ChatReleaseLogTest(unittest.TestCase):
    """server._chat_release: warn only when the refund was made but not persisted"""

    def _release(self, result):
        with tempfile.TemporaryDirectory() as tmp:
            handler = server.make_handler(Path(tmp), MASTER)
            ident = {"key_id": "k1", "_quota_reserved": True}
            with mock.patch("app.org_store.refund_quota", return_value=result), \
                    mock.patch("builtins.print") as p:
                handler._chat_release(object(), ident)
        return " ".join(str(c.args) for c in p.call_args_list)

    def test_save_failed_logs_warn(self) -> None:
        self.assertIn("[quota][warn]", self._release(org_store.RefundResult.SAVE_FAILED))

    def test_nothing_to_refund_is_silent(self) -> None:
        self.assertEqual(self._release(org_store.RefundResult.NOTHING), "")
        self.assertEqual(self._release(org_store.RefundResult.REFUNDED), "")


class ServerQuotaRefundTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_gen = model_backend.generate
        self._orig_stream = model_backend.generate_stream
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        handler = server.make_handler(self.root, MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.key_id = _make_key(self.root)
        # issue a raw key over HTTP so the server sees a real X-API-Key
        _, d = self._post("/api/admin/apikeys", {"owner": "dev", "tier": "free"},
                          {"X-Auth-Token": MASTER})
        self.raw_key = json.loads(d)["api_key"]["key"]
        self.http_key_id = [k for k in org_store.list_api_keys(self.root)
                            if k["key_id"] != self.key_id][0]["key_id"]

    def tearDown(self) -> None:
        model_backend.generate = self._orig_gen
        model_backend.generate_stream = self._orig_stream
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _post(self, path, body, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, body=json.dumps(body), headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        return resp.status, raw

    def _chat(self, path="/api/chat", **extra):
        body = {"messages": [{"role": "user", "content": "hi"}], "model": "m"}
        body.update(extra)
        return self._post(path, body, {"X-API-Key": self.raw_key})

    def test_backend_502_does_not_consume_quota(self) -> None:
        # (d)
        def boom(project_root, model, messages, num_ctx=8192, options=None):
            raise model_backend.BackendError("ollama down")
        model_backend.generate = boom
        st, _ = self._chat()
        self.assertEqual(st, 502)
        self.assertEqual(_used(self.root, self.http_key_id), 0)

    def test_unexpected_exception_does_not_consume_quota(self) -> None:
        def boom(project_root, model, messages, num_ctx=8192, options=None):
            raise TypeError("unexpected")
        model_backend.generate = boom
        st, _ = self._chat()
        self.assertEqual(st, 500)
        self.assertEqual(_used(self.root, self.http_key_id), 0)

    def test_stream_error_does_not_consume_quota(self) -> None:
        def gen(project_root, model, messages, num_ctx=8192, options=None):
            yield "a"
            raise model_backend.BackendError("died")
        model_backend.generate_stream = gen
        st, raw = self._chat("/api/chat/stream")
        self.assertEqual(st, 200)
        self.assertIn('"error"', raw)
        self.assertEqual(_used(self.root, self.http_key_id), 0)

    def test_chat_hub_provider_error_does_not_consume_quota(self) -> None:
        def stream(messages, model, *, provider, project_root=None, **_):
            raise RuntimeError("provider died")
            yield  # pragma: no cover

        with mock.patch("app.providers.stream", stream):
            self._chat("/api/chat/stream", provider="openai")
        self.assertEqual(_used(self.root, self.http_key_id), 0)

    def test_success_still_consumes_one(self) -> None:
        model_backend.generate = (
            lambda project_root, model, messages, num_ctx=8192, options=None: "ok")
        st, _ = self._chat()
        self.assertEqual(st, 200)
        self.assertEqual(_used(self.root, self.http_key_id), 1)


class UsageStoreLockOwnershipTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / usage_store.QUOTA_FILE_NAME
        self.lock = self.path.with_name(f"{self.path.name}.lock")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_lock_file_holds_owner_token(self) -> None:
        with usage_store._quota_lock(self.path):
            self.assertTrue(self.lock.read_text(encoding="utf-8").strip())
        self.assertFalse(self.lock.exists())

    def test_release_keeps_foreign_lock(self) -> None:
        # our lock was broken as stale and another process took it: we must not delete theirs
        with usage_store._quota_lock(self.path):
            self.lock.write_text("someone-else", encoding="utf-8")
        self.assertTrue(self.lock.exists())
        self.assertEqual(self.lock.read_text(encoding="utf-8"), "someone-else")

    def test_stale_break_restores_lock_replaced_during_check(self) -> None:
        # stale lock seen as "old", but a new owner takes it right before our rename:
        # rename-then-verify sees "new" in the renamed file and puts it back
        self.lock.write_text("old", encoding="utf-8")
        os.utime(self.lock, (0, 0))
        real_rename = os.rename

        def swap_then_rename(src, dst):
            if Path(src) == self.lock and str(dst).endswith(".del"):
                Path(src).write_text("new", encoding="utf-8")
            return real_rename(src, dst)

        with mock.patch("app.usage_store.os.rename", side_effect=swap_then_rename):
            usage_store._break_stale_lock(self.lock)
        self.assertEqual(self.lock.read_text(encoding="utf-8"), "new")
        self.assertEqual(list(self.root.glob("*.del")), [])

    def test_stale_break_removes_truly_stale_lock(self) -> None:
        self.lock.write_text("dead-owner", encoding="utf-8")
        os.utime(self.lock, (0, 0))
        usage_store._break_stale_lock(self.lock)
        self.assertFalse(self.lock.exists())

    def test_oserror_wrapped_as_quota_store_error(self) -> None:
        with mock.patch("app.usage_store.os.replace", side_effect=PermissionError("locked")), \
                mock.patch("app.usage_store.time.sleep", lambda s: None):
            with self.assertRaises(usage_store.QuotaStoreError):
                usage_store.check_and_consume_quota("alice", "free", project_root=self.root)


if __name__ == "__main__":
    unittest.main()
