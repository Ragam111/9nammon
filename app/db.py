"""SQLite connection and migration runner for LCA Chat Hub.

One database per project: ``data/lca.db``. ``PRAGMA user_version`` is the
authoritative schema version. Files in ``app/migrations`` named ``NNNN_*.sql``
are applied in numeric order. A sibling ``NNNN_*.py`` with ``apply(conn, project_root, sql_path)``
may wrap that SQL (backup, seed, checksum).

Checked when this module was added: the repo had no ``app/migrations`` files
(no 0001–0009). The chat hub migration is ``0010_chat_hub``, the number the
data spec reserved, and it was still free. A fresh database therefore moves
from user_version 0 to 10 in one step.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import threading
from pathlib import Path

from app.chat_search import seg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DB_RELATIVE = Path("data") / "lca.db"

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class MigrationError(RuntimeError):
    """The database cannot be migrated safely."""


def db_path(project_root) -> Path:
    return Path(project_root) / DB_RELATIVE


def write_lock(project_root) -> threading.Lock:
    key = str(Path(project_root).resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def connect_raw(path) -> sqlite3.Connection:
    """Open one connection and apply the per-connection PRAGMAs.

    A brand-new file gets ``page_size=4096`` and ``auto_vacuum=INCREMENTAL``
    before any table is created.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists() or path.stat().st_size == 0
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    if fresh:
        conn.execute("PRAGMA page_size=4096")
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-8000")
    conn.execute("PRAGMA mmap_size=67108864")
    conn.execute("PRAGMA journal_size_limit=16777216")
    try:
        conn.create_function("lca_seg", 1, seg, deterministic=True)
    except TypeError:  # pragma: no cover - very old sqlite bindings
        conn.create_function("lca_seg", 1, seg)
    return conn


def list_migrations() -> list[tuple[int, str, Path, Path | None]]:
    """``(number, name, sql_path, py_path or None)`` sorted by number."""
    if not MIGRATIONS_DIR.is_dir():
        return []
    found = []
    for sql_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        number = int(sql_path.name.split("_", 1)[0])
        py_path = sql_path.with_suffix(".py")
        found.append((number, sql_path.stem, sql_path, py_path if py_path.exists() else None))
    found.sort(key=lambda item: item[0])
    return found


def code_version() -> int:
    migs = list_migrations()
    return migs[-1][0] if migs else 0


def _load_py(py_path: Path):
    spec = importlib.util.spec_from_file_location(f"lca_{py_path.stem}", py_path)
    if spec is None or spec.loader is None:
        raise MigrationError(f"โหลด migration ไม่ได้: {py_path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def split_sql(sql: str) -> list[str]:
    """Split a script on semicolons that are not inside strings or line comments."""
    statements = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    in_str = False
    while i < n:
        ch = sql[i]
        if in_str:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append(sql[i + 1])
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _migrate_unlocked(project_root) -> None:
    path = db_path(project_root)
    conn = connect_raw(path)
    try:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        migrations = list_migrations()
        newest = migrations[-1][0] if migrations else 0
        if current > newest:
            raise MigrationError(
                f"ฐานข้อมูลเป็นเวอร์ชัน {current} ซึ่งใหม่กว่าโค้ด ({newest}) — ไม่ downgrade"
            )
        for number, _name, sql_path, py_path in migrations:
            if current >= number:
                continue
            if py_path is None:
                raise MigrationError(f"ไม่มีตัวรันสำหรับ {sql_path.name}")
            module = _load_py(py_path)
            module.apply(conn, Path(project_root), sql_path)
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current < number:
                raise MigrationError(f"{sql_path.name} ไม่ได้ตั้ง user_version เป็น {number}")
    finally:
        try:
            conn.execute("PRAGMA optimize")
        except sqlite3.Error:
            pass
        conn.close()


def ensure_migrated(project_root) -> None:
    """Apply pending migrations. Safe to call on every request."""
    with write_lock(project_root):
        _migrate_unlocked(project_root)


class _ConnCtx:
    def __init__(self, project_root, write: bool):
        self.project_root = project_root
        self.write = write
        self.conn = None
        self._lock = None

    def __enter__(self) -> sqlite3.Connection:
        if self.write:
            self._lock = write_lock(self.project_root)
            self._lock.acquire()
            try:
                _migrate_unlocked(self.project_root)
                self.conn = connect_raw(db_path(self.project_root))
                self.conn.execute("BEGIN IMMEDIATE")
            except Exception:
                if self.conn is not None:
                    self.conn.close()
                self._lock.release()
                raise
            return self.conn
        ensure_migrated(self.project_root)
        self.conn = connect_raw(db_path(self.project_root))
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.write and self.conn is not None:
                if exc_type is None:
                    self.conn.execute("COMMIT")
                else:
                    try:
                        self.conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
        finally:
            if self.conn is not None:
                try:
                    if self.write:
                        self.conn.execute("PRAGMA optimize")
                except sqlite3.Error:
                    pass
                self.conn.close()
            if self._lock is not None:
                self._lock.release()
        return False


def write_txn(project_root):
    """Writer transaction. One writer at a time for this project."""
    return _ConnCtx(project_root, True)


def read_txn(project_root):
    """Reader connection. WAL allows readers beside the writer."""
    return _ConnCtx(project_root, False)
