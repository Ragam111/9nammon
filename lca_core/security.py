"""L4 — origin allow-list, CORS helper, loopback filter.

No wildcard origins. No network calls.
"""

from __future__ import annotations

import ipaddress

from lca_core.constants import AUTH_REDIRECT_URIS, DASHBOARD_ORIGINS, GOOGLE_CLIENT_ID

__all__ = [
    "GOOGLE_CLIENT_ID",
    "cors_config",
    "cors_headers",
    "is_loopback_ip",
    "origin_allowed",
    "redirect_allowed",
    "client_id_allowed",
]


def origin_allowed(origin: str | None) -> bool:
    """Exact match against the two dashboard origins. Trailing slash is rejected."""
    if not origin or not isinstance(origin, str):
        return False
    return origin in DASHBOARD_ORIGINS


def redirect_allowed(redirect_uri: str | None) -> bool:
    if not redirect_uri or not isinstance(redirect_uri, str):
        return False
    return redirect_uri in AUTH_REDIRECT_URIS


def client_id_allowed(client_id: str | None) -> bool:
    """Missing client id is acceptable. A present id must match the public one."""
    if client_id is None or client_id == "":
        return True
    return client_id == GOOGLE_CLIENT_ID


def cors_config() -> dict:
    """Keyword arguments for a future CORSMiddleware. Starlette is not imported.

    ``allow_origins`` is a new list so a caller cannot mutate the constant.
    """
    return {
        "allow_origins": list(DASHBOARD_ORIGINS),
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Accept"],
        "max_age": 600,
    }


def cors_headers(origin: str | None) -> dict | None:
    """Response headers for one allowed origin, or None when the origin is refused.

    The refused case omits ``Access-Control-Allow-Origin`` entirely. It never
    echoes ``*`` or the rejected origin.
    """
    if not origin_allowed(origin):
        return None
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Accept",
        "Vary": "Origin",
    }


def is_loopback_ip(value: str | None) -> bool:
    """True for localhost, 127.0.0.0/8, and ::1. False for LAN, any, and empty."""
    if value is None or not isinstance(value, str):
        return False
    text = value.strip().lower()
    if text == "localhost":
        return True
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    elif text.count(":") == 1 and "." in text:
        host, _, port = text.partition(":")
        if port.isdigit():
            text = host
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    return bool(address.is_loopback)
