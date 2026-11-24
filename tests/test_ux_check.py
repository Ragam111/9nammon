"""test_ux_check.py - scripts/ux_check.py: lint rules on small pages, and the real pages."""

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ux_check  # noqa: E402

HEAD = '<!doctype html><html lang="th"><head><meta name="viewport" content="width=device-width"></head><body>'
TAIL = "</body></html>"


def run_rules(body: str, head: str = HEAD) -> list[ux_check.Finding]:
    """Findings for a small page built from head + body."""
    text = head + body + TAIL
    return ux_check.page_findings("t.html", text, ux_check.scan_text(text))


class PageRulesTest(unittest.TestCase):
    def test_clean_page_has_no_findings(self):
        body = '<label>ชื่อ<input id="a"></label><label for="b">รหัส</label><input id="b"><input aria-label="ค้นหา">'
        self.assertEqual(run_rules(body), [])

    def test_missing_lang_and_viewport_are_errors(self):
        findings = run_rules("<p>x</p>", head="<!doctype html><html><head></head><body>")
        errors = [f.message for f in findings if f.level == "error"]
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("lang" in m for m in errors))
        self.assertTrue(any("viewport" in m for m in errors))

    def test_unlabeled_input_is_warning(self):
        findings = run_rules('<input id="name">')
        self.assertEqual([(f.level, f.message) for f in findings],
                         [("warning", "form control name has no label")])

    def test_label_for_after_control_still_counts(self):
        self.assertEqual(run_rules('<input id="c"><label for="c">รหัส</label>'), [])

    def test_hidden_and_button_inputs_are_ignored(self):
        self.assertEqual(run_rules('<input type="hidden" id="h"><input type="button" value="x">'), [])

    def test_title_gives_a_name(self):
        self.assertEqual(run_rules('<input id="q" title="ค้นหา">'), [])

    def test_hex_colors_counted_but_ids_are_not(self):
        body = '<style>#add-btn{color:#1f8a4c}#main{color:#fff}</style>'
        findings = [f for f in run_rules(body) if "hex" in f.message]
        self.assertEqual(len(findings), 1)
        self.assertIn("2 hardcoded hex", findings[0].message)


class SyntaxRuleTest(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is not installed")
    def test_broken_inline_script_is_error(self):
        scanner = ux_check.scan_text("<script>let x = ;</script>")
        findings = ux_check.syntax_findings("p.html", scanner, shutil.which("node"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, "error")

    @unittest.skipIf(shutil.which("node") is None, "node is not installed")
    def test_valid_inline_script_passes(self):
        scanner = ux_check.scan_text("<script>const x = 1;</script>")
        self.assertEqual(ux_check.syntax_findings("p.html", scanner, shutil.which("node")), [])

    def test_external_script_is_not_checked(self):
        scanner = ux_check.scan_text('<script src="/app.js"></script>')
        self.assertEqual(scanner.scripts, [])


class RealPagesTest(unittest.TestCase):
    def test_pages_are_found(self):
        self.assertGreater(len(ux_check.collect_pages(ROOT)), 5)

    def test_real_pages_have_no_errors(self):
        node = shutil.which("node")
        errors = [
            f"{f.page}:{f.line} {f.message}"
            for path in ux_check.collect_pages(ROOT)
            for f in ux_check.scan_file(path, node)
            if f.level == "error"
        ]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
