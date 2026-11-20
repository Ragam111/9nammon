"""Read-only UX/UI checks for the LCA web pages. Stdlib only, no model call.

Checks every page under app/ and local_dashboard/web/index.html:
  error   - missing lang on <html>, missing viewport meta, inline script that fails `node --check`
  warning - form control with no accessible name, hardcoded hex color outside app.css

Usage:
  python scripts/ux_check.py          # text report, exit 1 if any error
  python scripts/ux_check.py --json   # all findings as JSON
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_PATTERNS = ("app/*.html", "local_dashboard/web/index.html")
TOKEN_FILE = "app/app.css"
FORM_TAGS = frozenset({"input", "select", "textarea"})
SKIPPED_INPUT_TYPES = frozenset({"hidden", "submit", "button", "reset", "image"})
# 3 or 6 digit hex only, not part of a longer word or id such as "#add-btn".
# Known limit: an id made only of hex letters and digits, such as "#bad", is still counted.
HEX_COLOR = re.compile(r"(?<![\w#-])#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})(?![\w-])")
NODE_TIMEOUT_SEC = 30
MAX_PRINTED_WARNINGS = 15


@dataclass
class Finding:
    """One problem found on one page."""

    level: str  # "error" or "warning"
    page: str
    line: int
    message: str


class PageScanner(HTMLParser):
    """Collects the facts the checks need from one HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_lang = False
        self.has_viewport = False
        self.scripts: list[tuple[int, str]] = []
        self.label_targets: set[str] = set()
        self.controls: list[tuple[int, dict[str, str], bool]] = []
        self._label_depth = 0
        self._script_line = 0
        self._script_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        line = self.getpos()[0]
        if tag == "html" and values.get("lang"):
            self.has_lang = True
        if tag == "meta" and values.get("name", "").lower() == "viewport":
            self.has_viewport = True
        if tag == "label":
            self._label_depth += 1
            if values.get("for"):
                self.label_targets.add(values["for"])
        input_type = values.get("type", "").lower()
        if tag in FORM_TAGS and input_type not in SKIPPED_INPUT_TYPES:
            self.controls.append((line, values, self._label_depth > 0))
        if tag == "script" and "src" not in values:
            self._script_line = line
            self._script_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_depth > 0:
            self._label_depth -= 1
        if tag == "script" and self._script_parts is not None:
            self.scripts.append((self._script_line, "".join(self._script_parts)))
            self._script_parts = None

    def handle_data(self, data: str) -> None:
        if self._script_parts is not None:
            self._script_parts.append(data)


def scan_text(text: str) -> PageScanner:
    """Parse one HTML document and return its scanner."""
    scanner = PageScanner()
    scanner.feed(text)
    scanner.close()
    return scanner


def has_accessible_name(values: dict[str, str], in_label: bool, label_targets: set[str]) -> bool:
    """True when a control is named by a wrapping or for= label, or by aria/title."""
    if in_label or values.get("aria-label") or values.get("aria-labelledby") or values.get("title"):
        return True
    control_id = values.get("id", "")
    return bool(control_id) and control_id in label_targets


def hex_findings(page: str, text: str) -> list[Finding]:
    """One warning per page that counts hardcoded hex colors, pointing at the first one."""
    lines = [text.count("\n", 0, match.start()) + 1 for match in HEX_COLOR.finditer(text)]
    if not lines:
        return []
    message = f"{len(lines)} hardcoded hex color(s); use --lca-* tokens from {TOKEN_FILE}"
    return [Finding("warning", page, lines[0], message)]


def page_findings(page: str, text: str, scanner: PageScanner) -> list[Finding]:
    """Structure, label and color findings for one page (no node call)."""
    findings: list[Finding] = []
    if not scanner.has_lang:
        findings.append(Finding("error", page, 1, "missing lang attribute on <html>"))
    if not scanner.has_viewport:
        findings.append(Finding("error", page, 1, "missing viewport meta tag"))
    for line, values, in_label in scanner.controls:
        if not has_accessible_name(values, in_label, scanner.label_targets):
            name = values.get("id") or values.get("name") or "(no id)"
            findings.append(Finding("warning", page, line, f"form control {name} has no label"))
    findings.extend(hex_findings(page, text))
    return findings


def first_error_line(stderr: str) -> str:
    """Pick the most useful line from node's syntax error output."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for line in lines:
        if line.startswith(("SyntaxError", "Error")):
            return line
    return lines[0] if lines else "syntax error"


def syntax_findings(page: str, scanner: PageScanner, node: str | None) -> list[Finding]:
    """Run `node --check` on every inline script block of one page."""
    if not scanner.scripts:
        return []
    if node is None:
        return [Finding("warning", page, 1, "node not found; inline scripts were not syntax-checked")]
    findings: list[Finding] = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, (line, code) in enumerate(scanner.scripts):
            block = Path(tmp) / f"block_{index}.js"
            block.write_text(code, encoding="utf-8")
            result = subprocess.run(
                [node, "--check", str(block)],
                capture_output=True, text=True, timeout=NODE_TIMEOUT_SEC, check=False,
            )
            if result.returncode != 0:
                message = f"inline script fails node --check: {first_error_line(result.stderr)}"
                findings.append(Finding("error", page, line, message))
    return findings


def scan_file(path: Path, node: str | None) -> list[Finding]:
    """All findings for one page file."""
    page = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    scanner = scan_text(text)
    return page_findings(page, text, scanner) + syntax_findings(page, scanner, node)


def collect_pages(root: Path) -> list[Path]:
    """Every page the checks cover, sorted for a stable report."""
    return sorted({path for pattern in PAGE_PATTERNS for path in root.glob(pattern)})


def format_report(findings: list[Finding], page_count: int) -> str:
    """Text report. Warnings first, errors next, summary last so a tail-only log keeps it."""
    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]
    lines = [f"warning {f.page}:{f.line}  {f.message}" for f in warnings[:MAX_PRINTED_WARNINGS]]
    if len(warnings) > MAX_PRINTED_WARNINGS:
        lines.append(f"... {len(warnings) - MAX_PRINTED_WARNINGS} more warnings (use --json)")
    lines.extend(f"ERROR   {f.page}:{f.line}  {f.message}" for f in errors)
    lines.append(f"UX check: {page_count} pages, {len(errors)} errors, {len(warnings)} warnings")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the checks on every page. Exit 1 only when there is at least one error."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print all findings as JSON")
    args = parser.parse_args(argv)
    node = shutil.which("node")
    pages = collect_pages(ROOT)
    findings = [finding for path in pages for finding in scan_file(path, node)]
    if args.json:
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    else:
        print(format_report(findings, len(pages)))
    return 1 if any(f.level == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
