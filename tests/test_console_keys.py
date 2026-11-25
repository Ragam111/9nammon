"""Tests for the LCA Console API keys page (/console/keys) and its backend fields.

Real server on a random port, master token set (not local mode), temp project root.
"""
import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from app import session_store  # noqa: E402

MASTER = "master-secret-token"
MASTER_HDR = {"X-Auth-Token": MASTER}
PAGE_JS = ROOT / "app" / "console-keys.js"


class ConsoleKeysTest(unittest.TestCase):
    def setUp(self) -> None:
        session_store.clear()
        self._tmp = tempfile.TemporaryDirectory()
        handler = server.make_handler(Path(self._tmp.name), MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        for user, pw, role in (("boss", "password123", "CEO"),
                               ("alice", "alicepass1", "USER"),
                               ("ops", "opspass123", "ADMIN")):
            st, d = self._req("POST", "/api/admin/users",
                              {"username": user, "password": pw, "role": role}, MASTER_HDR)
            self.assertEqual(st, 200, d)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()
        session_store.clear()

    def _raw(self, method: str, path: str, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, raw, hdrs

    def _req(self, method: str, path: str, body=None, headers=None):
        st, raw, _ = self._raw(method, path, body, headers)
        return st, (json.loads(raw) if raw else {})

    def _token(self, user: str, pw: str) -> str:
        st, d = self._req("POST", "/api/auth/login", {"username": user, "password": pw})
        self.assertEqual(st, 200, d)
        return d["token"]

    def _create(self, name: str = "ci-bot", owner: str = "alice", tier: str = "free",
                headers=None):
        return self._req("POST", "/api/admin/apikeys",
                         {"name": name, "owner": owner, "tier": tier}, headers or MASTER_HDR)

    # ---- page gate ----
    def test_page_served_for_admin(self) -> None:
        tok = self._token("ops", "opspass123")
        st, raw, hdrs = self._raw("GET", "/console/keys", headers={"X-Auth-Token": tok})
        self.assertEqual(st, 200)
        self.assertIn("text/html", hdrs.get("content-type", ""))
        self.assertIn("page-console-keys", raw)
        self.assertIn("/console-keys.js", raw)
        st, raw, _ = self._raw("GET", "/console/keys", headers={"Cookie": f"lca_key={tok}"})
        self.assertEqual(st, 200)

    def test_page_blocked_for_user_and_anonymous(self) -> None:
        st, _, hdrs = self._raw("GET", "/console/keys")
        self.assertEqual(st, 302)
        self.assertEqual(hdrs.get("location"), "/login?next=/console/keys")
        tok = self._token("alice", "alicepass1")
        st, raw, _ = self._raw("GET", "/console/keys", headers={"Cookie": f"lca_key={tok}"})
        self.assertEqual(st, 403)
        self.assertNotIn("page-console-keys", raw)

    def test_page_is_registered_as_admin(self) -> None:
        self.assertIn("/console/keys", server.STATIC_ROUTES)
        self.assertEqual(server.PROTECTED_PAGES.get("/console/keys"), "ADMIN")

    # ---- list / create ----
    def test_create_returns_full_key_once_and_list_shows_prefix_only(self) -> None:
        st, d = self._create()
        self.assertEqual(st, 200, d)
        issued = d["api_key"]
        full = issued["key"]
        self.assertTrue(full.startswith("lca_f_"))
        self.assertEqual(issued["name"], "ci-bot")
        self.assertEqual(issued["created_by"], "__master__")
        st, lst = self._req("GET", "/api/admin/apikeys", headers=MASTER_HDR)
        self.assertEqual(st, 200, lst)
        raw = json.dumps(lst)
        self.assertNotIn(full, raw)
        self.assertNotIn(full[12:], raw)
        rows = lst["api_keys"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["prefix"], full[:12])
        self.assertEqual(row["name"], "ci-bot")
        self.assertEqual(row["owner"], "alice")
        self.assertEqual(row["created_by"], "__master__")
        self.assertTrue(row["created_at"])
        self.assertEqual(row["used_today"], 0)
        self.assertGreater(row["daily_limit"], 0)
        self.assertTrue(row["active"])
        for k, v in row.items():
            self.assertNotIn("hash", k)
            self.assertNotEqual(k, "key")
            if isinstance(v, str):
                self.assertNotRegex(v, r"^[0-9a-f]{64}$", f"{k} looks like a hash")

    def test_created_by_is_admin_username(self) -> None:
        tok = self._token("ops", "opspass123")
        st, d = self._create(name="ops-key", headers={"X-Auth-Token": tok})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["api_key"]["created_by"], "ops")

    def test_name_is_trimmed_and_capped(self) -> None:
        st, d = self._create(name="  " + "x" * 200 + "  ")
        self.assertEqual(st, 200, d)
        self.assertEqual(len(d["api_key"]["name"]), 64)

    def test_create_bad_tier_is_400(self) -> None:
        st, _ = self._create(tier="gold")
        self.assertEqual(st, 400)

    def test_user_cannot_list_or_create(self) -> None:
        tok = self._token("alice", "alicepass1")
        hdr = {"X-Auth-Token": tok}
        st, _ = self._req("GET", "/api/admin/apikeys", headers=hdr)
        self.assertEqual(st, 403)
        st, _ = self._create(headers=hdr)
        self.assertEqual(st, 403)

    # ---- revoke ----
    def test_revoke_makes_key_fail_on_v1_models(self) -> None:
        _, d = self._create()
        full = d["api_key"]["key"]
        bearer = {"Authorization": f"Bearer {full}"}
        st, _ = self._req("GET", "/v1/models", headers=bearer)
        self.assertEqual(st, 200)
        st, out = self._req("POST", "/api/admin/apikeys/revoke",
                            {"key_id": d["api_key"]["key_id"]}, MASTER_HDR)
        self.assertEqual(st, 200, out)
        st, _ = self._req("GET", "/v1/models", headers=bearer)
        self.assertEqual(st, 401)
        _, lst = self._req("GET", "/api/admin/apikeys", headers=MASTER_HDR)
        self.assertFalse(lst["api_keys"][0]["active"])

    # ---- XSS: page JS never builds HTML from data ----
    def test_page_js_has_no_html_sinks(self) -> None:
        src = PAGE_JS.read_text(encoding="utf-8")
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(sink, src, sink)
        html = (ROOT / "app" / "console-keys.html").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", html)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_xss_name_stays_text_in_node(self) -> None:
        script = ROOT / "tests" / "js" / "console_keys_xss.js"
        out = subprocess.run(["node", str(script), str(PAGE_JS)],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("OK", out.stdout)


if __name__ == "__main__":
    unittest.main()
