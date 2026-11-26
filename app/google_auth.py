"""google_auth.py — stdlib-only Google sign-in (OAuth 2.0 code flow + PKCE S256).

Flow (server.py routes):
1. GET /auth/google/start    -> new state + PKCE verifier kept server-side (in memory,
   short TTL, one use) and the state in an HttpOnly SameSite=Lax cookie; redirect to
   the Google authorize URL with code_challenge (S256).
2. GET /auth/google/callback -> state must match the cookie and a pending entry; the
   code is exchanged with the code_verifier; userinfo must have a verified email.
   No session is issued here: the redirect carries a one-time login code in the
   fragment (#lca_login_code=) and sets an HttpOnly cookie (FINISH_COOKIE) holding a
   random binding value; only the hash of the binding is stored with the code.
3. POST /api/auth/google/finish {code} -> the session is issued only when the code is
   unused, unexpired and the cookie binding matches (login-CSRF / fixation guard:
   an attacker's code is useless in a victim browser without the attacker's cookie).

Config (config.json, env fallback): GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
GOOGLE_REDIRECT_URI. The redirect URI must be http://localhost or http://127.0.0.1,
or an https URL the owner configured. Endpoint URLs are module attributes so tests
can point them at a fake server on 127.0.0.1. The client secret and Google tokens
are never logged or put in an error message.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from urllib import error, parse, request

from app import config_manager

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

CALLBACK_PATH = "/auth/google/callback"
STATE_COOKIE = "lca_google_state"
STATE_TTL_SECONDS = 600
FINISH_COOKIE = "lca_google_finish"
FINISH_PATH = "/api/auth/google/finish"
FINISH_COOKIE_PATH = "/api/auth/google"
LOGIN_CODE_TTL_SECONDS = 60
MAX_LOGIN_CODES = 512
MAX_PENDING = 256
MAX_PENDING_PER_CLIENT = 8
START_RATE_MAX = 20          # /auth/google/start per client IP per window
START_RATE_WINDOW_S = 60.0
HTTP_TIMEOUT_S = 10
_LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1"})


class GoogleAuthError(Exception):
    """Sign-in failed. ``str(e)`` is a Thai message without secrets."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ---------- config ----------

def redirect_uri_allowed(uri: str) -> bool:
    """http only on localhost/127.0.0.1; https any host; path must be the callback."""
    try:
        u = parse.urlsplit(str(uri or ""))
        port = u.port  # raises on a bad port
    except ValueError:
        return False
    del port
    if u.username or u.password or u.query or u.fragment or u.path != CALLBACK_PATH:
        return False
    if u.scheme == "http":
        return (u.hostname or "") in _LOCAL_HTTP_HOSTS
    return u.scheme == "https" and bool(u.hostname)


