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


if __name__ == "__main__":
    unittest.main()
