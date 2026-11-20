"""Users, password hashing (scrypt, stdlib) and server-side sessions behind an httpOnly cookie."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from .db import Database
from .errors import AppError

SESSION_COOKIE = "bf_session"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
_MIN_PASSWORD = 10
_dummy_hash = ""  # built on first use; compared against when the username does not exist


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str


def hash_password(password: str) -> str:
    """Return 'scrypt$<salt hex>$<hash hex>'."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against a stored scrypt hash."""
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


def create_user(db: Database, username: str, password: str, role: str = "user") -> User:
    """Create a user. Raises AppError('validation') for a short password or a taken name."""
    if len(password) < _MIN_PASSWORD:
        raise AppError("validation", f"รหัสผ่านต้องยาวอย่างน้อย {_MIN_PASSWORD} ตัวอักษร")
    try:
        with db.session() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, hash_password(password), role),
            )
            return User(int(cur.lastrowid or 0), username, role)
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise AppError("validation", "ชื่อผู้ใช้นี้มีอยู่แล้ว") from exc
        raise


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def login(db: Database, username: str, password: str, ttl_hours: int) -> str:
    """Check credentials and return a new raw session token (only its hash is stored)."""
    with db.session() as conn:
        row = conn.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,)).fetchone()
    # Exactly one scrypt run on both paths, so timing does not reveal which usernames exist.
    global _dummy_hash
    if not row and not _dummy_hash:
        _dummy_hash = hash_password(secrets.token_hex(16))
    stored = row["password_hash"] if row else _dummy_hash
    if not verify_password(password, stored) or row is None:
        raise AppError("auth", "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    token = secrets.token_urlsafe(32)
    with db.session() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (_token_hash(token), row["id"], time.time() + ttl_hours * 3600),
        )
    return token


def user_for_token(db: Database, token: str | None) -> User:
    """Return the user for a session token, or raise AppError('auth')."""
    if not token:
        raise AppError("auth")
    with db.session() as conn:
        row = conn.execute(
            "SELECT u.id, u.username, u.role FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?",
            (_token_hash(token), time.time()),
        ).fetchone()
    if row is None:
        raise AppError("auth")
    return User(row["id"], row["username"], row["role"])


def logout(db: Database, token: str | None) -> None:
    """Delete the session if it exists. Safe to call twice."""
    if token:
        with db.session() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
