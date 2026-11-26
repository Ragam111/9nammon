"""WP-A: LCA-Admin edition gate (loopback / proxy / tunnel / CSRF / roles), /api/admin/nodes,
lca_admin_app.build_server and lca_app first-run. Temp project root only, no real nodes."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lca_admin_app  # noqa: E402
import lca_app  # noqa: E402
import server  # noqa: E402
from app import cloud_tunnel, edition, org_store, session_store  # noqa: E402
from test_edition_split import call, start  # noqa: E402

CSRF = "c" * 40
CSRF_HDR = {"X-LCA-CSRF": CSRF}


def bearer(tok: str, csrf: bool = False) -> dict:
    h = {"X-Auth-Token": tok}
    if csrf:
        h["X-LCA-CSRF"] = CSRF
        h["Cookie"] = f"lca_csrf={CSRF}"
    return h


def page_cookie(tok: str) -> dict:
    return {"Cookie": f"lca_key={tok}"}


class AdminEditionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        org_store.init_storage(self.root)
        self.httpd, self.port, self.handler = start(self.root, "admin")
        self.tok = {r: session_store.create(f"u_{r.lower()}", r)["token"]
                    for r in ("CEO", "ADMIN", "USER")}

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    # --- acceptance 2: roles ---
    def test_admin_page_roles(self) -> None:
        status, hdrs, _ = call(self.port, "GET", "/admin")
        self.assertEqual(status, 302)
        self.assertTrue(hdrs["Location"].startswith("/login"))
        status, _h, _b = call(self.port, "GET", "/admin", page_cookie(self.tok["ADMIN"]))
        self.assertEqual(status, 403)
        status, hdrs, body = call(self.port, "GET", "/admin", page_cookie(self.tok["CEO"]))
        self.assertEqual(status, 200)
        self.assertIn(b"LCA Admin", body)
        self.assertIn("lca_csrf=", hdrs.get("Set-Cookie", ""))

    def test_db_page_needs_ceo_and_auto_bypass_is_off(self) -> None:
        status, _h, _b = call(self.port, "GET", "/admin/db")
        self.assertEqual(status, 302)
        status, _h, _b = call(self.port, "GET", "/admin/db", page_cookie(self.tok["ADMIN"]))
        self.assertEqual(status, 403)

    def test_api_admin_user_and_guest_forbidden(self) -> None:
        for headers in ({}, bearer(self.tok["USER"])):
            status, _h, _b = call(self.port, "GET", "/api/admin/apikeys", headers)
            self.assertEqual(status, 403, headers)
        status, _h, _b = call(self.port, "GET", "/api/admin/apikeys", bearer(self.tok["ADMIN"]))
        self.assertEqual(status, 200)

    def test_embedded_auto_token_not_ceo_for_admin_api(self) -> None:
        status, _h, body = call(self.port, "GET", "/chat")
        self.assertEqual(status, 200)
        m = re.search(rb'__LCA_SESSION_TOKEN="([^"]+)"', body)
        self.assertIsNotNone(m, "auto session token should be embedded in /chat")
        auto = m.group(1).decode()
        for hdrs in (bearer(auto), {"Authorization": f"Bearer {auto}"}, page_cookie(auto)):
            status, _h, _b = call(self.port, "GET", "/api/admin/apikeys", hdrs)
            self.assertIn(status, (401, 403), hdrs)
        status, _h, _b = call(self.port, "GET", "/api/admin/apikeys", bearer(self.tok["CEO"]))
        self.assertEqual(status, 200)

    # --- acceptance 3: loopback / proxy / tunnel ---
    def test_proxy_headers_forbidden_even_for_ceo(self) -> None:
        for name in ("X-Forwarded-For", "CF-Connecting-IP", "Forwarded"):
            hdrs = bearer(self.tok["CEO"])
            hdrs[name] = "127.0.0.1"
            status, _h, _b = call(self.port, "GET", "/api/admin/stats", hdrs)
            self.assertEqual(status, 403, name)

    def test_tunnel_active_forbidden(self) -> None:
        with mock.patch.object(cloud_tunnel, "is_active", return_value=True):
            status, _h, _b = call(self.port, "GET", "/api/admin/stats", bearer(self.tok["CEO"]))
        self.assertEqual(status, 403)

    def test_non_loopback_peer_forbidden(self) -> None:
        base = self.handler

        class Remote(base):  # type: ignore[misc, valid-type]
            def setup(self):
                super().setup()
                self.client_address = ("10.1.2.3", 5555)

        httpd = server.ExclusiveHTTPServer(("127.0.0.1", 0), Remote)
        import threading
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            port = httpd.server_address[1]
            status, _h, _b = call(port, "GET", "/api/admin/stats", bearer(self.tok["CEO"]))
            self.assertEqual(status, 403)
            status, _h, _b = call(port, "GET", "/chat")
            self.assertEqual(status, 403)
        finally:
            httpd.shutdown()
            httpd.server_close()

    # --- acceptance 4: Host / Origin / CSRF ---
    def test_bad_host_and_origin(self) -> None:
        status, _h, _b = call(self.port, "GET", "/api/admin/stats",
                              {**bearer(self.tok["CEO"]), "Host": "evil.example"})
        self.assertEqual(status, 403)
        status, _h, _b = call(self.port, "POST", "/api/admin/nodes",
                              {**bearer(self.tok["CEO"], csrf=True), "Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_post_without_csrf_forbidden(self) -> None:
        body = json.dumps({"action": "status"}).encode()
        status, _h, _b = call(self.port, "POST", "/api/admin/nodes", bearer(self.tok["CEO"]), body)
        self.assertEqual(status, 403)
        bad = {**bearer(self.tok["CEO"]), "X-LCA-CSRF": CSRF, "Cookie": "lca_csrf=" + "d" * 40}
        status, _h, _b = call(self.port, "POST", "/api/admin/nodes", bad, body)
        self.assertEqual(status, 403)

    # --- acceptance 8: nodes allowlist, no shell ---
    def test_nodes_allowlist(self) -> None:
        fake = {"ssh": True, "hostname": "n2"}
        with mock.patch.object(server, "_node_ctl_call", return_value=fake) as m:
            status, _h, body = call(self.port, "GET", "/api/admin/nodes", bearer(self.tok["CEO"]))
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["result"], fake)
            for action in ("status", "start", "stop", "restart", "logs"):
                status, _h, _b = call(self.port, "POST", "/api/admin/nodes",
                                      bearer(self.tok["CEO"], csrf=True),
                                      json.dumps({"action": action}).encode())
                self.assertEqual(status, 200, action)
            for action in ("deploy", "rollback", "rm -rf /", "", None, "pull-model"):
                status, _h, _b = call(self.port, "POST", "/api/admin/nodes",
                                      bearer(self.tok["CEO"], csrf=True),
                                      json.dumps({"action": action}).encode())
                self.assertEqual(status, 400, action)
        # real node_ctl validation (no ssh is started for an invalid host)
        status, _h, _b = call(self.port, "POST", "/api/admin/nodes",
                              bearer(self.tok["CEO"], csrf=True),
                              json.dumps({"action": "status", "host": "a;b"}).encode())
        self.assertEqual(status, 400)
        status, _h, _b = call(self.port, "GET", "/api/admin/nodes", bearer(self.tok["ADMIN"]))
        self.assertEqual(status, 403)

    def test_nodes_call_uses_no_shell(self) -> None:
        import ast
        for rel in ("server.py", "scripts/node_ctl.py"):
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "shell":
                    self.assertFalse(isinstance(node.value, ast.Constant) and node.value.value,
                                     rel)


class EntryPointTest(unittest.TestCase):
    # --- acceptance 5 ---
    def test_admin_build_server_loopback_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            httpd, port = lca_admin_app.build_server(tmp, preferred_port=0)
            try:
                self.assertEqual(httpd.server_address[0], "127.0.0.1")
                self.assertNotIn(port, (8420, 8422))
                self.assertEqual(httpd.lca_edition, "admin")
            finally:
                httpd.server_close()
        self.assertEqual(lca_admin_app.DEFAULT_PORT, 8430)
        with self.assertRaises(ValueError):
            lca_admin_app.build_server(".", preferred_port=0, host="0.0.0.0")

    def test_same_data_dir_as_customer(self) -> None:
        self.assertIs(lca_admin_app.data_dir, lca_app.data_dir)

    def test_admin_window_title_and_path(self) -> None:
        self.assertEqual(lca_admin_app.START_PATH, "/admin")
        self.assertEqual(lca_admin_app.WINDOW_TITLE, "LCA Admin")

    # --- acceptance 7 ---
    def test_customer_first_run_not_admin_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = lca_app.start_path(Path(tmp))
            self.assertFalse(edition.is_admin_route(path))
            self.assertEqual(path, "/models")
            httpd, _port = lca_app.build_server(tmp, preferred_port=0)
            try:
                self.assertEqual(httpd.lca_edition, "customer")
            finally:
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
