"""Read-only database admin for LCA owners (CEO only).

Every query runs on a fresh read-only connection (mode=ro + query_only).
Table/column names come only from a whitelist built from sqlite_master and
PRAGMA table_info; user input is never interpolated into SQL.
Sensitive columns are always redacted. No write/delete/raw-SQL in this version.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs

from app import db, db_manager, org_store

MAX_PAGE_SIZE = 100
MAX_PAGE = 1_000_000
MAX_EXPORT_ROWS = 50_000
MAX_SEARCH_LEN = 200
MASK = "••••"
# Whole-word match on column names: token/token_hash/*_token/*_hash/password/secret/salt/
# verifier/session id stay redacted; count columns such as tokens_in/tokens_out/tokens_est do not.
SENSITIVE_RE = re.compile(
    r"(^|_)(token|hash|password|passwd|secret|salt|verifier)(_|$)|^sid$|(^|_)session(_id)?$",
    re.I)
CSV_DANGER = ("=", "+", "-", "@", "\t", "\r")
GET_PATHS = frozenset({"/api/admin/db/tables", "/api/admin/db/rows",
                       "/api/admin/db/summary", "/api/admin/db/export"})
POST_PATHS = frozenset({"/api/admin/db/check"})


class DbAdminError(ValueError):
    """Bad request (unknown table/column, bad page)."""


def connect_ro(project_root) -> sqlite3.Connection:
    """New read-only connection; writes raise sqlite3.OperationalError."""
    path = Path(db.ensure_ready(project_root)).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _q(name: str) -> str:
    """Quote a whitelisted identifier (only called on names from sqlite_master)."""
    return '"' + name.replace('"', '""') + '"'


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    out = []
    for r in rows:
        try:  # FTS shadow/virtual tables may be unreadable; skip them
            conn.execute(f"SELECT 1 FROM {_q(r[0])} LIMIT 0")
            out.append(r[0])
        except sqlite3.Error:
            continue
    return out


def _columns(conn: sqlite3.Connection, table: str) -> list[dict]:
    return [{"name": r[1], "type": r[2] or "", "pk": bool(r[5])}
            for r in conn.execute(f"PRAGMA table_info({_q(table)})")]


def is_sensitive(column: str) -> bool:
    return bool(SENSITIVE_RE.search(column))


def redact(column: str, value: Any) -> Any:
    """Mask sensitive columns: '••••' + original length."""
    if value is None or not is_sensitive(column):
        return value
    return f"{MASK}{len(str(value))}"


def _resolve_table(conn: sqlite3.Connection, table: Optional[str]) -> str:
    if not table or table not in _tables(conn):
        raise DbAdminError("unknown table")
    return table


def list_tables(project_root) -> dict:
    """Tables with row counts + schema version."""
    with closing(connect_ro(project_root)) as conn:
        out = []
        for t in _tables(conn):
            n = conn.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone()[0]
            cols = _columns(conn, t)
            out.append({"name": t, "rows": n, "columns": [c["name"] for c in cols],
                        "redacted": [c["name"] for c in cols if is_sensitive(c["name"])]})
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
    return {"schema_version": ver, "tables": out}


def _order_clause(cols: list[dict], order_by: Optional[str]) -> str:
    if not order_by:
        return ""
    desc = order_by.startswith("-")
    name = order_by[1:] if desc else order_by
    if name not in {c["name"] for c in cols}:
        raise DbAdminError("unknown column")
    if is_sensitive(name):
        raise DbAdminError("cannot order by a sensitive column")
    return f" ORDER BY {_q(name)} {'DESC' if desc else 'ASC'}"


def _where_clause(cols: list[dict], search: Optional[str]) -> tuple[str, list]:
    if not search:
        return "", []
    text = [c["name"] for c in cols
            if not is_sensitive(c["name"]) and not c["type"].upper().startswith(("INT", "REAL", "BLOB"))]
    if not text:
        return " WHERE 0", []
    like = "%" + search[:MAX_SEARCH_LEN].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    sql = " WHERE " + " OR ".join(f"{_q(c)} LIKE ? ESCAPE '\\'" for c in text)
    return sql, [like] * len(text)


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(str(value))
    except (TypeError, ValueError):
        raise DbAdminError("bad number") from None
    if n < lo or n > hi:
        raise DbAdminError("number out of range")
    return n if value is not None else default


def _redact_row(names: list[str], row: sqlite3.Row) -> list:
    return [redact(n, v if not isinstance(v, bytes) else f"<blob {len(v)}B>")
            for n, v in zip(names, row)]


def browse(project_root, table: str, page: Any = 1, page_size: Any = 50,
           search: Optional[str] = None, order_by: Optional[str] = None) -> dict:
    """One page of a table, redacted. page is 1-based."""
    p = _int(1 if page in (None, "") else page, 1, 1, MAX_PAGE)
    size = _int(50 if page_size in (None, "") else page_size, 50, 1, MAX_PAGE_SIZE)
    with closing(connect_ro(project_root)) as conn:
        t = _resolve_table(conn, table)
        cols = _columns(conn, t)
        where, params = _where_clause(cols, search)
        order = _order_clause(cols, order_by)
        total = conn.execute(f"SELECT COUNT(*) FROM {_q(t)}{where}", params).fetchone()[0]
        names = [c["name"] for c in cols]
        sel = ", ".join(_q(n) for n in names)
        rows = conn.execute(f"SELECT {sel} FROM {_q(t)}{where}{order} LIMIT ? OFFSET ?",
                            params + [size, (p - 1) * size]).fetchall()
    return {"table": t, "columns": cols, "page": p, "page_size": size, "total": total,
            "redacted": [n for n in names if is_sensitive(n)],
            "rows": [_redact_row(names, r) for r in rows]}


def csv_safe(value: Any) -> str:
    """Neutralise spreadsheet formula injection."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(CSV_DANGER) else s


