"""Shared shell (LCA_UI_SPEC task 4): nav + status chip on every app.js page.

Pages in STATIC_ROUTES that do not load app.js (console, dev, install, rea,
db-admin, offline) are out of scope: they keep their own auth/layout scripts.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
NAV = ["/chat", "/models", "/console/keys", "/plans", "/spaces", "/support"]


def static_html_pages() -> list:
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    block = src[src.index("STATIC_ROUTES = {"):]
    block = block[:block.index("\n}")]
    return sorted(set(re.findall(r'\("([\w\-]+\.html)"', block)))


def loads_app_js(html: str) -> bool:
    return re.search(r'<script[^>]+src="/app\.js"', html) is not None


def primary_count(html: str) -> int:
    body = re.sub(r"<dialog.*?</dialog>", "", html, flags=re.S)  # a modal is its own view
    body = re.sub(r"<(style|script)\b.*?</\1>", "", body, flags=re.S)
    return len(re.findall(r'class="[^"]*\b(?:primary|btn-primary)\b[^"]*"', body))


class StaticShell(unittest.TestCase):
    def setUp(self) -> None:
        self.pages = {n: (APP / n).read_text(encoding="utf-8") for n in static_html_pages()}
        self.shell_pages = {n: h for n, h in self.pages.items() if loads_app_js(h)}

    def test_found_pages(self) -> None:
        for n in ("models.html", "chat.html", "index.html", "plans.html"):
            self.assertIn(n, self.shell_pages)

    def test_mount_point(self) -> None:
        for name, html in self.shell_pages.items():
            if name == "chat.html":
                self.assertIn('id="lca-status-chip"', html)
                self.assertNotIn('id="lca-shell"', html, "chat keeps its own sidebar")
            else:
                self.assertIn('<div id="lca-shell"></div>', html, name)

    def test_render_shell_targets(self) -> None:
        js = (APP / "app.js").read_text(encoding="utf-8")
        for href in NAV + ["/admin/db"]:
            self.assertIn('href: "%s"' % href, js)
        self.assertNotIn("innerHTML", js)

    def test_one_primary_per_page(self) -> None:
        for name, html in self.shell_pages.items():
            self.assertLessEqual(primary_count(html), 1, name)

    def test_poll_interval_30s(self) -> None:
        js = (APP / "app.js").read_text(encoding="utf-8")
        self.assertIn("SHELL_POLL_MS = 30000", js)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class NodeShell(unittest.TestCase):
    def run_role(self, role: str) -> dict:
        out = subprocess.run(["node", str(ROOT / "tests" / "js" / "ui_shell_admin.js"), role],
                             capture_output=True, text=True, timeout=30, check=True)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_ceo_sees_admin(self) -> None:
        r = self.run_role("CEO")
        self.assertEqual(r["links"], NAV + ["/admin/db"])
        self.assertIn("Ollama up", r["chip"])
        self.assertIn("5/100", r["chip"])

    def test_user_no_admin(self) -> None:
        r = self.run_role("USER")
        self.assertEqual(r["links"], NAV)
        self.assertEqual(r["interval"], 30000)

    def test_menu_esc_and_read_only_calls(self) -> None:
        r = self.run_role("USER")
        self.assertEqual((r["opened"], r["closed"]), ("true", "false"))
        self.assertTrue(all(c["method"] == "GET" for c in r["calls"]))
        self.assertEqual({c["url"] for c in r["calls"]}, {"/api/health", "/api/me"})


class MeIsReadOnly(unittest.TestCase):
    def test_me_does_not_reserve(self) -> None:
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        body = src[src.index("def _handle_me(self)"):src.index("def _handle_auth_login")]
        self.assertIn("org_store.token_usage(", body)
        self.assertNotRegex(body, r"reserve_tokens|_reserve|consume|record_usage|commit_tokens")
        store = (APP / "org_store.py").read_text(encoding="utf-8")
        fn = store[store.index("def token_usage("):]
        fn = re.split(r"\n(?=\S)", fn)[0]
        self.assertIn("SELECT", fn)
        self.assertNotRegex(fn, r"UPDATE|INSERT|DELETE|_write\(")


if __name__ == "__main__":
    unittest.main()