def load_config(project_root) -> dict | None:
    """{client_id, client_secret, redirect_uri} or None when Google sign-in is off."""
    vals = {k: (config_manager.get_key(project_root, k) or "").strip()
            for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")}
    if not all(vals.values()) or not redirect_uri_allowed(vals["GOOGLE_REDIRECT_URI"]):
        return None
    return {"client_id": vals["GOOGLE_CLIENT_ID"], "client_secret": vals["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": vals["GOOGLE_REDIRECT_URI"]}


def config_problem(project_root) -> str:
    """Thai reason Google sign-in is off ('' when it is on)."""
    vals = {k: (config_manager.get_key(project_root, k) or "").strip()
            for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")}
    missing = [k for k, v in vals.items() if not v]
    if missing:
        return "ยังไม่ได้ตั้งค่าล็อกอินด้วย Google (ขาด " + ", ".join(missing) + " ใน config.json)"
    if not redirect_uri_allowed(vals["GOOGLE_REDIRECT_URI"]):
        return ("GOOGLE_REDIRECT_URI ไม่ได้รับอนุญาต — ใช้ http://localhost หรือ http://127.0.0.1 "
                f"หรือ https ที่ลงท้ายด้วย {CALLBACK_PATH}")
    return ""


# ---------- PKCE + pending state (server-side, one use) ----------

def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge) per RFC 7636."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


_pending: dict[str, tuple[str, str, float, str]] = {}   # state -> (verifier, next, expires, client)
_pending_lock = threading.Lock()


def _drop_oldest(keys) -> None:
    del _pending[min(keys, key=lambda k: _pending[k][2])]


def _prune(now: float, client: str) -> None:
    """Expire old entries, then make room. One client (IP) holds at most
    MAX_PENDING_PER_CLIENT; when the whole table is full the client holding the most
    loses its oldest — so a flood from one IP only evicts its own pending logins."""
    for key in [k for k, v in _pending.items() if v[2] <= now]:
        del _pending[key]
    own = [k for k, v in _pending.items() if v[3] == client]
    while len(own) >= MAX_PENDING_PER_CLIENT:
        _drop_oldest(own)
        own = [k for k in own if k in _pending]
    while len(_pending) >= MAX_PENDING:
        counts: dict[str, int] = {}
        for v in _pending.values():
            counts[v[3]] = counts.get(v[3], 0) + 1
        top = max(counts, key=counts.get)
        _drop_oldest([k for k, v in _pending.items() if v[3] == top])


def begin(next_path: str = "/chat", now: float | None = None,
          client: str = "") -> tuple[str, str]:
    """Create a pending login for ``client`` (the caller's IP). Returns (state, challenge)."""
    now = time.time() if now is None else now
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    with _pending_lock:
        _prune(now, client)
        _pending[state] = (verifier, next_path, now + STATE_TTL_SECONDS, client)
    return state, challenge


def take(state: str, cookie_state: str, now: float | None = None) -> tuple[str, str] | None:
    """One-use lookup: (verifier, next) when state matches the cookie and is not expired."""
    if not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
        return None
    now = time.time() if now is None else now
    with _pending_lock:
        entry = _pending.pop(state, None)
    if entry is None or entry[2] <= now:
        return None
    return entry[0], entry[1]


def clear_pending() -> None:
    with _pending_lock:
        _pending.clear()
        _login_codes.clear()


# ---------- one-time login codes (callback -> /api/auth/google/finish) ----------

# sha256(code) -> (sha256(binding), username, expires_at)
_login_codes: dict[str, tuple[str, str, float]] = {}


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_login_code(username: str, now: float | None = None) -> tuple[str, str]:
    """Create a single-use login code for ``username``. Returns (code, binding);
    the binding goes in the HttpOnly finish cookie, only hashes are kept."""
    now = time.time() if now is None else now
    code, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with _pending_lock:
        for k in [k for k, v in _login_codes.items() if v[2] <= now]:
            del _login_codes[k]
        if len(_login_codes) >= MAX_LOGIN_CODES:
            _drop_oldest_codes()
        _login_codes[_h(code)] = (_h(binding), username, now + LOGIN_CODE_TTL_SECONDS)
    return code, binding


def _drop_oldest_codes() -> None:
    oldest = min(_login_codes, key=lambda k: _login_codes[k][2])
    del _login_codes[oldest]


def redeem_login_code(code: str, binding: str, now: float | None = None) -> str | None:
    """Username when ``code`` is unused, unexpired and ``binding`` matches; else None.
    Any attempt consumes the code (single use, no retries with other cookies)."""
    if not code or not isinstance(code, str) or len(code) > 128:
        return None
    now = time.time() if now is None else now
    with _pending_lock:
        entry = _login_codes.pop(_h(code), None)
    if entry is None or entry[2] <= now or not binding:
        return None
    if not hmac.compare_digest(entry[0], _h(binding)):
        return None
    return entry[1]


def authorize_url(cfg: dict, state: str, challenge: str) -> str:
    query = parse.urlencode({
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return f"{AUTH_URL}?{query}"


# ---------- token exchange + userinfo ----------

def _json(req: request.Request) -> dict:
    with request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def exchange_code(cfg: dict, code: str, verifier: str) -> str:
    """Code + code_verifier -> access token (raises GoogleAuthError 400)."""
    if not code or not verifier:
        raise GoogleAuthError(400, "ไม่มีรหัสยืนยันจาก Google — เริ่มเข้าสู่ระบบใหม่")
    body = parse.urlencode({
        "code": code,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": cfg["redirect_uri"],
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }).encode("utf-8")
    req = request.Request(TOKEN_URL, data=body, method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded",
                                   "Accept": "application/json"})
    try:
        data = _json(req)
    except (error.URLError, OSError, ValueError) as e:
        print(f"[google][warn] แลก code ไม่สำเร็จ ({e.__class__.__name__})")
        raise GoogleAuthError(400, "แลกรหัสกับ Google ไม่สำเร็จ — เริ่มเข้าสู่ระบบใหม่") from None
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise GoogleAuthError(400, "Google ไม่ได้ส่ง access token กลับมา")
    return token


def fetch_identity(access_token: str) -> dict:
    """userinfo -> {sub, email, name}; email must be verified (raises GoogleAuthError)."""
    req = request.Request(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}",
                                                 "Accept": "application/json"})
    try:
        info = _json(req)
    except (error.URLError, OSError, ValueError) as e:
        print(f"[google][warn] อ่านข้อมูลผู้ใช้ไม่สำเร็จ ({e.__class__.__name__})")
        raise GoogleAuthError(502, "อ่านข้อมูลบัญชีจาก Google ไม่สำเร็จ") from None
    sub = info.get("sub")
    email = str(info.get("email") or "").strip().lower()
    if not isinstance(sub, str) or not sub or not email:
        raise GoogleAuthError(400, "Google ไม่ได้ส่งอีเมลของบัญชีมา")
    if info.get("email_verified") not in (True, "true"):
        raise GoogleAuthError(403, "อีเมล Google นี้ยังไม่ได้ยืนยัน — ใช้บัญชีที่ยืนยันอีเมลแล้ว")
    name = str(info.get("name") or info.get("given_name") or "").strip()
    return {"sub": sub, "email": email, "name": name}
