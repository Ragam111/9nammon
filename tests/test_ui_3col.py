"""Task 2 of docs/LCA_UI_SPEC.md: 3-column /chat layout on desktop.

Static checks only (no browser): ids kept, header <= 3 controls, "more" menu
holds compare/persona/export/import/temporary, nav links, grid CSS, panel
memory in localStorage with try/catch. Plus the node suite for the toggles.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

# Every id in app/chat.html before the 3-column change (b5d6a80).
PRE_CHANGE_IDS = (
    "new-chat", "search", "search-hits", "folder", "add-folder", "conv-list",
    "ephemeral", "net-dot", "title", "model", "custom-model", "compare-btn",
    "persona", "export-btn", "import-btn", "import-file", "offline", "notice",
    "thread", "attach-chips", "composer", "attach-btn", "attach-file", "input",
    "send", "compare-box", "compare-picks", "queue-note", "compare-go",
)
CONTROL_TAGS = {"button", "select", "input", "textarea", "a"}
VOID_TAGS = {"input", "meta", "link", "br", "img", "hr", "source", "wbr"}


class _Tree(HTMLParser):
    """Collect ids and, per element, its ancestor ids and tags."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.elements: list[tuple[str, dict[str, str | None], list[tuple[str, dict]]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        self.elements.append((tag, a, list(self.stack)))
        if tag not in VOID_TAGS:
            self.stack.append((tag, a))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def _parse(path: Path) -> _Tree:
    tree = _Tree()
    tree.feed(path.read_text(encoding="utf-8"))
    return tree


def _inside(ancestors: list[tuple[str, dict]], *, tag: str | None = None, id_: str | None = None) -> bool:
    return any((tag is None or t == tag) and (id_ is None or a.get("id") == id_) for t, a in ancestors)


class Ui3ColTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (APP / "chat.html").read_text(encoding="utf-8")
        cls.css = (APP / "chat.css").read_text(encoding="utf-8")
        cls.js = (APP / "chat.js").read_text(encoding="utf-8")
        cls.tree = _parse(APP / "chat.html")
        cls.ids = {a.get("id") for _, a, _ in cls.tree.elements if a.get("id")}

    def test_mobile_sidebar_cannot_widen_layout(self) -> None:
        m = re.search(r"@media \(max-width: 720px\) \{(.*?)\n\}", self.css, re.S)
        self.assertIsNotNone(m)
        block = m.group(1)
        self.assertRegex(block, r"\.sidebar \{[^}]*min-width:\s*0")
        sel = re.search(r"\.sidebar select \{([^}]*)\}", block)
        self.assertIsNotNone(sel)
        self.assertRegex(sel.group(1), r"(^|[;\s])width:\s*100%")
        self.assertRegex(sel.group(1), r"max-width:\s*100%")

    def test_pre_change_ids_still_exist(self) -> None:
        missing = [i for i in PRE_CHANGE_IDS if i not in self.ids]
        self.assertEqual(missing, [])

    def test_ids_used_by_chat_js_exist(self) -> None:
        used = set(re.findall(r'\$\("([\w-]+)"\)', self.js))
        used |= set(re.findall(r'getElementById\("([\w-]+)"\)', self.js))
        used |= set(re.findall(r'querySelector(?:All)?\("#([\w-]+)', self.js))
        created = set(re.findall(r'\.id = "([\w-]+)"', self.js))
        missing = sorted(used - created - self.ids)
        self.assertEqual(missing, [])
        self.assertTrue(used, "regex found no ids in chat.js")

    def test_ids_are_unique(self) -> None:
        all_ids = [a.get("id") for _, a, _ in self.tree.elements if a.get("id")]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_header_has_at_most_three_visible_controls(self) -> None:
        controls = [
            (tag, a.get("id")) for tag, a, anc in self.tree.elements
            if tag in CONTROL_TAGS and _inside(anc, tag="header")
            and not _inside(anc, id_="more-menu") and "hidden" not in a
            and "mobile-only" not in (a.get("class") or "").split()  # desktop view
        ]
        self.assertLessEqual(len(controls), 3, controls)
        ids = {i for _, i in controls}
        self.assertIn("model", ids)
        self.assertIn("more-btn", ids)
        # title is plain text, still in the header
        title = [anc for _, a, anc in self.tree.elements if a.get("id") == "title"][0]
        self.assertTrue(_inside(title, tag="header"))

    def test_more_menu_holds_secondary_actions(self) -> None:
        for want in ("compare-btn", "persona", "export-btn", "import-btn", "ephemeral"):
            anc = [anc for _, a, anc in self.tree.elements if a.get("id") == want][0]
            self.assertTrue(_inside(anc, id_="more-menu"), want)
        btn = [a for t, a, _ in self.tree.elements if a.get("id") == "more-btn"][0]
        self.assertEqual(btn.get("aria-expanded"), "false")
        self.assertEqual(btn.get("aria-controls"), "more-menu")
        self.assertEqual(btn.get("aria-haspopup"), "true")
        menu = [a for t, a, _ in self.tree.elements if a.get("id") == "more-menu"][0]
        self.assertIn("hidden", menu)
        self.assertIn("⋯", self.html)

    def test_sidebar_nav_links(self) -> None:
        hrefs = {a.get("href") for t, a, anc in self.tree.elements
                 if t == "a" and _inside(anc, tag="aside")}
        for want in ("/models", "/console/keys", "/plans", "/spaces", "/support"):
            self.assertIn(want, hrefs)

    def test_right_panel(self) -> None:
        for want in ("side-panel", "panel-toggle", "attachments", "panel-model"):
            self.assertIn(want, self.ids)
        btn = [a for t, a, _ in self.tree.elements if a.get("id") == "panel-toggle"][0]
        self.assertIn(btn.get("aria-expanded"), ("true", "false"))
        self.assertEqual(btn.get("aria-controls"), "side-panel")

    def test_grid_css(self) -> None:
        self.assertRegex(self.css, r"grid-template-columns:\s*260px\s+1fr\s+320px")
        self.assertIn("min-width: 1024px", self.css)
        self.assertIn("panel-collapsed", self.css)

    def test_panel_state_uses_guarded_localstorage(self) -> None:
        block = self.js.split("/* layout:start */")[1].split("/* layout:end */")[0]
        self.assertIn("localStorage", block)
        self.assertGreaterEqual(block.count("try {"), 2)

    def test_composer_autofocus_and_shortcuts_kept(self) -> None:
        ta = [a for t, a, _ in self.tree.elements if a.get("id") == "input"][0]
        self.assertIn("autofocus", ta)
        for key in ('=== "k"', '=== "n"', '=== "m"', '"ArrowUp"', '"Escape"', '"Enter"'):
            self.assertIn(key, self.js)

    def test_brand_only(self) -> None:
        blob = (self.html + self.css).lower()
        for banned in ("anthropic", "openai", "chatgpt", "claude"):
            self.assertNotIn(banned, blob)
        self.assertIn("IBMPlexSansThai", self.html)


class Ui3ColNodeSuiteTest(unittest.TestCase):
    def test_node_suite(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        proc = subprocess.run(
            [node, "--test", str(ROOT / "tests" / "ui_layout.test.mjs")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
