"""Pure handlers for the three dashboard routes.

``dispatch`` does not bind a port and does not exchange an OAuth code.
CodexGPT calls it from ``app_server.py`` and writes the returned status, headers,
and body or SSE chunks. See docs/LCA_CORE.md.
"""

from __future__ import annotations

import hmac
import secrets
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from lca_core.constants import GOOGLE_CLIENT_ID
from lca_core.logs import LogOffline, iter_sse_chunks, tail_records
from lca_core.router import cluster_status
from lca_core.security import client_id_allowed, cors_headers, redirect_allowed

__all__ = [
    "GatewayContext",
    "auth_logout_body",
    "auth_start",
    "auth_status_body",
    "build_authorize_url",
    "clear_session_cookie",
    "cluster_status_body",
    "dispatch",
    "logs_snapshot",
    "logs_sse",
]

SESSION_COOKIE = "lca_session"


@dataclass
class GatewayContext:
    audit_path: Path
    probe: Callable
    session: dict = field(default_factory=dict)
    executor: object | None = None
    probe_timeout: float = 0.4
    expected_state: str | None = None


def auth_status_body(session: dict | None) -> dict:
    session = session or {}
    if not session.get("authenticated"):
        return {"authenticated": False}
    body: dict = {"authenticated": True}
    name = session.get("name")
    email = session.get("email")
    if isinstance(name, str) and name:
        body["name"] = name
    if isinstance(email, str) and email:
        body["email"] = email
    return body


def build_authorize_url(redirect_uri: str, state: str, client_id: str) -> str:
    """Build the Google authorize URL. This function does not open it."""
    if not redirect_allowed(redirect_uri):
        raise ValueError("redirect_uri is not allow-listed")
    if client_id != GOOGLE_CLIENT_ID:
        raise ValueError("client_id does not match")
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
    )
    return "https://accounts.google.com/o/oauth2/v2/auth?" + query


def auth_start(redirect_uri: str | None, client_id: str | None, state: str) -> dict:
    if not redirect_allowed(redirect_uri):
        return {"status": 400, "headers": _json_headers(), "body": {"error": "bad redirect_uri"}}
    if not client_id_allowed(client_id):
        return {"status": 400, "headers": _json_headers(), "body": {"error": "bad client_id"}}
    url = build_authorize_url(redirect_uri or "", state, client_id or GOOGLE_CLIENT_ID)
    return {
        "status": 200,
        "headers": _json_headers(),
        "body": {"url": url},
        "location": url,
        "state": state,
    }


def auth_logout_body() -> dict:
    return {"ok": True}


def clear_session_cookie() -> str:
    return f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"


def cluster_status_body(probe: Callable, *, executor=None, timeout: float = 0.4) -> dict:
    return cluster_status(probe, executor=executor, timeout=timeout)


def logs_snapshot(path: Path) -> dict:
    try:
        lines = tail_records(path)
    except LogOffline as exc:
        return {
            "status": 503,
            "headers": _json_headers(),
            "body": {"error": "offline", "detail": exc.detail},
        }
    return {"status": 200, "headers": _json_headers(), "body": {"lines": lines}}


def logs_sse(path: Path) -> dict:
    try:
        lines = tail_records(path)
    except LogOffline as exc:
        return {
            "status": 503,
            "headers": _json_headers(),
            "body": {"error": "offline", "detail": exc.detail},
        }
    chunks = list(iter_sse_chunks(lines))
    return {
        "status": 200,
        "headers": {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
        },
        "chunks": chunks,
    }


def dispatch(
    method: str,
    path: str,
    query: dict | None = None,
    *,
    ctx: GatewayContext,
    accept: str = "",
    origin: str | None = None,
) -> dict:
    """Return a response dict for one of the contracted routes.

    Keys: ``status``, ``headers``, and either ``body`` or ``chunks``.
    ``location`` is set when the gateway may answer 302 for login start.
    Login start defaults to 200 JSON ``{"url": ...}`` which the page also accepts.
    """
    method = (method or "").upper()
    path = (path or "").split("?", 1)[0]
    query = {str(k): "" if v is None else str(v) for k, v in (query or {}).items()}
    if path not in ("/auth/google", "/api/cluster/status", "/api/logs/stream"):
        return _with_cors(_not_implemented(404), origin)
    if method == "OPTIONS":
        headers = cors_headers(origin) or {}
        if origin and not headers:
            return {"status": 403, "headers": _json_headers(), "body": {"error": "origin refused"}}
        return {"status": 204, "headers": headers, "body": None}
    if path == "/auth/google":
        result = _auth(method, query, ctx)
    elif path == "/api/cluster/status":
        result = _cluster(method, ctx)
    else:
        result = _logs(method, query, ctx, accept)
    return _with_cors(result, origin)


def _auth(method: str, query: dict, ctx: GatewayContext) -> dict:
    mode = query.get("mode", "")
    if method == "GET" and mode == "status":
        return {
            "status": 200,
            "headers": _json_headers(),
            "body": auth_status_body(ctx.session),
        }
    if method == "GET" and mode == "start":
        state = ctx.expected_state or secrets.token_urlsafe(16)
        return auth_start(query.get("redirect_uri"), query.get("client_id"), state)
    if method == "GET" and query.get("code"):
        return _callback(query, ctx)
    if method == "POST" and mode == "logout":
        return {
            "status": 200,
            "headers": {**_json_headers(), "Set-Cookie": clear_session_cookie()},
            "body": auth_logout_body(),
        }
    if method == "GET" and mode == "logout":
        return _not_implemented(405)
    return _not_implemented(404)


def _callback(query: dict, ctx: GatewayContext) -> dict:
    """Validate state locally. The gateway still has to exchange the code.

    The authorization code is not copied into the response body.
    """
    state = query.get("state") or ""
    expected = ctx.expected_state or ""
    if not state or not expected or not hmac.compare_digest(state, expected):
        return {"status": 400, "headers": _json_headers(), "body": {"error": "bad state"}}
    return {
        "status": 200,
        "headers": _json_headers(),
        "body": {"ok": True, "exchange": "gateway"},
        "location": "/#/account",
    }


def _cluster(method: str, ctx: GatewayContext) -> dict:
    if method != "GET":
        return _not_implemented(405)
    body = cluster_status_body(ctx.probe, executor=ctx.executor, timeout=ctx.probe_timeout)
    return {"status": 200, "headers": _json_headers(), "body": body}


def _logs(method: str, query: dict, ctx: GatewayContext, accept: str) -> dict:
    if method != "GET":
        return _not_implemented(405)
    wants_json = query.get("format") == "json" or (
        "application/json" in accept and "text/event-stream" not in accept
    )
    if wants_json:
        return logs_snapshot(ctx.audit_path)
    return logs_sse(ctx.audit_path)


def _json_headers() -> dict:
    return {"Content-Type": "application/json; charset=utf-8"}


def _not_implemented(status: int) -> dict:
    return {"status": status, "headers": _json_headers(), "body": {"error": "not implemented"}}


def _with_cors(result: dict, origin: str | None) -> dict:
    if not origin:
        return result
    extra = cors_headers(origin)
    if not extra:
        return result
    headers = dict(result.get("headers") or {})
    headers.update(extra)
    merged = dict(result)
    merged["headers"] = headers
    return merged
