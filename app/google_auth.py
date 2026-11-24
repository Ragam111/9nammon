"""google_auth.py — stdlib-only Google OAuth helpers for LCA.

This module performs the minimal OAuth steps required for Google login:
1. exchange authorization code for access token
2. fetch user profile from Google UserInfo endpoint
3. return fail-closed data or None on any failure
"""

from __future__ import annotations

import json
from urllib import parse, request

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def exchange_code_for_google_user(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict | None:
    """Exchange OAuth code for Google account info.

    Returns a dict with {email, name} or None if the exchange fails. This function is
    intentionally fail-closed: if any step fails, we return None rather than creating a
    partial identity.
    """
    if not code or not client_id or not client_secret or not redirect_uri:
        return None

    try:
        payload = parse.urlencode({
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")

        token_req = request.Request(GOOGLE_TOKEN_URL, data=payload, method="POST")
        token_req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with request.urlopen(token_req, timeout=10) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))

        access_token = (token_data or {}).get("access_token")
        if not access_token:
            return None

        user_req = request.Request(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with request.urlopen(user_req, timeout=10) as resp:
            user_info = json.loads(resp.read().decode("utf-8"))

        email = (user_info.get("email") or "").strip().lower()
        name = (user_info.get("name") or user_info.get("given_name") or "Google User").strip()
        if not email:
            return None
        return {"email": email, "name": name}
    except Exception:
        return None
