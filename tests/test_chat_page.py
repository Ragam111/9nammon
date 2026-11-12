"""Chat hub page budget: vanilla JS, local fonts, no CDN."""

from __future__ import annotations

import gzip
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ChatPageBudgetTest(unittest.TestCase):
    def test_own_js_is_under_60kb_gzip(self):
        raw = b"".join(
            (ROOT / "app" / name).read_bytes()
            for name in ("app.js", "chat.js")
        )
        size = len(gzip.compress(raw, compresslevel=9))
        self.assertLessEqual(size, 60 * 1024, f"own JS gzip {size} bytes")

    def test_thai_fonts_are_local_and_under_budget(self):
        fonts = ROOT / "app" / "fonts"
        regular = (fonts / "IBMPlexSansThai-Regular.sub.woff2").stat().st_size
        semibold = (fonts / "IBMPlexSansThai-SemiBold.sub.woff2").stat().st_size
        self.assertLessEqual(regular + semibold, 60 * 1024)
        self.assertTrue((fonts / "OFL.txt").is_file())
        self.assertIn("Open Font License", (fonts / "OFL.txt").read_text(encoding="utf-8"))
        html = (ROOT / "app" / "chat.html").read_text(encoding="utf-8")
        home = (ROOT / "app" / "home.html").read_text(encoding="utf-8")
        css = (ROOT / "app" / "app.css").read_text(encoding="utf-8")
        chat_css = (ROOT / "app" / "chat.css").read_text(encoding="utf-8")
        js = (ROOT / "app" / "chat.js").read_text(encoding="utf-8")
        app_js = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn('lang="th"', html)
        self.assertIn('lang="th"', home)
        self.assertIn("IBMPlexSansThai-Regular.sub.woff2", html)
        self.assertIn("IBMPlexSansThai-Regular.sub.woff2", home)
        blob = html + home + css + chat_css + js + app_js
        for banned in ("fonts.googleapis", "fonts.gstatic", "cdn.jsdelivr", "unpkg.com", "cdnjs."):
            self.assertNotIn(banned, blob)
        self.assertIn('font-family: "LCA Sans"', css)
        self.assertIn("IBMPlexSansThai-SemiBold.sub.woff2", css)
        self.assertIn("IBMPlexMono-Regular.sub.woff2", css)
        self.assertIn("Leelawadee UI", css)
        self.assertIn("Tahoma", css)
        self.assertIn("font-display: swap", css)
        self.assertIn("letter-spacing: 0", css)
        self.assertIn("line-height: 1.75", chat_css)
        self.assertIn("letter-spacing: 0", chat_css)
        self.assertNotIn("break-all", css + chat_css)
        self.assertNotIn("keep-all", css + chat_css)
        self.assertNotIn("react", js.lower())
        self.assertNotIn("vue", js.lower())
        self.assertIn("/api/version", app_js)
        self.assertIn("server OK", app_js)
        self.assertIn("offline", app_js)
        self.assertIn('id="lca-status"', html)
        self.assertIn('id="lca-status"', home)
        self.assertIn('href="/chat"', home)


if __name__ == "__main__":
    unittest.main()
