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


class ChatPageStructureTest(unittest.TestCase):
    def test_chat_html_exists(self):
        self.assertTrue((ROOT / "app" / "chat.html").is_file())

    def test_chat_js_exists(self):
        self.assertTrue((ROOT / "app" / "chat.js").is_file())

    def test_chat_css_exists(self):
        self.assertTrue((ROOT / "app" / "chat.css").is_file())

    def test_html_has_viewport_meta(self):
        html = (ROOT / "app" / "chat.html").read_text(encoding="utf-8")
        self.assertIn("viewport", html)

    def test_js_has_auth_ref(self):
        js = (ROOT / "app" / "chat.js").read_text(encoding="utf-8")
        # chat JS must send auth header
        self.assertIn("token", js.lower())

    def test_js_is_nonempty(self):
        content = (ROOT / "app" / "chat.js").read_bytes()
        self.assertGreater(len(content), 0)

    def test_css_has_root_vars_or_body(self):
        css = (ROOT / "app" / "chat.css").read_text(encoding="utf-8")
        self.assertTrue(":root" in css or "body" in css)

    def test_fonts_dir_has_woff2_files(self):
        fonts = ROOT / "app" / "fonts"
        woff2 = list(fonts.glob("*.woff2"))
        self.assertGreater(len(woff2), 0)


if __name__ == "__main__":
    unittest.main()
