"""SQLite helper: WAL, NORMAL sync, busy_timeout, and a dry-run temp cleanup.

Cleanup deletes only temp names this package registered
(``*.db.tmp`` and ``*.db-journal``). The live database is kept.
``local_dashboard/web`` is refused because that folder is served as static files.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from lca_core.constants import BUSY_TIMEOUT_MS

MANIFEST = ".lca_core_owned.json"
SAFE_TEMP_SUFFIXES = (".db.tmp", ".db-journal")

__all__ = [
    "SAFE_TEMP_SUFFIXES",
    "checkpoint_and_close",
    "cleanup_stale",
    "connect",
    "reclaim_wal",
    "register",
    "session",
]


def _refuse_static_web(path: Path) -> None:
    parts = [part.lower() for part in Path(path).parts]
    for index, part in enumerate(parts):
        if part == "local_dashboard" and index + 1 < len(parts) and parts[index + 1] == "web":
            raise ValueError("refuse database files under local_dashboard/web")


def _manifest_path(directory: Path) -> Path:
    return Path(directory) / MANIFEST


def _load(directory: Path) -> dict:
    path = _manifest_path(directory)
    if not path.exists():
        return {"files": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"files": []}
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list):
        return {"files": []}
    return {"files": [name for name in files if isinstance(name, str)]}


def _save(directory: Path, data: dict) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = _manifest_path(directory)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def register(path: Path) -> Path:
    """Remember a file this package created. Names must be a single path segment."""
    path = Path(path)
    _refuse_static_web(path)
    name = path.name
    if not name or name != Path(name).name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError("refusing a non-local file name")
    if name == MANIFEST:
        raise ValueError("refusing to register the manifest")
    directory = path.parent
    data = _load(directory)
    if name not in data["files"]:
        data["files"].append(name)
        _save(directory, data)
    return path


def connect(path: Path, *, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    path = Path(path)
    _refuse_static_web(path)
    register(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_s = max(0.0, float(busy_timeout_ms) / 1000.0)
    conn = sqlite3.connect(str(path), timeout=timeout_s)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)};")
    return conn


def checkpoint_and_close(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    finally:
        conn.close()


def cleanup_stale(directory: Path, *, dry_run: bool = True) -> dict:
    """Remove registered ``*.db.tmp`` and ``*.db-journal`` files.

    ``dry_run`` defaults to True and does not unlink anything.
    Files absent from the manifest are left in place, including other ``*.db.tmp``.
    """
    directory = Path(directory)
    _refuse_static_web(directory)
    data = _load(directory)
    matched: list[str] = []
    removed: list[str] = []
    skipped: list[str] = []
    for name in data["files"]:
        if not name.endswith(SAFE_TEMP_SUFFIXES):
            skipped.append(name)
            continue
        path = directory / name
        if path.name != name or path.parent.resolve() != directory.resolve():
            skipped.append(name)
            continue
        try:
            if path.is_symlink() or not path.is_file():
                if path.exists():
                    skipped.append(name)
                continue
        except OSError:
            skipped.append(name)
            continue
        matched.append(name)
        if dry_run:
            continue
        path.unlink()
        removed.append(name)
    return {
        "dry_run": dry_run,
        "matched": matched,
        "removed": removed,
        "skipped": skipped,
    }


def reclaim_wal(db_path: Path, *, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> str:
    """Checkpoint WAL/SHM for a database this package registered.

    Returns ``skipped`` when the database is not ours, ``clean`` when no WAL
    is present, ``checkpointed`` after a truncate checkpoint, or ``busy``.
    """
    db_path = Path(db_path)
    _refuse_static_web(db_path)
    if db_path.name not in _load(db_path.parent)["files"]:
        return "skipped"
    wal = Path(str(db_path) + "-wal")
    shm = Path(str(db_path) + "-shm")
    if not wal.exists() and not shm.exists():
        return "clean"
    try:
        conn = sqlite3.connect(str(db_path), timeout=max(0.0, busy_timeout_ms / 1000.0))
        try:
            conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)};")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return "busy"
    return "checkpointed"


def register_temp_siblings(db_path: Path) -> None:
    text = str(db_path)
    register(Path(text + ".tmp"))
    register(Path(text + "-journal"))


@contextmanager
def session(path: Path, *, busy_timeout_ms: int = BUSY_TIMEOUT_MS):
    """Open, yield, checkpoint, and delete only the temp siblings we registered."""
    path = Path(path)
    register_temp_siblings(path)
    conn = connect(path, busy_timeout_ms=busy_timeout_ms)
    try:
        yield conn
    finally:
        checkpoint_and_close(conn)
        cleanup_stale(path.parent, dry_run=False)