def export_csv(project_root, table: str) -> str:
    """Whole table (capped) as redacted, injection-safe CSV."""
    with closing(connect_ro(project_root)) as conn:
        t = _resolve_table(conn, table)
        names = [c["name"] for c in _columns(conn, t)]
        sel = ", ".join(_q(n) for n in names)
        rows = conn.execute(f"SELECT {sel} FROM {_q(t)} LIMIT ?", (MAX_EXPORT_ROWS,))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([csv_safe(n) for n in names])
        for r in rows:
            w.writerow([csv_safe(v) for v in _redact_row(names, r)])
    return buf.getvalue()


def _group(conn: sqlite3.Connection, tables: list[str], table: str, col: str) -> dict:
    if table not in tables:
        return {}
    sql = f"SELECT {_q(col)}, COUNT(*) FROM {_q(table)} GROUP BY 1"
    return {str(k): n for k, n in conn.execute(sql)}


def _file_sizes(project_root) -> dict:
    path = Path(db.db_path(project_root))
    wal = path.with_name(path.name + "-wal")
    return {"db_bytes": path.stat().st_size if path.exists() else 0,
            "wal_bytes": wal.stat().st_size if wal.exists() else 0}


def summary(project_root) -> dict:
    """Health summary: users by role, keys by tier, orders by status, file sizes."""
    with closing(connect_ro(project_root)) as conn:
        ts = _tables(conn)
        out = {"users_by_role": _group(conn, ts, "org_users", "role"),
               "keys_by_tier": {}, "active_keys": 0,
               "orders_by_status": _group(conn, ts, "pay_orders", "status"),
               "schema_version": conn.execute("PRAGMA user_version").fetchone()[0]}
        if "org_api_keys" in ts:
            out["keys_by_tier"] = {str(k): n for k, n in conn.execute(
                "SELECT tier, COUNT(*) FROM org_api_keys WHERE active=1 GROUP BY 1")}
            out["active_keys"] = sum(out["keys_by_tier"].values())
    out.update(_file_sizes(project_root))
    return out


def quick_check(project_root) -> dict:
    with closing(connect_ro(project_root)) as conn:
        res = [r[0] for r in conn.execute("PRAGMA quick_check")]
    return {"ok": res == ["ok"], "result": res[:20]}


# ---------- HTTP glue (handler provides _require/_send_json) ----------

def wants_get(path: str) -> bool:
    return path in GET_PATHS


def wants_post(path: str) -> bool:
    return path in POST_PATHS


def _audit(project_root, ident: dict, action: str, detail: str = "") -> None:
    db_manager.log_event(project_root, "db_admin", f"{ident.get('username')} {action}",
                         source="db_admin", extra=detail[:200])


def _require_ceo(h, path: str, project_root) -> Optional[dict]:
    """h._require("CEO"), but a 401/403 is written to server_events before the reply."""
    try:
        who = h._identity()
        if who is None or not org_store.role_at_least(who.get("role"), "CEO"):
            status = 401 if who is None else 403
            user = (who or {}).get("username") or "-"
            db_manager.log_event(project_root, "db_admin_denied", f"{status} {user} {path}",
                                 level="warn", source="db_admin")
    except Exception:  # noqa: BLE001 - audit must not break the response
        pass
    return h._require("CEO")


def _send_csv(h, table: str, text: str) -> None:
    body = ("﻿" + text).encode("utf-8")
    h.send_response(200)
    h.send_header("Content-Type", "text/csv; charset=utf-8")
    h.send_header("Content-Disposition", f'attachment; filename="{table}.csv"')
    h.send_header("X-Content-Type-Options", "nosniff")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def _dispatch_get(h, path: str, qs: dict, project_root) -> None:
    one = lambda k: (qs.get(k) or [None])[0]  # noqa: E731
    if path == "/api/admin/db/tables":
        h._send_json(200, list_tables(project_root))
    elif path == "/api/admin/db/summary":
        h._send_json(200, summary(project_root))
    elif path == "/api/admin/db/rows":
        h._send_json(200, browse(project_root, one("table"), one("page"),
                                 one("page_size"), one("q"), one("order")))
    else:
        t = one("table")
        _send_csv(h, t, export_csv(project_root, t))


def handle_get(h, parsed, project_root) -> None:
    ident = _require_ceo(h, parsed.path, project_root)
    if ident is None:
        return
    qs = parse_qs(parsed.query)
    _audit(project_root, ident, parsed.path, parsed.query)
    try:
        _dispatch_get(h, parsed.path, qs, project_root)
    except DbAdminError as e:
        h._send_json(400, {"error": str(e)})
    except sqlite3.Error:
        h._send_json(500, {"error": "database error"})


def handle_post(h, parsed, project_root) -> None:
    ident = _require_ceo(h, parsed.path, project_root)
    if ident is None:
        return
    _audit(project_root, ident, parsed.path)
    try:
        h._send_json(200, quick_check(project_root))
    except sqlite3.Error:
        h._send_json(500, {"error": "database error"})
