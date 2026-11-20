"""Apply pending SQLite migrations to existing LCA databases (run by update.ps1).

    python scripts/migrate.py                 # default data roots (below)
    python scripts/migrate.py <root> [<root>] # explicit project/data roots

A root's database is ``<root>/data/lca.db`` (``app.db.db_path``). Default roots:

- ``%LOCALAPPDATA%\\LocalCodeAssistant\\data`` — LCA Desktop (``lca_app.data_dir``)
- ``%USERPROFILE%`` — ``start-lca.bat`` / ``lca-desktop.bat`` serve that folder

Only databases that already exist are touched: an update never creates one.
Each migration that changes data takes its own backup first (see
``app/migrations/0010_chat_hub.py``). Exit code 1 if any database failed.
Stdlib only.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def default_roots() -> list[Path]:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    roots = [Path(base) / "LocalCodeAssistant" / "data", Path.home()]
    out: list[Path] = []
    for root in roots:
        if root not in out:
            out.append(root)
    return out


def _user_version(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def migrate_roots(roots) -> tuple[list[str], int]:
    from app import db

    lines: list[str] = []
    failures = 0
    target = db.code_version()
    for root in roots:
        path = db.db_path(root)
        if not path.exists():
            lines.append(f"[migrate] skip {path} (no database yet)")
            continue
        try:
            before = _user_version(path)
            if before >= target:
                lines.append(f"[migrate] ok   {path} (schema {before}, up to date)")
                continue
            db.ensure_migrated(root)
            after = _user_version(path)
            lines.append(f"[migrate] done {path} (schema {before} -> {after})")
        except Exception as exc:  # report every root, then fail
            failures += 1
            lines.append(f"[migrate] FAIL {path}: {type(exc).__name__}: {exc}")
    return lines, failures


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    roots = [Path(a) for a in args] if args else default_roots()
    lines, failures = migrate_roots(roots)
    for line in lines:
        print(line)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
