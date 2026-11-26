"""edition.py — which build this process is: customer app or LCA-Admin.

The edition is baked in at build time (scripts/stage_app.py writes app/EDITION, or the
entry script passes it). It is never read from env or config. Unknown or missing
values fall back to CUSTOMER (fail-closed: admin surfaces disappear).

UNGATED is a programmatic-only mode for the legacy test suite and direct make_handler
callers; it can never come from the EDITION file or the --edition flag.
"""

from __future__ import annotations

import fnmatch
import hmac
import ipaddress
from pathlib import Path
from typing import Mapping, Optional

CUSTOMER = "customer"
ADMIN = "admin"
UNGATED = "ungated"
EDITIONS = (CUSTOMER, ADMIN)

EDITION_FILE = "EDITION"
CSRF_COOKIE = "lca_csrf"
CSRF_HEADER = "X-LCA-CSRF"

# pages and assets that exist only in LCA-Admin (customer answers 404)
ADMIN_PAGES = frozenset({"/admin", "/admin/db", "/console", "/console/keys", "/dev"})
ADMIN_ASSETS = frozenset({"/console-keys.js", "/admin.js"})
ADMIN_API_PREFIX = "/api/admin/"

# files that stage_app removes from the customer bundle
ADMIN_FILE_PATTERNS = ("console*.html", "console-keys.js", "db-admin.html", "dev.html",
                       "admin*.html", "admin*.js")

# proxy headers: their presence means the request did not come straight from this machine
PROXY_HEADERS = ("X-Forwarded-For", "CF-Connecting-IP", "Forwarded")


def normalize(value: object) -> str:
    """Return a known edition name; anything else becomes CUSTOMER."""
    v = str(value or "").strip().lower()
    if v.startswith("edition="):
        v = v.split("=", 1)[1].strip()
    return v if v in EDITIONS else CUSTOMER


def read_edition_file(app_dir: Path) -> str:
    """Edition written by stage_app into app/EDITION; missing/unreadable → CUSTOMER."""
    try:
        text = (Path(app_dir) / EDITION_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return CUSTOMER
    first = text.strip().splitlines()[0] if text.strip() else ""
    return normalize(first)


def is_admin_route(path: str) -> bool:
    """True for admin-only pages, assets and every /api/admin/* endpoint."""
    p = str(path or "")
    if p in ADMIN_PAGES or p in ADMIN_ASSETS:
        return True
    return p == "/api/admin" or p.startswith(ADMIN_API_PREFIX)


def is_admin_file(name: str) -> bool:
    """True if a bundled app/ file belongs only in LCA-Admin."""
    base = Path(str(name)).name
    return any(fnmatch.fnmatchcase(base, pat) for pat in ADMIN_FILE_PATTERNS)


def peer_is_loopback(peer: object) -> bool:
    """TCP peer only (never proxy headers): loopback address → True."""
    try:
        return ipaddress.ip_address(str(peer).strip()).is_loopback
    except ValueError:
        return False


def admin_block_reason(peer: object, headers: Mapping[str, str],
                       tunnel_active: bool) -> Optional[str]:
    """Why an admin-edition request must be refused (403), or None when allowed."""
    if not peer_is_loopback(peer):
        return "admin app รับเฉพาะเครื่องนี้ (loopback) เท่านั้น"
    for name in PROXY_HEADERS:
        if headers.get(name) is not None:
            return f"admin app ไม่รับ request ที่ผ่าน proxy ({name})"
    if tunnel_active:
        return "admin app ปิดรับขณะ Cloudflare tunnel เปิดอยู่"
    return None


def cookie_value(cookie_header: Optional[str], name: str) -> str:
    """Read one cookie value from a Cookie header ('' when absent)."""
    for part in str(cookie_header or "").split(";"):
        key, _sep, value = part.strip().partition("=")
        if key == name:
            return value.strip()
    return ""


def csrf_ok(headers: Mapping[str, str]) -> bool:
    """Double-submit check: X-LCA-CSRF header must equal the lca_csrf cookie."""
    sent = str(headers.get(CSRF_HEADER) or "").strip()
    cookie = cookie_value(headers.get("Cookie"), CSRF_COOKIE)
    if len(sent) < 16 or not cookie:
        return False
    return hmac.compare_digest(sent, cookie)
