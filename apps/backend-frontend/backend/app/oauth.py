"""Sign in with Google or GitHub (OAuth 2.0 authorization code flow). Apple is not built yet.

The browser goes to the provider with a random `state`, which is also kept in an httpOnly cookie.
The callback accepts the code only when the two match. Accounts are never linked by email: a provider
identity gets its own user row, so a provider login cannot take over a password account.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .errors import AppError

STATE_COOKIE = "bf_oauth_state"
LINK_COOKIE = "bf_oauth_link"  # set when a signed-in user is linking a provider, not signing in
STATE_COOKIE_PATH = "/api/auth/oauth"


@dataclass(frozen=True)
class Provider:
    name: str
    authorize_url: str
    token_url: str
    profile_url: str
    scope: str


PROVIDERS: dict[str, Provider] = {
    "google": Provider(
        "google",
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        "https://openidconnect.googleapis.com/v1/userinfo",
        "openid profile email",
    ),
    "github": Provider(
        "github",
        "https://github.com/login/oauth/authorize",
        "https://github.com/login/oauth/access_token",
        "https://api.github.com/user",
        "read:user",
    ),
}


def redirect_uri(base_url: str, provider: str) -> str:
    return f"{base_url.rstrip('/')}/api/auth/oauth/{provider}/callback"


def new_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(provider: Provider, client_id: str, redirect: str, state: str) -> str:
    query = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
    }
    return f"{provider.authorize_url}?{urlencode(query)}"


def states_match(cookie_state: str | None, query_state: str | None) -> bool:
    """Constant-time comparison; a missing value on either side never matches."""
    return bool(cookie_state and query_state) and hmac.compare_digest(str(cookie_state), str(query_state))


async def fetch_profile(
    client: httpx.AsyncClient,
    provider: Provider,
    client_id: str,
    client_secret: str,
    code: str,
    redirect: str,
) -> tuple[str, str]:
    """Trade the code for an access token, then read the account's stable id and a display name."""
    try:
        token_res = await client.post(
            provider.token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        access = _json(token_res).get("access_token") if token_res.status_code == 200 else None
        if not access:
            raise AppError("auth", "ยืนยันตัวตนกับผู้ให้บริการไม่สำเร็จ ลองเข้าสู่ระบบใหม่")
        profile_res = await client.get(
            provider.profile_url,
            headers={"Authorization": f"Bearer {access}", "Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise AppError("upstream", "เชื่อมต่อผู้ให้บริการล็อกอินไม่ได้ ลองใหม่อีกครั้ง") from exc
    if profile_res.status_code != 200:
        raise AppError("auth", "อ่านข้อมูลบัญชีจากผู้ให้บริการไม่สำเร็จ")
    data = _json(profile_res)
    subject = str(data.get("sub") or data.get("id") or "")
    display = str(data.get("email") or data.get("login") or "")
    if not subject:
        raise AppError("auth", "ผู้ให้บริการไม่ได้ส่งรหัสบัญชีกลับมา")
    return subject, display


def _json(response: httpx.Response) -> dict[str, object]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
