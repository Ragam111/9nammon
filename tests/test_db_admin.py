"""Tests for the read-only DB admin (/admin/db, /api/admin/db/*). Temp project root only."""
import http.client
import json
import sqlite3
from contextlib import closing
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from app import db, db_admin, session_store  # noqa: E402

MASTER = "master-secret-token"
MASTER_HDR = {"X-Auth-Token": MASTER}


class DbAdminUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        db.ensure_ready(self.root)
        with db.write_txn(self.root) as c:
            c.execute("INSERT INTO org_users(username, role, password) VALUES (?,?,?)",
                      ("u1", "USER", "pbkdf2$secretvalue"))
            c.execute("INSERT INTO org_api_keys(key_id, key_hash, prefix, owner, tier) "
                      "VALUES (?,?,?,?,?)", ("k1", "deadbeefhash", "lca_ab", "u1", "free"))
            c.execute("INSERT INTO auth_sessions VALUES (?,?,?,?,?,?)",
                      ("tokhash123", "=cmd|' /C calc'!A0", "USER", "free", 1.0, 2.0))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_tables_counts_and_version(self) -> None:
        d = db_admin.list_tables(self.root)
        self.assertEqual(d["schema_version"], db.code_version())
        by = {t["name"]: t for t in d["tables"]}
        self.assertEqual(by["org_users"]["rows"], 1)
        self.assertIn("password", by["org_users"]["redacted"])

    def test_redaction_every_sensitive_migration_column(self) -> None:
        with closing(db_admin.connect_ro(self.root)) as conn:
            for t in db_admin._tables(conn):
                for c in db_admin._columns(conn, t):
                    parts = c["name"].lower().split("_")
                    if any(w in parts for w in ("hash", "secret", "password", "token", "salt",
                                                "verifier", "session")):
                        self.assertTrue(db_admin.is_sensitive(c["name"]), (t, c["name"]))
        for table, secret in (("org_users", "secretvalue"), ("org_api_keys", "deadbeefhash"),
                              ("auth_sessions", "tokhash123")):
            dump = json.dumps(db_admin.browse(self.root, table), ensure_ascii=False)
            self.assertNotIn(secret, dump)
            self.assertIn("••••", dump)

    def test_injection_rejected(self) -> None:
        for bad in ("org_users;DROP TABLE org_users", "sqlite_master", "", None, '"org_users"'):
            with self.assertRaises(db_admin.DbAdminError):
                db_admin.browse(self.root, bad)
        for page in ("-1", "0", "1 OR 1=1", "99999999999", "abc"):
            with self.assertRaises(db_admin.DbAdminError):
                db_admin.browse(self.root, "org_users", page=page)
        with self.assertRaises(db_admin.DbAdminError):
            db_admin.browse(self.root, "org_users", page_size=101)
        with self.assertRaises(db_admin.DbAdminError):
            db_admin.browse(self.root, "org_users", order_by="role; DROP TABLE x")
        d = db_admin.browse(self.root, "org_users", search="' OR 1=1 --")
        self.assertEqual(d["total"], 0)
        self.assertEqual(db_admin.browse(self.root, "org_users", search="%")["total"], 0)
        self.assertEqual(db_admin.browse(self.root, "org_users", search="u1")["total"], 1)
        self.assertEqual(db_admin.list_tables(self.root)["tables"][0]["name"] != "", True)

    def test_search_does_not_match_secret_columns(self) -> None:
        self.assertEqual(db_admin.browse(self.root, "org_users", search="secretvalue")["total"], 0)

    def test_order(self) -> None:
        d = db_admin.browse(self.root, "org_users", order_by="-username")
        self.assertEqual(d["total"], 1)

    def test_order_by_sensitive_column_rejected(self) -> None:
        for t, col in (("org_users", "password"), ("org_api_keys", "-key_hash"),
                       ("auth_sessions", "token_hash")):
            with self.assertRaises(db_admin.DbAdminError):
                db_admin.browse(self.root, t, order_by=col)

    def test_sensitive_re_is_narrow(self) -> None:
        for c in ("tokens_in", "tokens_out", "tokens_est", "prefix", "sha256", "key_id",
                  "username", "connection_id", "session_count"):
            self.assertFalse(db_admin.is_sensitive(c), c)
        for c in ("token_hash", "token", "refresh_token", "password", "secret", "client_secret",
                  "salt", "verifier", "key_hash", "session", "session_id", "sid"):
            self.assertTrue(db_admin.is_sensitive(c), c)
        with closing(db_admin.connect_ro(self.root)) as conn:
            cols = {(t, c["name"]) for t in db_admin._tables(conn)
                    for c in db_admin._columns(conn, t)}
        for name in ("tokens_in", "tokens_out", "tokens_est"):
            self.assertIn(("messages", name), cols)
            self.assertFalse(db_admin.is_sensitive(name))
        for t, name in (("auth_sessions", "token_hash"), ("org_api_keys", "key_hash"),
                        ("org_users", "password")):
            self.assertIn((t, name), cols)
            self.assertTrue(db_admin.is_sensitive(name))

    def test_read_only_connection_refuses_writes(self) -> None:
        with closing(db_admin.connect_ro(self.root)) as conn:
            with self.assertRaises(sqlite3.Error):
                conn.execute("DELETE FROM org_users")
            with self.assertRaises(sqlite3.Error):
                conn.execute("CREATE TABLE x(a)")

    def test_csv_injection_and_redaction(self) -> None:
        for v in ("=1+1", "+1", "-1", "@SUM", "\tx"):
            self.assertTrue(db_admin.csv_safe(v).startswith("'"))
        self.assertEqual(db_admin.csv_safe("ok"), "ok")
        out = db_admin.export_csv(self.root, "auth_sessions")
        self.assertNotIn("tokhash123", out)
        self.assertIn("'=cmd", out)

    def test_summary_and_check(self) -> None:
        s = db_admin.summary(self.root)
        self.assertEqual(s["users_by_role"], {"USER": 1})
        self.assertEqual(s["active_keys"], 1)
        self.assertGreater(s["db_bytes"], 0)
        self.assertTrue(db_admin.quick_check(self.root)["ok"])


class DbAdminHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        session_store.clear()
        db_admin._DENIED_SEEN.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        handler = server.make_handler(self.root, MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        for user, pw, role in (("boss", "password123", "CEO"), ("ops", "opspass123", "ADMIN"),
                               ("alice", "alicepass1", "USER")):
            st, d = self._req("POST", "/api/admin/users",
                              {"username": user, "password": pw, "role": role}, MASTER_HDR)
            self.assertEqual(st, 200, d)
        self.tok = {u: self._login(u, p) for u, p in
                    (("boss", "password123"), ("ops", "opspass123"), ("alice", "alicepass1"))}

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()
        session_store.clear()

    def _raw(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers=headers or {})
        r = conn.getresponse()
        raw = r.read().decode("utf-8")
        h = {k.lower(): v for k, v in r.getheaders()}
        conn.close()
        return r.status, raw, h

    def _req(self, method, path, body=None, headers=None):
        st, raw, _ = self._raw(method, path, body, headers)
        try:
            return st, json.loads(raw) if raw else {}
        except ValueError:
            return st, {"raw": raw}

    def _login(self, user, pw):
        st, d = self._req("POST", "/api/auth/login", {"username": user, "password": pw})
        self.assertEqual(st, 200, d)
        return d["token"]

    def _h(self, user):
        return {"X-Auth-Token": self.tok[user]}

    def test_ceo_ok_others_denied(self) -> None:
        paths = ["/api/admin/db/tables", "/api/admin/db/summary",
                 "/api/admin/db/rows?table=org_users", "/api/admin/db/export?table=org_users"]
        for p in paths:
            self.assertEqual(self._raw("GET", p, headers=self._h("boss"))[0], 200, p)
            self.assertEqual(self._raw("GET", p, headers=self._h("ops"))[0], 403, p)
            self.assertEqual(self._raw("GET", p, headers=self._h("alice"))[0], 403, p)
            self.assertEqual(self._raw("GET", p)[0], 401, p)
            self.assertEqual(self._raw("GET", p, headers={"X-Auth-Token": "bogus"})[0], 401, p)
        self.assertEqual(self._req("POST", "/api/admin/db/check", {}, self._h("boss"))[0], 200)
        self.assertEqual(self._req("POST", "/api/admin/db/check", {}, self._h("ops"))[0], 403)
        self.assertEqual(self._req("POST", "/api/admin/db/check", {})[0], 401)

    def test_denied_calls_are_audited(self) -> None:
        self.assertEqual(self._raw("GET", "/api/admin/db/tables", headers=self._h("ops"))[0], 403)
        self.assertEqual(self._raw("GET", "/api/admin/db/summary")[0], 401)
        self.assertEqual(self._req("POST", "/api/admin/db/check", {}, self._h("alice"))[0], 403)
        with closing(sqlite3.connect(db.db_path(self.root))) as c:
            msgs = [r[0] for r in c.execute(
                "SELECT message FROM server_events WHERE kind='db_admin_denied'")]
        self.assertIn("403 ops /api/admin/db/tables", msgs)
        self.assertIn("401 - /api/admin/db/summary", msgs)
        self.assertIn("403 alice /api/admin/db/check", msgs)

    def test_denied_audit_deduped_per_ip_path(self) -> None:
        for _ in range(5):
            self.assertEqual(self._raw("GET", "/api/admin/db/tables", headers=self._h("ops"))[0], 403)
        self.assertEqual(self._raw("GET", "/api/admin/db/summary")[0], 401)
        with closing(sqlite3.connect(db.db_path(self.root))) as c:
            msgs = [r[0] for r in c.execute(
                "SELECT message FROM server_events WHERE kind='db_admin_denied'")]
        self.assertEqual(msgs.count("403 ops /api/admin/db/tables"), 1)
        self.assertEqual(msgs.count("401 - /api/admin/db/summary"), 1)

    def test_denied_window_unit(self) -> None:
        self.assertTrue(db_admin._denied_allowed("1.2.3.4", "/p", now=1000.0))
        self.assertFalse(db_admin._denied_allowed("1.2.3.4", "/p", now=1059.0))
        self.assertTrue(db_admin._denied_allowed("5.6.7.8", "/p", now=1059.0))
        self.assertTrue(db_admin._denied_allowed("1.2.3.4", "/q", now=1059.0))
        self.assertTrue(db_admin._denied_allowed("1.2.3.4", "/p", now=1061.0))

    def test_http_order_by_sensitive_400(self) -> None:
        st = self._raw("GET", "/api/admin/db/rows?table=org_users&order=password",
                       headers=self._h("boss"))[0]
        self.assertEqual(st, 400)

    def test_http_injection_and_redaction(self) -> None:
        h = self._h("boss")
        for q in ("table=org_users;DROP", "table=sqlite_master", "table=org_users&page=-1",
                  "table=org_users&page=1%20OR%201=1", "table=org_users&page=999999999999",
                  "table=org_users&order=role;DROP"):
            self.assertEqual(self._raw("GET", "/api/admin/db/rows?" + q, headers=h)[0], 400, q)
        st, d = self._req("GET", "/api/admin/db/rows?table=org_users&q=%27%20OR%201%3D1--", headers=h)
        self.assertEqual((st, d["total"]), (200, 0))
        st, raw, _ = self._raw("GET", "/api/admin/db/rows?table=org_users", headers=h)
        self.assertNotIn("pbkdf2", raw)
        st, raw, hd = self._raw("GET", "/api/admin/db/export?table=auth_sessions", headers=h)
        self.assertIn("text/csv", hd["content-type"])
        for t in self.tok.values():
            self.assertNotIn(t, raw)
        self.assertEqual(self._req("GET", "/api/admin/db/tables", headers=h)[1]["schema_version"],
                         db.code_version())

    def test_page_gate_and_audit(self) -> None:
        st, raw, _ = self._raw("GET", "/admin/db", headers=self._h("boss"))
        self.assertEqual(st, 200)
        self.assertIn("page-db-admin", raw)
        self.assertNotIn("innerHTML", raw)
        self.assertEqual(self._raw("GET", "/admin/db", headers=self._h("ops"))[0], 403)
        self.assertIn(self._raw("GET", "/admin/db")[0], (302, 303, 401))
        self._raw("GET", "/api/admin/db/summary", headers=self._h("boss"))
        time.sleep(0.05)
        with db.read_txn(self.root) as c:
            n = c.execute("SELECT COUNT(*) FROM server_events WHERE kind='db_admin'").fetchone()[0]
        self.assertGreaterEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
