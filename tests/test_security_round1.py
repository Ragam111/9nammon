"""test_security_round1.py — regression tests for security round 1.

1) /api/news?feed= accepts only DEFAULT_FEEDS keys (no SSRF / file read)
2) login sessions carry the user's real tier and pay quota like API keys
3) tunnel start: CEO only, own listen port, CF-Connecting-IP trusted while tunnel runs
4) /v1 streaming refunds quota only when nothing was delivered

Everything runs in temp dirs; cloudflared and Ollama are always mocked.
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import chat_hub, cloud_tunnel, model_backend, news_store, org_store  # noqa: E402
from app import openai_gateway as gw  # noqa: E402
from app import session_store  # noqa: E402

MASTER = "master-secret-token"
MODEL = "qwen2.5:1.5b"


class _HttpCase(unittest.TestCase):
    def setUp(self):
        session_store.clear()
        news_store._cache.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        handler = server.make_handler(self.root, MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.master = {"X-Auth-Token": MASTER}
        for name, pw, role in (("boss", "password123", "CEO"), ("alice", "alicepass1", "USER"),
                               ("ops", "opspass123", "ADMIN"), ("vip", "vippass123", "USER")):
            st, d = self._req("POST", "/api/admin/users",
                              {"username": name, "password": pw, "role": role}, self.master)
            self.assertEqual(st, 200, d)
        org_store.create_api_key(self.root, "vip", "paid", "CEO")

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()
        session_store.clear()

    def _raw(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        return resp.status, raw

    def _req(self, method, path, body=None, headers=None):
        st, raw = self._raw(method, path, body, headers)
        try:
            return st, (json.loads(raw) if raw else {})
        except json.JSONDecodeError:
            return st, {"raw": raw}

    def _login(self, user, pw):
        st, d = self._req("POST", "/api/auth/login", {"username": user, "password": pw})
        self.assertEqual(st, 200, d)
        return {"X-Auth-Token": d["token"]}, d

    def _user_count(self, username):
        rows = org_store._read(self.root, "SELECT count FROM org_user_usage WHERE username=?",
                               (username,))
        return rows[0]["count"] if rows else 0


# ---------------------------------------------------------------- 1) news SSRF
class NewsFeedAllowlistTest(_HttpCase):
    def test_arbitrary_urls_rejected_400(self):
        calls = []
        with mock.patch.object(news_store, "_fetch_feed", lambda u, timeout=10: calls.append(u) or []):
            for bad in ("http://127.0.0.1:8420/api/health", "file:///etc/passwd",
                        "https://example.com/feed", "nope"):
                st, d = self._req("GET", "/api/news?feed=" + urllib.request.quote(bad, safe=""),
                                  headers=self.master)
                self.assertEqual(st, 400, (bad, d))
        self.assertEqual(calls, [])

    def test_known_key_fetches_its_url(self):
        calls = []
        with mock.patch.object(news_store, "_fetch_feed", lambda u, timeout=10: calls.append(u) or []):
            st, d = self._req("GET", "/api/news?feed=bbci", headers=self.master)
        self.assertEqual(st, 200, d)
        self.assertEqual(calls, [news_store.DEFAULT_FEEDS["bbci"]])

    def test_no_feed_uses_all_defaults(self):
        calls = []
        with mock.patch.object(news_store, "_fetch_feed", lambda u, timeout=10: calls.append(u) or []):
            st, _ = self._req("GET", "/api/news", headers=self.master)
        self.assertEqual(st, 200)
        self.assertEqual(sorted(calls), sorted(news_store.DEFAULT_FEEDS.values()))


class NewsFetchGuardTest(unittest.TestCase):
    def test_non_http_scheme_not_opened(self):
        with mock.patch.object(news_store, "urlopen") as op:
            self.assertEqual(news_store._fetch_feed("file:///etc/passwd"), [])
        op.assert_not_called()

    def test_redirect_to_private_host_blocked(self):
        h = news_store._SafeRedirect()
        req = urllib.request.Request("https://feeds.bbci.co.uk/x")
        for target in ("http://127.0.0.1/", "http://localhost:8420/", "http://10.0.0.5/",
                       "file:///etc/passwd", "http://169.254.169.254/latest"):
            with self.assertRaises(urllib.error.URLError, msg=target):
                h.redirect_request(req, None, 302, "Found", {}, target)


# ---------------------------------------------------------------- 2) session quota
class SessionQuotaTest(_HttpCase):
    def setUp(self):
        super().setUp()
        self._gen = mock.patch.object(model_backend, "generate",
                                      lambda root, model, messages, num_ctx=8192, options=None: "ok")
        self._gen.start()

    def tearDown(self):
        self._gen.stop()
        super().tearDown()

    def _chat(self, hdr):
        return self._req("POST", "/api/chat",
                         {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}, hdr)

    def test_login_session_tier_is_free_without_paid_key(self):
        hdr, d = self._login("alice", "alicepass1")
        self.assertEqual(d["tier"], "free")
        st, me = self._req("GET", "/api/me", headers=hdr)
        self.assertEqual(me["tier"], "free")

    def test_login_session_tier_paid_with_paid_key(self):
        _hdr, d = self._login("vip", "vippass123")
        self.assertEqual(d["tier"], "paid")

    def test_session_chat_consumes_and_enforces_quota(self):
        hdr, _ = self._login("alice", "alicepass1")
        with mock.patch.dict(org_store.TIER_DAILY_LIMIT, {"free": 2}):
            self.assertEqual(self._chat(hdr)[0], 200)
            self.assertEqual(self._user_count("alice"), 1)
            self.assertEqual(self._chat(hdr)[0], 200)
            st, d = self._chat(hdr)
        self.assertEqual(st, 429, d)
        self.assertEqual(self._user_count("alice"), 2)

    def test_session_chat_failure_refunds(self):
        hdr, _ = self._login("alice", "alicepass1")

        def boom(*a, **k):
            raise model_backend.BackendError("down")
        with mock.patch.object(model_backend, "generate", boom):
            st, _ = self._chat(hdr)
        self.assertEqual(st, 502)
        self.assertEqual(self._user_count("alice"), 0)

    def test_paid_session_unlimited(self):
        hdr, _ = self._login("vip", "vippass123")
        with mock.patch.dict(org_store.TIER_DAILY_LIMIT, {"free": 1}):
            for _ in range(3):
                self.assertEqual(self._chat(hdr)[0], 200)

    def test_master_token_unlimited_and_not_counted(self):
        with mock.patch.dict(org_store.TIER_DAILY_LIMIT, {"free": 1}):
            for _ in range(3):
                self.assertEqual(self._chat(self.master)[0], 200)
        self.assertEqual(self._user_count("__master__"), 0)

    def test_v1_session_enforces_quota(self):
        hdr, _ = self._login("alice", "alicepass1")
        models = {"object": "list", "data": [{"id": MODEL}]}
        reply = {"choices": [{"message": {"role": "assistant", "content": "x"}}]}
        body = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
        with mock.patch.object(gw, "list_models", return_value=models), \
                mock.patch.object(gw, "complete", return_value=reply), \
                mock.patch.dict(org_store.TIER_DAILY_LIMIT, {"free": 1}):
            self.assertEqual(self._req("POST", "/v1/chat/completions", body, hdr)[0], 200)
            st, _ = self._req("POST", "/v1/chat/completions", body, hdr)
        self.assertEqual(st, 429)


class ChatHubQuotaTest(unittest.TestCase):
    """chat_hub generation endpoints (regen/branch/edit/compare) reserve their own quota."""

    def _call(self, handler, ident):
        return chat_hub._run_assistant(
            handler, Path("."), ident, conversation_id=1, parent_id=None, provider="ollama",
            model="m", connection_id=None, gen_gate=None, num_ctx=1, lang="th",
            origin=None, source_id=None, stream=False)

    def test_exhausted_quota_raises_before_generation(self):
        handler = mock.Mock()
        handler._quota_reserve.return_value = False
        with mock.patch.object(chat_hub, "_placeholder") as ph:
            with self.assertRaises(chat_hub.ChatQuotaError):
                self._call(handler, {"username": "alice", "source": "session", "tier": "free"})
        ph.assert_not_called()

    def test_failure_after_reserve_releases(self):
        handler = mock.Mock()
        handler._quota_reserve.side_effect = lambda ident: ident.update(_quota_reserved="user") or True
        with mock.patch.object(chat_hub, "_placeholder", side_effect=RuntimeError("db")):
            with self.assertRaises(RuntimeError):
                self._call(handler, {"username": "alice", "source": "session", "tier": "free"})
        handler._chat_release.assert_called_once()

    def test_quota_error_maps_to_429(self):
        handler = mock.Mock()
        handler._require.return_value = {"username": "alice"}
        handler._read_json_body.return_value = {}
        parsed = mock.Mock(path="/api/chat/regen")
        with mock.patch.object(chat_hub, "_post_regen", side_effect=chat_hub.ChatQuotaError("q")):
            chat_hub.handle_post(handler, parsed, Path("."), None)
        self.assertEqual(handler._send_json.call_args[0][0], 429)


# ---------------------------------------------------------------- 3) tunnel
class TunnelHardeningTest(_HttpCase):
    def test_admin_cannot_start_tunnel(self):
        hdr, _ = self._login("ops", "opspass123")
        with mock.patch.object(cloud_tunnel, "start") as start:
            st, _ = self._req("POST", "/api/admin/tunnel/start", {"port": 22}, hdr)
        self.assertEqual(st, 403)
        start.assert_not_called()

    def test_ceo_start_ignores_body_port(self):
        with mock.patch.object(cloud_tunnel, "start",
                               return_value={"url": "https://a-b.trycloudflare.com"}) as start:
            st, d = self._req("POST", "/api/admin/tunnel/start", {"port": 22}, self.master)
        self.assertEqual(st, 200, d)
        start.assert_called_once_with(self.port)
        self.assertEqual(d["port"], self.port)

    def test_ceo_start_without_port_ok(self):
        with mock.patch.object(cloud_tunnel, "start",
                               return_value={"url": "https://a-b.trycloudflare.com"}) as start:
            st, _ = self._req("POST", "/api/admin/tunnel/start", {}, self.master)
        self.assertEqual(st, 200)
        start.assert_called_once_with(self.port)


class TunnelClientIpTest(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("LCA_TRUST_PROXY", None)

    def tearDown(self):
        self._env.stop()

    def test_cf_header_trusted_while_tunnel_active(self):
        with mock.patch.object(cloud_tunnel, "is_active", return_value=True):
            ip = server.resolve_client_ip("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9"})
        self.assertEqual(ip, "203.0.113.9")

    def test_cf_header_ignored_when_no_tunnel_and_no_env(self):
        with mock.patch.object(cloud_tunnel, "is_active", return_value=False):
            ip = server.resolve_client_ip("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9"})
        self.assertEqual(ip, "127.0.0.1")

    def test_remote_peer_never_trusted_even_with_tunnel(self):
        with mock.patch.object(cloud_tunnel, "is_active", return_value=True):
            ip = server.resolve_client_ip("198.51.100.7", {"CF-Connecting-IP": "203.0.113.9"})
        self.assertEqual(ip, "198.51.100.7")

    def test_is_active_false_without_proc(self):
        with mock.patch.dict(cloud_tunnel._state, {"proc": None}):
            self.assertFalse(cloud_tunnel.is_active())


# ---------------------------------------------------------------- 4) /v1 stream refund
class V1StreamRefundTest(_HttpCase):
    def setUp(self):
        super().setUp()
        rec = org_store.create_api_key(self.root, "alice", "free", "CEO")
        self.key_id, self.key = rec["key_id"], rec["key"]
        self._p = mock.patch.object(gw, "list_models",
                                    return_value={"object": "list", "data": [{"id": MODEL}]})
        self._p.start()

    def tearDown(self):
        self._p.stop()
        super().tearDown()

    def _used(self):
        return [k for k in org_store.list_api_keys(self.root) if k["key_id"] == self.key_id][0]["used_today"]

    def _stream(self, gen):
        with mock.patch.object(gw, "stream", return_value=gen):
            return self._raw("POST", "/v1/chat/completions",
                             {"model": MODEL, "stream": True,
                              "messages": [{"role": "user", "content": "hi"}]},
                             {"Authorization": f"Bearer {self.key}"})

    def test_error_after_delivered_chunk_keeps_charge(self):
        def gen():
            yield b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
            raise gw.GatewayError(502, "broke", "upstream_error")
        st, _ = self._stream(gen())
        self.assertEqual(st, 200)
        self.assertEqual(self._used(), 1)

    def test_error_before_any_chunk_refunds(self):
        def gen():
            raise gw.GatewayError(502, "broke", "upstream_error")
            yield b""  # pragma: no cover
        self._stream(gen())
        self.assertEqual(self._used(), 0)


if __name__ == "__main__":
    unittest.main()
