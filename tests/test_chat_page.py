"""Chat hub page budget: vanilla JS, local fonts, no CDN.

Covers:
  ChatPageBudgetTest     — gzip budget, Thai fonts local, no CDN, OFL license
  ChatHtmlStructureTest  — DOCTYPE, charset, viewport, title, required element IDs
  ChatJsStructureTest    — IIFE wrapper, use strict, no eval, no document.write,
                           no framework references
  ChatCssStructureTest   — LCA Sans, font-display, no CDN, no word-break hacks
  ChatFilesExistTest     — font files, CSS, JS, HTML all present
"""

from __future__ import annotations

import gzip
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HTML = (ROOT / "app" / "chat.html").read_text(encoding="utf-8")
_CSS = (ROOT / "app" / "chat.css").read_text(encoding="utf-8")
_JS = (ROOT / "app" / "chat.js").read_text(encoding="utf-8")
_BLOB = _HTML + _CSS + _JS


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
        self.assertIn('lang="th"', _HTML)
        self.assertIn("IBMPlexSansThai-Regular.sub.woff2", _HTML)
        for banned in ("fonts.googleapis", "fonts.gstatic", "cdn.jsdelivr", "unpkg.com", "cdnjs."):
            self.assertNotIn(banned, _BLOB)
        self.assertIn('font-family: "LCA Sans"', _CSS)
        self.assertIn("font-display: swap", _CSS)
        self.assertIn("letter-spacing: 0", _CSS)
        self.assertNotIn("break-all", _CSS)
        self.assertNotIn("keep-all", _CSS)
        self.assertNotIn("react", _JS.lower())
        self.assertNotIn("vue", _JS.lower())

    def test_no_cdn_in_html(self):
        for banned in ("fonts.googleapis", "cdn.jsdelivr", "unpkg.com", "cdnjs."):
            self.assertNotIn(banned, _HTML, f"CDN reference found: {banned}")

    def test_no_cdn_in_css(self):
        for banned in ("fonts.googleapis", "cdn.jsdelivr", "unpkg.com", "cdnjs."):
            self.assertNotIn(banned, _CSS, f"CDN reference found: {banned}")

    def test_no_cdn_in_js(self):
        for banned in ("cdn.jsdelivr", "unpkg.com", "cdnjs."):
            self.assertNotIn(banned, _JS, f"CDN reference found: {banned}")


class ChatHtmlStructureTest(unittest.TestCase):
    def test_html_has_doctype(self):
        self.assertTrue(_HTML.lower().startswith("<!doctype html>"),
                        "chat.html ต้องขึ้นต้นด้วย <!DOCTYPE html>")

    def test_html_has_charset_meta(self):
        self.assertIn("charset", _HTML.lower())

    def test_html_has_viewport_meta(self):
        self.assertIn("viewport", _HTML)

    def test_html_title_exists(self):
        self.assertIn("<title>", _HTML)

    def test_html_lang_th(self):
        self.assertIn('lang="th"', _HTML)

    def test_html_links_chat_css(self):
        self.assertIn("chat.css", _HTML)

    def test_html_required_element_ids(self):
        for eid in ("new-chat", "search", "model"):
            self.assertIn(f'id="{eid}"', _HTML, f"missing element id: {eid}")

    def test_html_has_font_preload(self):
        self.assertIn("IBMPlexSansThai-Regular.sub.woff2", _HTML)


class ChatJsStructureTest(unittest.TestCase):
    def test_js_has_iife_wrapper(self):
        self.assertIn("(function", _JS, "chat.js ต้องใช้ IIFE wrapper")

    def test_js_has_use_strict(self):
        self.assertIn('"use strict"', _JS)

    def test_js_no_eval(self):
        import re
        self.assertIsNone(re.search(r'\beval\s*\(', _JS), "chat.js ต้องไม่ใช้ eval()")

    def test_js_no_document_write(self):
        self.assertNotIn("document.write(", _JS)

    def test_js_no_framework_imports(self):
        for fw in ("require(", "import React", "import Vue", "import {"):
            self.assertNotIn(fw, _JS, f"ไม่ควรมี framework import: {fw}")

    def test_js_has_esc_function(self):
        self.assertIn("function esc(", _JS, "ต้องมี XSS escape function")


class ChatCssStructureTest(unittest.TestCase):
    def test_css_has_lca_sans(self):
        self.assertIn("LCA Sans", _CSS)

    def test_css_has_font_display_swap(self):
        self.assertIn("font-display: swap", _CSS)

    def test_css_no_break_all(self):
        self.assertNotIn("break-all", _CSS)

    def test_css_no_keep_all(self):
        self.assertNotIn("keep-all", _CSS)


class ChatFilesExistTest(unittest.TestCase):
    def test_chat_html_exists(self):
        self.assertTrue((ROOT / "app" / "chat.html").is_file())

    def test_chat_js_exists(self):
        self.assertTrue((ROOT / "app" / "chat.js").is_file())

    def test_chat_css_exists(self):
        self.assertTrue((ROOT / "app" / "chat.css").is_file())

    def test_font_regular_exists(self):
        self.assertTrue((ROOT / "app" / "fonts" / "IBMPlexSansThai-Regular.sub.woff2").is_file())

    def test_font_semibold_exists(self):
        self.assertTrue((ROOT / "app" / "fonts" / "IBMPlexSansThai-SemiBold.sub.woff2").is_file())

    def test_ofl_license_exists(self):
        self.assertTrue((ROOT / "app" / "fonts" / "OFL.txt").is_file())


if __name__ == "__main__":
    unittest.main()
