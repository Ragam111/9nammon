"""stage_app.py — build the app/ data dir that pyinstaller bundles for one edition.

    python scripts/stage_app.py --edition customer --out build/app_customer --verify
    python scripts/stage_app.py --edition admin    --out build/app_admin
    python scripts/stage_app.py --check build/app_customer     # CI: fail if admin files leaked

customer: drops console*.html, console-keys.js, db-admin.html, dev.html, admin*.html/js
admin:    keeps every file
Both write app/EDITION ("EDITION=<edition>") which server reads at startup.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import edition  # noqa: E402

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def find_admin_files(stage_dir: Path) -> list[str]:
    """Relative paths of admin-only files found under stage_dir."""
    base = Path(stage_dir)
    return sorted(str(p.relative_to(base)) for p in base.rglob("*")
                  if p.is_file() and edition.is_admin_file(p.name))


def _check_out(src: Path, out: Path) -> None:
    """Refuse to wipe the source tree or anything that contains it."""
    s, o = src.resolve(), out.resolve()
    if o == s or s.is_relative_to(o) or o.is_relative_to(s):
        raise ValueError(f"--out ต้องอยู่นอก {s}: {o}")


def stage(src: Path, out: Path, ed: str) -> Path:
    """Copy src → out (fresh), strip admin files for customer, write EDITION."""
    if ed not in edition.EDITIONS:
        raise ValueError(f"edition ต้องเป็น {edition.EDITIONS}: {ed!r}")
    src, out = Path(src), Path(out)
    _check_out(src, out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out, ignore=_IGNORE)
    if ed == edition.CUSTOMER:
        for rel in find_admin_files(out):
            (out / rel).unlink()
    (out / edition.EDITION_FILE).write_text(f"EDITION={ed}\n", encoding="utf-8")
    return out


def check_customer(stage_dir: Path) -> int:
    """0 when no admin file is present (and EDITION=customer), else print and return 1."""
    leaked = find_admin_files(stage_dir)
    ed = edition.read_edition_file(stage_dir)
    for rel in leaked:
        print(f"[stage_app] admin file in customer bundle: {rel}", file=sys.stderr)
    if ed != edition.CUSTOMER:
        print(f"[stage_app] EDITION is {ed}, expected customer", file=sys.stderr)
    return 1 if leaked or ed != edition.CUSTOMER else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="stage app/ for one LCA edition")
    p.add_argument("--edition", choices=edition.EDITIONS)
    p.add_argument("--out", type=Path)
    p.add_argument("--src", type=Path, default=ROOT / "app")
    p.add_argument("--verify", action="store_true", help="after customer stage, check for leaks")
    p.add_argument("--check", type=Path, help="only verify an existing customer stage dir")
    args = p.parse_args(argv)
    if args.check:
        return check_customer(args.check)
    if not args.edition or not args.out:
        p.error("--edition and --out are required")
    try:
        out = stage(args.src, args.out, args.edition)
    except (ValueError, OSError) as e:
        print(f"[stage_app] {e}", file=sys.stderr)
        return 2
    print(f"[stage_app] {args.edition} -> {out}")
    if args.verify and args.edition == edition.CUSTOMER:
        return check_customer(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
