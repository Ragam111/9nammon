"""Chat hub page budget: vanilla JS, local fonts, no CDN."""

from __future__ import annotations

import gzip
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ChatPageBudgetTest(unittest.TestCase):
    def test_own_js_is_under_60kb_gzip(self):
        raw = (ROOT / "app" / "chat.js").read_bytes()
        size = len(gzip.compress(raw, compresslevel=9))
        self.assertLessEqual(size, 60 * 1024, f"chat.js gzip {size} bytes")

    def test_thai_fonts_are_local_and_under_budget(self):
        fonts = ROOT / "app" / "fonts"
        regular = (fonts / "IBMPlexSansThai-Regular.sub.woff2").stat().st_size
        semibold = (fonts / "IBMPlexSansThai-SemiBold.sub.woff2").stat().st_size
        self.assertLessEqual(regular + semibold, 60 * 1024)
        self.assertTrue((fonts / "OFL.txt").is_file())
        self.assertIn("Open Font License", (fonts / "OFL.txt").read_text(encoding="utf-8"))
        html = (ROOT / "app" / "chat.html").read_text(encoding="utf-8")
        css = (ROOT / "app" / "chat.css").read_text(encoding="utf-8")
        js = (ROOT / "app" / "chat.js").read_text(encoding="utf-8")
        self.assertIn('lang="th"', html)
        self.assertIn("IBMPlexSansThai-Regular.sub.woff2", html)
        blob = html + css + js
        for banned in ("fonts.googleapis", "fonts.gstatic", "cdn.jsdelivr", "unpkg.com", "cdnjs."):
            self.assertNotIn(banned, blob)
        self.assertIn('font-family: "LCA Sans"', css)
        self.assertIn("font-display: swap", css)
        self.assertIn("letter-spacing: 0", css)
        self.assertNotIn("break-all", css)
        self.assertNotIn("keep-all", css)
        self.assertNotIn("react", js.lower())
        self.assertNotIn("vue", js.lower())


class ChatPageExtraTest(unittest.TestCase):
    def test_chat_html_exists(self):
        self.assertTrue((ROOT / "app" / "chat.html").is_file())

    def test_app_js_exists(self):
        self.assertTrue((ROOT / "app" / "app.js").is_file())

    def test_chat_css_exists(self):
        self.assertTrue((ROOT / "app" / "chat.css").is_file())

    def test_chat_html_loads_app_js_before_chat_js(self):
        html = (ROOT / "app" / "chat.html").read_text(encoding="utf-8")
        pos_app = html.find('src="/app.js"')
        pos_chat = html.find('src="/chat.js"')
        self.assertGreater(pos_app, -1)
        self.assertGreater(pos_chat, -1)
        self.assertLess(pos_app, pos_chat)

    def test_chat_html_has_viewport_meta(self):
        html = (ROOT / "app" / "chat.html").read_text(encoding="utf-8")
        self.assertIn("viewport", html)

    def test_chat_js_is_valid_utf8(self):
        raw = (ROOT / "app" / "chat.js").read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            self.fail("chat.js ไม่ใช่ UTF-8")

    def test_app_js_is_valid_utf8(self):
        raw = (ROOT / "app" / "app.js").read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            self.fail("app.js ไม่ใช่ UTF-8")


if __name__ == "__main__":
    unittest.main()
