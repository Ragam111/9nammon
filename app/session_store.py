"""session_store.py — session token หลัง login ด้วย username/password (in-memory, stdlib)

ทำไมต้องมี: org_store มี user+password (PBKDF2) อยู่แล้ว แต่ไม่มีทางให้ "คน" ล็อกอิน —
มีแต่ master token กับ API key ที่ต้องวางเอง. โมดูลนี้แปลง login ที่ถูกต้องเป็น
session token อายุจำกัด ซึ่ง server รับผ่าน X-Auth-Token เหมือน token อื่น

ออกแบบ:
- เก็บใน RAM ต่อ process (รีสตาร์ต = ทุกคน login ใหม่) — ไม่มี token ลงดิสก์
- token = ``lcs_`` + secrets.token_urlsafe(32); เทียบด้วย compare_digest เสมอ
- TTL เริ่มต้น 12 ชั่วโมง; verify() ลบ session หมดอายุให้เอง
- login limiter ต่อ IP (sliding window) กัน brute-force รหัสผ่าน
- thread-safe (ThreadingHTTPServer)
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

SESSION_TTL_SECONDS = 12 * 60 * 60
TOKEN_PREFIX = "lcs_"
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 60.0

_lock = threading.Lock()
_sessions: dict[str, dict] = {}
_failures: dict[str, deque] = defaultdict(deque)


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
    with _lock:
        _sessions[token] = record
    return {"token": token, **record}


def verify(token: str | None, now: float | None = None) -> dict | None:
    """คืน identity dict ถ้า token เป็น session ที่ยังไม่หมดอายุ, ไม่งั้น None"""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    now = time.time() if now is None else now
    with _lock:
        matched = None
        for known, rec in list(_sessions.items()):
            if rec["expires_at"] <= now:
                _sessions.pop(known, None)
                continue
            if hmac.compare_digest(token, known):
                matched = rec
        if matched is None:
            return None
        return {
            "username": matched["username"],
            "role": matched["role"],
            "tier": matched["tier"],
            "key_id": None,
            "source": "session",
            "expires_at": matched["expires_at"],
        }


def revoke(token: str | None) -> bool:
    """ลบ session — True ถ้ามีอยู่จริง"""
    if not token:
        return False
    with _lock:
        return _sessions.pop(token, None) is not None


def revoke_user(username: str) -> int:
    """ลบทุก session ของ user (ใช้ตอนปิดบัญชี) — คืนจำนวนที่ลบ"""
    with _lock:
        gone = [t for t, rec in _sessions.items() if rec["username"] == username]
        for t in gone:
            _sessions.pop(t, None)
    return len(gone)


def count() -> int:
    with _lock:
        return len(_sessions)


def clear() -> None:
    with _lock:
        _sessions.clear()
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
