"""Google sign-in (/auth/google/start + /auth/google/callback) against a fake Google.

The fake token/userinfo server runs on 127.0.0.1 — no real Google endpoint is called.
It checks PKCE S256 exactly like Google: code_verifier must hash to the challenge.
"""

import base64
import contextlib
import hashlib
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import google_auth, org_store  # noqa: E402

MASTER = "master-secret-token"
CLIENT_ID = "test-client.apps.example"
CLIENT_SECRET = "fake-client-secret-DO-NOT-LEAK-7f3a"


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class FakeGoogle:
    """codes: code -> {challenge, profile}; tokens: access token -> profile."""

    def __init__(self):
        self.codes, self.tokens, self.token_requests = {}, {}, []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, status, obj):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                form = {k: v[0] for k, v in parse_qs(
                    self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
                fake.token_requests.append(form)
                entry = fake.codes.pop(form.get("code", ""), None)
                ok = (entry is not None and form.get("client_secret") == CLIENT_SECRET
                      and form.get("client_id") == CLIENT_ID
                      and form.get("grant_type") == "authorization_code"
                      and form.get("code_verifier")
                      and _s256(form["code_verifier"]) == entry["challenge"])
                if not ok:
                    self._json(400, {"error": "invalid_grant"})
                    return
                token = "fake-access-token-" + form["code"]
                fake.tokens[token] = entry["profile"]
                self._json(200, {"access_token": token, "token_type": "Bearer",
                                 "id_token": "fake-id-token", "refresh_token": "fake-refresh"})

            def do_GET(self):
                auth = self.headers.get("Authorization") or ""
                profile = fake.tokens.get(auth[7:]) if auth.startswith("Bearer ") else None
                if profile is None:
                    self._json(401, {"error": "invalid_token"})
                    return
                self._json(200, profile)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class GoogleLoginTest(unittest.TestCase):
    def setUp(self):
        self._saved = (google_auth.AUTH_URL, google_auth.TOKEN_URL, google_auth.USERINFO_URL)
        self.fake = FakeGoogle()
        google_auth.AUTH_URL = self.fake.base + "/authorize"
        google_auth.TOKEN_URL = self.fake.base + "/token"
        google_auth.USERINFO_URL = self.fake.base + "/userinfo"
        google_auth.clear_pending()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.root, MASTER))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.seen = []   # every response (status, headers, body) for the leak check
        self.configure()
        org_store.create_user(self.root, "boss", "password123", "CEO")

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.fake.close()
        google_auth.AUTH_URL, google_auth.TOKEN_URL, google_auth.USERINFO_URL = self._saved
        self._tmp.cleanup()

    def configure(self, **extra):
        cfg = {"GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET,
               "GOOGLE_REDIRECT_URI": f"http://127.0.0.1:{self.port}/auth/google/callback"}
        cfg.update(extra)
        (self.root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        hdrs["_cookies"] = [v for k, v in resp.getheaders() if k.lower() == "set-cookie"]
        conn.close()
        self.seen.append((resp.status, json.dumps(resp.getheaders()), body))
        return resp.status, hdrs, body

    def start(self, next_path=None):
        st, h, _ = self.get("/auth/google/start" + (f"?next={next_path}" if next_path else ""))
        self.assertEqual(st, 302)
        loc = urlsplit(h["location"])
        q = {k: v[0] for k, v in parse_qs(loc.query).items()}
        cookie = h["set-cookie"].split(";")[0]
        return q, cookie, h

    def login(self, sub="g-123", email="alice@example.com", verified=True, challenge=None,
              state=None, cookie=None, next_path=None):
        q, real_cookie, _ = self.start(next_path)
        code = "code-" + q["state"][:8] + str(len(self.fake.token_requests))
        self.fake.codes[code] = {
            "challenge": challenge or q["code_challenge"],
            "profile": {"sub": sub, "email": email, "email_verified": verified, "name": "Alice"}}
        st = q["state"] if state is None else state
        hdr = {"Cookie": real_cookie if cookie is None else cookie}
        return self.get(f"/auth/google/callback?state={st}&code={code}", hdr)

    def code_and_cookie(self, h):
        code = h["location"].split("#lca_login_code=", 1)[1]
        cookies = [c for c in h["_cookies"] if c.startswith(google_auth.FINISH_COOKIE + "=")]
        self.assertEqual(len(cookies), 1)
        c = cookies[0]
        for attr in ("HttpOnly", "SameSite=Lax", "Path=/api/auth/google"):
            self.assertIn(attr, c)
        return code, c.split(";")[0]

    def finish(self, code, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdr = {"Content-Type": "application/json"}
        if cookie:
            hdr["Cookie"] = cookie
        conn.request("POST", google_auth.FINISH_PATH, body=json.dumps({"code": code}), headers=hdr)
        resp = conn.getresponse()
        body = json.loads(resp.read() or b"{}")
        hdrs = [v for k, v in resp.getheaders() if k.lower() == "set-cookie"]
        conn.close()
        return resp.status, body, hdrs

    def google_users(self):
        return [r["username"] for r in org_store.list_users(self.root) if r["username"] != "boss"]

    def count(self, sql, params=()):
        return org_store._read(self.root, sql, params, one=True)[0]

    # ---- happy path ----
    def test_login_creates_session_and_redirects_to_chat(self):
        q, _cookie, h = self.start()
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["client_id"], CLIENT_ID)
        self.assertIn("HttpOnly", h["set-cookie"])
        self.assertIn("SameSite=Lax", h["set-cookie"])
        st, h, _ = self.login()
        self.assertEqual(st, 302)
        self.assertTrue(h["location"].startswith("/chat#lca_login_code="), h["location"])
        self.assertNotIn("lcs_", h["location"])       # never a session in the URL
        self.assertTrue(any(c.startswith(google_auth.STATE_COOKIE + "=;") and "Max-Age=0" in c
                            for c in h["_cookies"]))   # state cookie cleared
        st, data, _ = self.finish(*self.code_and_cookie(h))
        self.assertEqual(st, 200)
        token = data["token"]
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/me", headers={"X-Auth-Token": token})
        me = json.loads(conn.getresponse().read())
        conn.close()
        self.assertEqual(me["username"], "alice@example.com")
        self.assertEqual(me["role"], "USER")
        self.assertEqual(me["tier"], "free")
        self.assertEqual(me["tokens"]["limit"], org_store.FREE_MONTHLY_TOKENS)
        sent = self.fake.token_requests[-1]
        self.assertTrue(sent["code_verifier"])
        self.assertEqual(sent["redirect_uri"], f"http://127.0.0.1:{self.port}/auth/google/callback")

    def test_next_is_internal_only(self):
        st, h, _ = self.login(next_path="//evil.example/x")
        self.assertEqual(st, 302)
        self.assertTrue(h["location"].startswith("/chat#"), h["location"])

    # ---- state ----
    def test_wrong_or_missing_state_is_400_and_creates_no_user(self):
        st, _, body = self.login(state="forged-state")
        self.assertEqual(st, 400)
        self.assertIn("state", json.loads(body)["error"])
        st, _, _ = self.login(cookie="")                       # no state cookie
        self.assertEqual(st, 400)
        st, _, _ = self.login(cookie="lca_google_state=other")  # cookie of another login
        self.assertEqual(st, 400)
        st, _, _ = self.get("/auth/google/callback?code=x")     # no state at all
        self.assertEqual(st, 400)
        self.assertEqual(self.google_users(), [])
        self.assertEqual(self.count("SELECT COUNT(*) FROM org_google_accounts"), 0)

    def test_state_is_single_use(self):
        q, cookie, _ = self.start()
        self.fake.codes["c1"] = {"challenge": q["code_challenge"],
                                 "profile": {"sub": "s", "email": "a@example.com",
                                             "email_verified": True}}
        path = f"/auth/google/callback?state={q['state']}&code=c1"
        self.assertEqual(self.get(path, {"Cookie": cookie})[0], 302)
        self.assertEqual(self.get(path, {"Cookie": cookie})[0], 400)

    # ---- PKCE ----
    def test_invalid_code_verifier_is_400_and_creates_no_user(self):
        st, _, _ = self.login(challenge=_s256("some-other-verifier"))
        self.assertEqual(st, 400)
        self.assertEqual(self.google_users(), [])

    def test_missing_code_verifier_is_400(self):
        q, cookie, _ = self.start()
        with google_auth._pending_lock:   # simulate a lost verifier
            _v, nxt, exp, cl = google_auth._pending[q["state"]]
            google_auth._pending[q["state"]] = ("", nxt, exp, cl)
        st, _, _ = self.get(f"/auth/google/callback?state={q['state']}&code=c", {"Cookie": cookie})
        self.assertEqual(st, 400)
        self.assertEqual(self.google_users(), [])

    # ---- idempotent account ----
    def test_five_logins_same_account_one_user_at_most_one_key(self):
        for _ in range(5):
            self.assertEqual(self.login()[0], 302)
        self.assertEqual(self.google_users(), ["alice@example.com"])
        self.assertEqual(self.count("SELECT COUNT(*) FROM org_google_accounts"), 1)
        self.assertLessEqual(self.count("SELECT COUNT(*) FROM org_api_keys WHERE owner=?",
                                        ("alice@example.com",)), 1)
        first = org_store.issue_google_internal_token(self.root, "alice@example.com")
        self.assertTrue(first.startswith("lca_f_"))
        self.assertIsNone(org_store.issue_google_internal_token(self.root, "alice@example.com"))
        self.assertEqual(self.count("SELECT COUNT(*) FROM org_api_keys WHERE owner=?",
                                    ("alice@example.com",)), 1)

    def test_concurrent_sign_in_is_idempotent(self):
        errors = []

        def go():
            try:
                org_store.google_sign_in(self.root, "sub-c", "carol@example.com", "Carol")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=go) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.google_users(), ["carol@example.com"])

    def test_google_cannot_take_over_password_account(self):
        org_store.create_user(self.root, "bob@example.com", "password123", "ADMIN",
                              created_by_role="CEO")
        st, _, _ = self.login(sub="g-bob", email="bob@example.com")
        self.assertEqual(st, 403)
        self.assertEqual(self.count("SELECT COUNT(*) FROM org_google_accounts"), 0)

    def test_disabled_google_user_cannot_sign_in(self):
        self.assertEqual(self.login()[0], 302)
        org_store.set_user_active(self.root, "alice@example.com", False, "CEO")
        self.assertEqual(self.login()[0], 403)

    def test_unverified_email_rejected(self):
        st, _, body = self.login(verified=False)
        self.assertEqual(st, 403)
        self.assertIn("ยืนยัน", json.loads(body)["error"])
        self.assertEqual(self.google_users(), [])

    # ---- secrets ----
    def test_secret_and_tokens_never_in_responses_or_logs(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.login()
            self.login(state="bad")
            self.login(challenge=_s256("x"))
            self.login(verified=False)
            self.get("/api/auth/providers")
        blob = out.getvalue() + "".join(f"{s}{h}{b}" for s, h, b in self.seen)
        for secret in (CLIENT_SECRET, "fake-access-token", "fake-id-token", "fake-refresh"):
            self.assertNotIn(secret, blob)
        self.assertNotIn("code=code-", out.getvalue())   # OAuth code redacted in access log
        self.assertNotIn("lcs_", out.getvalue())          # session token never logged

    # ---- config ----
    def test_not_configured_hides_button_and_routes_explain(self):
        (self.root / "config.json").write_text("{}", encoding="utf-8")
        st, _, body = self.get("/api/auth/providers")
        self.assertEqual(json.loads(body), {"google": False})
        st, _, body = self.get("/auth/google/start")
        self.assertEqual(st, 503)
        self.assertIn("GOOGLE_CLIENT_ID", json.loads(body)["error"])
        st, _, _ = self.get("/auth/google/callback?state=x&code=y")
        self.assertEqual(st, 503)
        st, _, html = self.get("/login")
        self.assertIn('id="google-box" hidden', html)

    def test_configured_provider_flag(self):
        st, _, body = self.get("/api/auth/providers")
        self.assertEqual(json.loads(body), {"google": True})

    def test_non_local_http_redirect_uri_disables_google(self):
        self.configure(GOOGLE_REDIRECT_URI="http://lca.example.com/auth/google/callback")
        st, _, body = self.get("/auth/google/start")
        self.assertEqual(st, 503)
        self.assertIn("GOOGLE_REDIRECT_URI", json.loads(body)["error"])

    # ---- pending-state flood (DoS) ----
    def test_flood_from_one_client_does_not_evict_another_clients_pending(self):
        victim_state, _ = google_auth.begin("/chat", client="10.1.1.1")
        for _ in range(google_auth.MAX_PENDING + 5):
            google_auth.begin("/chat", client="10.9.9.9")
        self.assertIsNotNone(google_auth.take(victim_state, victim_state))
        self.assertLessEqual(sum(1 for v in google_auth._pending.values() if v[3] == "10.9.9.9"),
                             google_auth.MAX_PENDING_PER_CLIENT)

    def test_http_start_flood_from_one_ip_does_not_break_another_ips_login(self):
        victim = {"X-Forwarded-For": "10.1.1.1"}
        with mock.patch.dict(os.environ, {"LCA_TRUST_PROXY": "1"}):
            st, h, _ = self.get("/auth/google/start", victim)
            self.assertEqual(st, 302)
            q = {k: v[0] for k, v in parse_qs(urlsplit(h["location"]).query).items()}
            cookie = h["set-cookie"].split(";")[0]
            statuses = set()
            for _ in range(261):   # unauthenticated flood from another IP
                statuses.add(self.get("/auth/google/start", {"X-Forwarded-For": "10.9.9.9"})[0])
            self.assertIn(429, statuses)   # per-IP limit on /auth/google/start
            self.fake.codes["victim"] = {"challenge": q["code_challenge"],
                                         "profile": {"sub": "v-1", "email": "vic@example.com",
                                                     "email_verified": True, "name": "V"}}
            st, h, _ = self.get(f"/auth/google/callback?state={q['state']}&code=victim",
                                dict(victim, Cookie=cookie))
        self.assertEqual(st, 302, h)
        self.assertIn("#lca_login_code=", h["location"])

    # ---- one-time login code (login CSRF / session fixation) ----
    def _me(self, token):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/me", headers={"X-Auth-Token": token})
        r = conn.getresponse()
        r.read()
        conn.close()
        return r.status

    def test_finish_without_cookie_is_400_no_session(self):
        code, _ = self.code_and_cookie(self.login()[1])
        st, data, set_cookies = self.finish(code)
        self.assertEqual(st, 400)
        self.assertNotIn("token", data)
        self.assertTrue(any("Max-Age=0" in c for c in set_cookies))

    def test_finish_with_wrong_cookie_is_400(self):
        code, _ = self.code_and_cookie(self.login()[1])
        st, data, _ = self.finish(code, google_auth.FINISH_COOKIE + "=nope")
        self.assertEqual((st, "token" in data), (400, False))

    def test_finish_code_is_single_use(self):
        code, cookie = self.code_and_cookie(self.login()[1])
        self.assertEqual(self.finish(code, cookie)[0], 200)
        st, data, _ = self.finish(code, cookie)
        self.assertEqual((st, "token" in data), (400, False))

    def test_finish_expired_code_is_400(self):
        code, cookie = self.code_and_cookie(self.login()[1])
        later = google_auth.time.time() + google_auth.LOGIN_CODE_TTL_SECONDS + 1
        with mock.patch.object(google_auth.time, "time", return_value=later):
            st, data, _ = self.finish(code, cookie)
        self.assertEqual((st, "token" in data), (400, False))

    def test_correct_flow_issues_working_session(self):
        code, cookie = self.code_and_cookie(self.login()[1])
        st, data, set_cookies = self.finish(code, cookie)
        self.assertEqual(st, 200)
        self.assertEqual(data["username"], "alice@example.com")
        self.assertEqual(self._me(data["token"]), 200)
        self.assertTrue(any(c.startswith(google_auth.FINISH_COOKIE + "=;") and "Max-Age=0" in c
                            for c in set_cookies))

    def test_attacker_code_fails_in_victim_browser(self):
        # attacker logs in with own Google account and sends the code link to a victim
        code, attacker_cookie = self.code_and_cookie(
            self.login(sub="g-evil", email="evil@x.io")[1])
        _vcode, victim_cookie = self.code_and_cookie(
            self.login(sub="g-vic", email="vic@x.io")[1])
        st, data, _ = self.finish(code, victim_cookie)   # victim's own, different cookie
        self.assertEqual((st, "token" in data), (400, False))
        self.assertEqual(self.finish(code)[0], 400)       # victim without any cookie
        self.assertEqual(self.finish(code, attacker_cookie)[0], 400)   # consumed

    def test_finish_cookie_secure_only_on_https(self):
        handler = server.make_handler(self.root, MASTER)
        c = handler._google_finish_cookie(
            None, {"redirect_uri": "https://lca.example.com/auth/google/callback"}, "v", 60)
        self.assertIn("; Secure", c)
        c = handler._google_finish_cookie(
            None, {"redirect_uri": "http://127.0.0.1/auth/google/callback"}, "v", 60)
        self.assertNotIn("Secure", c)

    # ---- email case normalization ----
    def test_mixed_case_email_cannot_create_lookalike_of_password_account(self):
        org_store.create_user(self.root, "Mixed@x.io", "password123", "ADMIN",
                              created_by_role="CEO")
        self.assertEqual(self.login(sub="g-mixed", email="mixed@x.io")[0], 403)
        self.assertEqual(self.login(sub="g-mixed2", email="MIXED@X.IO")[0], 403)
        self.assertEqual(self.count("SELECT COUNT(*) FROM org_google_accounts"), 0)
        self.assertEqual(self.count(
            "SELECT COUNT(*) FROM org_users WHERE lower(username)='mixed@x.io'"), 1)

    def test_google_username_is_lowercased(self):
        h = self.login(sub="g-up", email="Upper@Example.COM")[1]
        st, data, _ = self.finish(*self.code_and_cookie(h))
        self.assertEqual(data["username"], "upper@example.com")

    # ---- app.js never stores a raw fragment token ----
    def test_app_js_has_no_fragment_to_key_path(self):
        import re
        js = (Path(server.__file__).parent / "app" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("lca_login=", js)
        self.assertNotIn("takeLoginFragment", js)
        self.assertNotIn("w.lca = {    getKey", js)
        self.assertIn("/api/auth/google/finish", js)
        args = [m.group(1).strip() for m in re.finditer(r"setKey\(([^)]*)\)", js)]
        self.assertIn("data.token", args)
        for bad in ("loginCode", "code", "loginToken", "m[1]"):
            self.assertNotIn(bad, args)
        self.assertIn("serviceWorker", js)   # PWA registration kept after rebase

    def test_redirect_uri_rules(self):
        ok = google_auth.redirect_uri_allowed
        self.assertTrue(ok("http://localhost:8421/auth/google/callback"))
        self.assertTrue(ok("http://127.0.0.1:9431/auth/google/callback"))
        self.assertTrue(ok("https://lca.example.com/auth/google/callback"))
        for bad in ("http://lca.example.com/auth/google/callback",
                    "http://127.0.0.1.evil.com/auth/google/callback",
                    "http://user@localhost/auth/google/callback",
                    "http://localhost/other", "javascript:alert(1)", "",
                    "https://lca.example.com/auth/google/callback?x=1"):
            self.assertFalse(ok(bad), bad)


if __name__ == "__main__":
    unittest.main()
