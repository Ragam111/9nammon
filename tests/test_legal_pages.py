"""
test_legal_pages.py — public /terms, /privacy, /refund pages.

Real server on a random port, no auth header: pages must be 200, placeholders
filled from config (HTML-escaped), footer links present, no external resources.
"""

import http.client
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from app import config_manager  # noqa: E402

LEGAL = ("/terms", "/privacy", "/refund")
XSS = '<script>alert(1)</script>"Acme'


class LegalPagesTest(unittest.TestCase):
    config: dict = {}

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("BUSINESS_NAME", None)
        os.environ.pop("CONTACT_EMAIL", None)
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        if self.config:
            config_manager._config_path(root).write_text(json.dumps(self.config), encoding="utf-8")
        handler = server.make_handler(root, "legal-test-master-token")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()
        self._env.stop()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, body


class UnsetConfigTest(LegalPagesTest):
    def test_public_200_and_unset_marker(self):
        for path in LEGAL:
            status, body = self._get(path)
            self.assertEqual(status, 200, path)
            self.assertIn("[ยังไม่ได้ตั้งค่า]", body, path)
            self.assertNotIn("{{", body, path)

    def test_links_present(self):
        for path in LEGAL:
            _, body = self._get(path)
            for target in LEGAL:
                self.assertIn(f'href="{target}"', body, (path, target))

    def test_no_external_resources(self):
        for path in LEGAL:
            _, body = self._get(path)
            srcs = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', body)
            ext = [s for s in srcs if re.match(r"^(?:[a-z]+:)?//", s, re.I)]
            self.assertEqual(ext, [], path)
            self.assertNotRegex(body, r"@import|url\(\s*['\"]?https?:", path)

    def test_draft_note_hidden_by_default(self):
        for path in LEGAL:
            _, body = self._get(path)
            self.assertRegex(body, r'id="draft-note" hidden', path)


class XssConfigTest(LegalPagesTest):
    config = {"BUSINESS_NAME": XSS, "CONTACT_EMAIL": "owner@example.test"}

    def test_placeholders_escaped(self):
        for path in LEGAL:
            status, body = self._get(path)
            self.assertEqual(status, 200)
            self.assertNotIn("<script>alert(1)</script>", body, path)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;&quot;Acme", body, path)
            self.assertNotIn("[ยังไม่ได้ตั้งค่า]", body, path)


class FooterLinksTest(unittest.TestCase):
    def test_footer_on_main_pages(self):
        for name in ("index.html", "login.html", "plans.html"):
            src = (ROOT / "app" / name).read_text(encoding="utf-8")
            for target in LEGAL:
                self.assertIn(f'href="{target}"', src, (name, target))

    def test_shared_nav_has_legal_links(self):
        src = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        for target in LEGAL:
            self.assertIn(f'"{target}"', src)

    def test_routes_are_static_and_public(self):
        for path in LEGAL:
            self.assertIn(path, server.STATIC_ROUTES)
            self.assertNotIn(path, getattr(server, "PROTECTED_PAGES", {}))


class CloudDisclosureTest(unittest.TestCase):
    """Legal text must not claim local-only processing (chat_hub supports cloud providers)."""

    def _src(self, name):
        return (ROOT / "app" / name).read_text(encoding="utf-8")

    def test_privacy_discloses_cloud_providers(self):
        src = self._src("privacy.html")
        self.assertNotIn("ไม่ได้ส่งข้อความของคุณไปยังผู้ให้บริการ AI ภายนอก", src)
        self.assertIn("โดยค่าเริ่มต้น", src)
        sec2 = src.split("<h2>2.")[1].split("<h2>3.")[0]
        sec4 = src.split("<h2>4.")[1].split("<h2>5.")[0]
        for sec in (sec2, sec4):
            for vendor in ("Anthropic", "Gemini", "OpenAI", "host อื่น"):
                self.assertIn(vendor, sec)
        self.assertIn("ถูกส่งไปยังผู้ให้บริการ AI ภายนอก", sec2)

    def test_terms_discloses_cloud_providers(self):
        sec1 = self._src("terms.html").split("<h2>1.")[1].split("<h2>2.")[0]
        self.assertIn("โดยค่าเริ่มต้น", sec1)
        for vendor in ("Ollama", "Anthropic", "Gemini", "OpenAI", "ถูกส่งไปยังผู้ให้บริการ"):
            self.assertIn(vendor, sec1)

    def test_privacy_google_fields(self):
        sec1 = self._src("privacy.html").split("<h2>1.")[1].split("<h2>2.")[0]
        for field in ("sub", "อีเมล", "ชื่อ"):
            self.assertIn(field, sec1)


class RenderLegalUnitTest(unittest.TestCase):
    def test_lookup_error_falls_back(self):
        def boom(_k):
            raise RuntimeError("bad config")
        out = server.render_legal(b"{{BUSINESS_NAME}}|{{CONTACT_EMAIL}}", boom).decode()
        self.assertEqual(out, "[ยังไม่ได้ตั้งค่า]|[ยังไม่ได้ตั้งค่า]")


if __name__ == "__main__":
    unittest.main()
