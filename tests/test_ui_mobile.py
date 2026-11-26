"""Task 3 of docs/LCA_UI_SPEC.md: mobile drawer + bottom sheet (static checks)."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ui_3col import APP, CONTROL_TAGS, _inside, _parse  # noqa: E402

MOBILE_BLOCK = r"@media \(max-width: 1023\.98px\) \{(.*?)\n\}"


class UiMobileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = (APP / "chat.css").read_text(encoding="utf-8")
        cls.js = (APP / "chat.js").read_text(encoding="utf-8")
        cls.tree = _parse(APP / "chat.html")
        cls.by_id = {a.get("id"): (t, a, anc) for t, a, anc in cls.tree.elements if a.get("id")}
        m = re.search(MOBILE_BLOCK, cls.css, re.S)
        cls.block = m.group(1) if m else ""

    def _attrs(self, id_: str) -> dict:
        return self.by_id[id_][1]

    def test_drawer_button_aria(self) -> None:
        a = self._attrs("drawer-btn")
        self.assertEqual(a.get("aria-controls"), "sidebar")
        self.assertEqual(a.get("aria-expanded"), "false")
        self.assertIn("mobile-only", a.get("class", ""))
        self.assertTrue(_inside(self.by_id["drawer-btn"][2], tag="header"))
        self.assertEqual(self.by_id["sidebar"][0], "aside")

    def test_sheet_button_in_more_menu(self) -> None:
        a = self._attrs("sheet-btn")
        self.assertEqual(a.get("aria-controls"), "side-panel")
        self.assertEqual(a.get("aria-expanded"), "false")
        self.assertTrue(_inside(self.by_id["sheet-btn"][2], id_="more-menu"))

    def test_close_buttons_and_backdrop(self) -> None:
        self.assertTrue(_inside(self.by_id["drawer-close"][2], id_="sidebar"))
        self.assertTrue(_inside(self.by_id["sheet-close"][2], id_="side-panel"))
        self.assertIn("hidden", self._attrs("backdrop"))

    def _header_controls(self, skip: str) -> list:
        return [a.get("id") for t, a, anc in self.tree.elements
                if t in CONTROL_TAGS and _inside(anc, tag="header")
                and not _inside(anc, id_="more-menu") and "hidden" not in a
                and skip not in (a.get("class") or "").split()]

    def test_header_three_controls_desktop_and_mobile(self) -> None:
        desk = self._header_controls("mobile-only")
        mob = self._header_controls("desktop-only")
        self.assertLessEqual(len(desk), 3, desk)
        self.assertLessEqual(len(mob), 3, mob)
        self.assertIn("drawer-btn", mob)
        self.assertNotIn("panel-toggle", mob)
        self.assertIn("panel-toggle", desk)

    def test_mobile_css_drawer_sheet(self) -> None:
        b = self.block
        self.assertTrue(b, "missing @media (max-width: 1023.98px)")
        self.assertRegex(b, r"\.sidebar \{[^}]*position: fixed")
        self.assertRegex(b, r"\.sidebar \{[^}]*translateX\(-100%\)")
        self.assertRegex(b, r"\.panel \{[^}]*bottom: 0")
        self.assertIn(".backdrop", b)
        self.assertRegex(b, r"body\.overlay-open \{[^}]*overflow: hidden")
        self.assertRegex(b, r"\.desktop-only \{ display: none")

    def test_open_state_has_no_visibility_delay(self) -> None:
        for sel in (".sidebar.open", ".panel.open"):
            m = re.search(re.escape(sel) + r" \{([^}]*)\}", self.block)
            self.assertIsNotNone(m, sel)
            self.assertRegex(m.group(1), r"transition:[^;]*visibility 0s", sel)

    def test_open_focuses_after_visibility(self) -> None:
        self.assertIn('getComputedStyle(box).visibility === "visible"', self.js)
        self.assertIn("requestAnimationFrame", self.js)
        self.assertIn('"transitionend"', self.js)
        self.assertIn('ev.key === "Tab"', self.js)

    def test_no_horizontal_scroll_rules(self) -> None:
        self.assertIn("overflow-x: hidden", self.block)
        self.assertIn("minmax(0, 1fr)", self.block)
        self.assertIn("width: min(85vw, 320px)", self.block)

    def test_tap_targets_44px(self) -> None:
        self.assertGreaterEqual(self.block.count("min-height: 44px"), 3)
        self.assertIn("min-width: 44px", self.block)

    def test_keyboard_safe_height(self) -> None:
        self.assertIn("100dvh", self.css)
        self.assertIn("--lca-vvh", self.block)
        layout = self.js.split("/* layout:start */")[1].split("/* layout:end */")[0]
        self.assertIn("visualViewport", layout)
        self.assertIn("inert", layout)

    def test_two_tap_reach(self) -> None:
        # Drawer (1 tap) holds chat list/search/folders/nav; "⋯" (1 tap) holds the rest.
        for want in ("new-chat", "search", "folder", "conv-list"):
            self.assertTrue(_inside(self.by_id[want][2], id_="sidebar"), want)
        for want in ("compare-btn", "persona", "export-btn", "import-btn", "ephemeral", "sheet-btn"):
            self.assertTrue(_inside(self.by_id[want][2], id_="more-menu"), want)


if __name__ == "__main__":
    unittest.main()


class DrawerSpecificityTest(unittest.TestCase):
    """app.css uses #sidebar (ID) rules that beat .sidebar; the hub must override them."""

    @classmethod
    def setUpClass(cls) -> None:
        css = (APP / "chat.css").read_text(encoding="utf-8")
        m = re.search(MOBILE_BLOCK, css, re.S)
        cls.block = m.group(1) if m else ""
        cls.html = (APP / "chat.html").read_text(encoding="utf-8")
        cls.app_css = (APP / "app.css").read_text(encoding="utf-8")

    def _rule(self) -> str:
        m = re.search(r"body\.page-hub #sidebar\.sidebar \{(.*?)\}", self.block, re.S)
        self.assertIsNotNone(m, "mobile block must target #sidebar with ID specificity")
        return m.group(1)

    def test_hub_markup_matches_selector(self) -> None:
        self.assertRegex(self.html, r'<body[^>]*class="[^"]*page-hub')
        self.assertRegex(self.html, r'id="sidebar"[^>]*class="[^"]*sidebar|class="[^"]*sidebar[^"]*"[^>]*id="sidebar"')

    def test_overrides_app_css_720_rule(self) -> None:
        # app.css max-width:720px sets width:100%; max-height:45vh; border-top; order:2
        self.assertIn("max-height: 45vh", self.app_css)
        rule = self._rule()
        for decl in ("width: min(85vw, 320px)", "max-height: none", "height: auto",
                     "inset: 0 auto 0 0", "border-top: none", "order: initial"):
            self.assertIn(decl, rule)

    def test_welcome_chips_and_plans_link_44px(self) -> None:
        self.assertRegex(self.block, r"\.empty button, #panel-quota a \{[^}]*min-height: 44px")
