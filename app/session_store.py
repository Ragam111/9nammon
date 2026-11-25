"""session_store.py — session token หลัง login ด้วย username/password (SQLite, stdlib)

ทำไมต้องมี: org_store มี user+password (PBKDF2) อยู่แล้ว แต่ไม่มีทางให้ "คน" ล็อกอิน —
มีแต่ master token กับ API key ที่ต้องวางเอง. โมดูลนี้แปลง login ที่ถูกต้องเป็น
session token อายุจำกัด ซึ่ง server รับผ่าน X-Auth-Token เหมือน token อื่น

ออกแบบ:
- server.main() เรียก configure(project_root) → เก็บใน ``data/lca.db`` ตาราง auth_sessions
  (migration 0012) ทำให้ session อยู่รอดหลังรีสตาร์ต. ยังไม่ configure (เช่นใน unit test)
  → ใช้ SQLite ``:memory:`` ต่อ process ด้วยโค้ดชุดเดียวกัน
- เก็บแค่ sha256(token) ไม่เคยเก็บ token ลงดิสก์ — db หลุดก็เอา token ไปใช้ไม่ได้
- token = ``lcs_`` + secrets.token_urlsafe(32)
- TTL เริ่มต้น 12 ชั่วโมง; verify() ปฏิเสธและลบ session หมดอายุให้เอง
- login limiter ต่อ IP (sliding window, in-memory) กัน brute-force รหัสผ่าน
- thread-safe (ThreadingHTTPServer); หลายโปรเซสใช้ db เดียวกันได้ (WAL)
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path

from app import db

SESSION_TTL_SECONDS = 12 * 60 * 60
TOKEN_PREFIX = "lcs_"
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 60.0

# same shape as auth_sessions in app/migrations/0012_org_auth.sql (memory mode only)
_MEM_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS auth_sessions ("
    " token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, role TEXT NOT NULL,"
    " tier TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL)"
)

_lock = threading.Lock()
_root: Path | None = None
_mem: sqlite3.Connection | None = None
_failures: dict[str, deque] = defaultdict(deque)


def configure(project_root: Path | str | None) -> None:
    """เลือกที่เก็บ: project_root → data/lca.db (คงทน), None → :memory: (ต่อ process)"""
    global _root
    root = Path(project_root) if project_root is not None else None
    if root is not None:
        db.ensure_ready(root)
    with _lock:
        _root = root


def storage() -> str:
    """'sqlite:<path>' หรือ 'memory' — ไว้ให้ /api/health หรือ test ตรวจ"""
    root = _root
    return f"sqlite:{db.db_path(root)}" if root is not None else "memory"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@contextmanager
def _conn():
    root = _root
    if root is None:
        global _mem
        with _lock:
            if _mem is None:
                _mem = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
                _mem.row_factory = sqlite3.Row
                _mem.execute(_MEM_SCHEMA)
            yield _mem
        return
    conn = db.connect_light(db.ensure_ready(root))
    try:
        yield conn
    finally:
        conn.close()


def create(username: str, role: str, tier: str = "paid", ttl: float = SESSION_TTL_SECONDS,
           now: float | None = None) -> dict:
    """ออก session ใหม่ — คืน dict ที่มี token เต็ม (โชว์ครั้งเดียวตอน login)"""
    now = time.time() if now is None else now
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    record = {
        "username": username,
        "role": role,
        "tier": tier,
        "key_id": None,
        "source": "session",
        "created_at": now,
        "expires_at": now + float(ttl),
    }
    with _conn() as c:
        c.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
        c.execute("INSERT INTO auth_sessions(token_hash, username, role, tier, created_at,"
                  " expires_at) VALUES (?,?,?,?,?,?)",
                  (_hash(token), username, role, tier, now, record["expires_at"]))
    return {"token": token, **record}


def verify(token: str | None, now: float | None = None) -> dict | None:
    """คืน identity dict ถ้า token เป็น session ที่ยังไม่หมดอายุ, ไม่งั้น None (db ล้ม = None)"""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    now = time.time() if now is None else now
    th = _hash(token)
    try:
        with _conn() as c:
            row = c.execute("SELECT username, role, tier, expires_at FROM auth_sessions"
                            " WHERE token_hash=?", (th,)).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= now:
                c.execute("DELETE FROM auth_sessions WHERE token_hash=? OR expires_at <= ?",
                          (th, now))
                return None
    except sqlite3.Error as e:
        print(f"[session][error] ตรวจ session ไม่ได้: {e}")
        return None
    return {
        "username": row["username"],
        "role": row["role"],
        "tier": row["tier"],
        "key_id": None,
        "source": "session",
        "expires_at": row["expires_at"],
    }


def revoke(token: str | None) -> bool:
    """ลบ session — True ถ้ามีอยู่จริง"""
    if not token:
        return False
    with _conn() as c:
        return c.execute("DELETE FROM auth_sessions WHERE token_hash=?",
                         (_hash(token),)).rowcount > 0


def revoke_user(username: str) -> int:
    """ลบทุก session ของ user (ใช้ตอนปิดบัญชี) — คืนจำนวนที่ลบ"""
    with _conn() as c:
        return c.execute("DELETE FROM auth_sessions WHERE username=?", (username,)).rowcount


def count() -> int:
    with _conn() as c:
        return int(c.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0])


def clear() -> None:
    with _conn() as c:
        c.execute("DELETE FROM auth_sessions")
    with _lock:
        _failures.clear()


# ---------- brute-force guard (ต่อ IP) ----------

def login_allowed(client_ip: str, now: float | None = None) -> bool:
    """False ถ้า IP นี้ล็อกอินพลาดเกิน LOGIN_MAX_FAILURES ครั้งใน LOGIN_WINDOW_SECONDS"""
    now = time.monotonic() if now is None else now
    with _lock:
        q = _failures[client_ip]
        while q and q[0] <= now - LOGIN_WINDOW_SECONDS:
            q.popleft()
        return len(q) < LOGIN_MAX_FAILURES


def record_failure(client_ip: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    with _lock:
        _failures[client_ip].append(now)


def reset_failures(client_ip: str) -> None:
    with _lock:
        _failures.pop(client_ip, None)
