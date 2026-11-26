"""WP-A: customer edition hides every admin surface; app.edition helpers. Temp root only."""
import http.client
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from app import edition, session_store  # noqa: E402

ADMIN_GETS = ("/admin", "/admin/db", "/console", "/console/keys", "/dev",
              "/console-keys.js", "/admin.js", "/api/admin/apikeys", "/api/admin/nodes",
              "/api/admin/users", "/api/admin/stats")
ADMIN_POSTS = ("/api/admin/apikeys", "/api/admin/nodes", "/api/admin/apikeys/revoke")


def start(root: Path, ed: str, token=None):
    """Run a real handler on 127.0.0.1:0; return (httpd, port, handler_cls)."""
    session_store.configure(root)
    handler = server.make_handler(root, token, edition=ed)
    httpd = server.ExclusiveHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1], handler


def call(port: int, method: str, path: str, headers=None, body: bytes = b""):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = {"Host": f"127.0.0.1:{port}"}
    hdrs.update(headers or {})
    if method == "POST":
        hdrs.setdefault("Content-Type", "application/json")
        body = body or b"{}"
    conn.request(method, path, body=body if method == "POST" else None, headers=hdrs)
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return res.status, dict(res.getheaders()), data


class EditionHelpersTest(unittest.TestCase):
    def test_normalize_fail_closed(self) -> None:
        self.assertEqual(edition.normalize("admin"), "admin")
        self.assertEqual(edition.normalize("EDITION=admin"), "admin")
        for bad in (None, "", "ADMIN ", "root", "ungated", "dev"):
            self.assertIn(edition.normalize(bad), edition.EDITIONS)
        self.assertEqual(edition.normalize("ungated"), "customer")

    def test_read_edition_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(edition.read_edition_file(Path(tmp)), "customer")
            (Path(tmp) / "EDITION").write_text("EDITION=admin\n", encoding="utf-8")
            self.assertEqual(edition.read_edition_file(Path(tmp)), "admin")
            (Path(tmp) / "EDITION").write_text("garbage", encoding="utf-8")
            self.assertEqual(edition.read_edition_file(Path(tmp)), "customer")

    def test_admin_route_and_file(self) -> None:
        for p in ADMIN_GETS:
            self.assertTrue(edition.is_admin_route(p), p)
        for p in ("/", "/chat", "/models", "/plans", "/api/chat", "/api/me", "/administrator"):
            self.assertFalse(edition.is_admin_route(p), p)
        for f in ("console.html", "console-keys.html", "console-keys.js", "db-admin.html",
                  "dev.html", "admin.html", "admin.js"):
            self.assertTrue(edition.is_admin_file(f), f)
        for f in ("chat.html", "models.html", "app.js", "org_store.py"):
            self.assertFalse(edition.is_admin_file(f), f)

    def test_block_reason(self) -> None:
        self.assertIsNone(edition.admin_block_reason("127.0.0.1", {}, False))
        self.assertIsNone(edition.admin_block_reason("::1", {}, False))
        self.assertIsNotNone(edition.admin_block_reason("10.0.0.5", {}, False))
        self.assertIsNotNone(edition.admin_block_reason("garbage", {}, False))
        for h in edition.PROXY_HEADERS:
            self.assertIsNotNone(edition.admin_block_reason("127.0.0.1", {h: "1.2.3.4"}, False))
        self.assertIsNotNone(edition.admin_block_reason("127.0.0.1", {}, True))

    def test_csrf_ok(self) -> None:
        tok = "a" * 32
        self.assertTrue(edition.csrf_ok({"X-LCA-CSRF": tok, "Cookie": f"x=1; lca_csrf={tok}"}))
        self.assertFalse(edition.csrf_ok({"Cookie": f"lca_csrf={tok}"}))
        self.assertFalse(edition.csrf_ok({"X-LCA-CSRF": tok}))
        self.assertFalse(edition.csrf_ok({"X-LCA-CSRF": "b" * 32, "Cookie": f"lca_csrf={tok}"}))
        self.assertFalse(edition.csrf_ok({"X-LCA-CSRF": "short", "Cookie": "lca_csrf=short"}))


class CustomerEditionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.httpd, self.port, self.handler = start(self.root, "customer")
        self.auto = {"X-Auth-Token": self.handler.session_token}

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def test_admin_gets_are_404_even_with_auto_token(self) -> None:
        for path in ADMIN_GETS:
            status, _h, _b = call(self.port, "GET", path, self.auto)
            self.assertEqual(status, 404, path)

    def test_admin_posts_are_404(self) -> None:
        for path in ADMIN_POSTS:
            status, _h, _b = call(self.port, "POST", path, self.auto)
            self.assertEqual(status, 404, path)

    def test_customer_pages_still_served(self) -> None:
        for path in ("/chat", "/models", "/plans"):
            status, _h, _b = call(self.port, "GET", path)
            self.assertEqual(status, 200, path)

    def test_customer_nav_has_no_admin_links(self) -> None:
        for name in ("app.js", "chat.html", "index.html", "models.html", "plans.html"):
            text = (server.APP_DIR / name).read_text(encoding="utf-8")
            for href in ('"/admin', '"/console', '"/dev"', "'/admin", "'/console"):
                self.assertNotIn("href: " + href, text, name)
                self.assertNotIn("href=" + href, text, name)

    def test_make_handler_rejects_unknown_edition(self) -> None:
        with self.assertRaises(ValueError):
            server.make_handler(self.root, None, edition="root")


if __name__ == "__main__":
    unittest.main()
