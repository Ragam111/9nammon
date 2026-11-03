"""Local vs cloud, decided by where the request actually goes.

An endpoint is **local** only when the host in its ``base_url`` is
``localhost``, ``127.0.0.1`` or ``::1`` (written ``[::1]`` in a URL).
Everything else is **cloud**: a LAN address such as ``192.168.1.5``, another
machine's hostname, a tunnel, or a public API. The provider *name* alone never
makes a call local — an ``ollama`` or ``openai_compat`` entry pointed at
another host leaves this machine, so it is shown and scheduled as cloud.

Only the self-hostable adapters (``ollama``, ``openai_compat``) can be local.
Anthropic / OpenAI / Gemini / xAI stay cloud even behind a localhost proxy,
because the proxy forwards the prompt to the vendor.
"""

from __future__ import annotations

from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SELF_HOSTABLE = frozenset({"ollama", "openai_compat"})


def is_loopback_url(url) -> bool:
    """True only for a URL whose host is localhost, 127.0.0.1 or ::1 / [::1]."""
    if not isinstance(url, str):
        return False
    raw = url.strip()
    if not raw:
        return False
    if raw.lower() in LOOPBACK_HOSTS:  # bare host, e.g. "::1"
        return True
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = urlsplit(raw).hostname
    except ValueError:
        return False
    return (host or "") in LOOPBACK_HOSTS


def _legacy_backend_url(project_root) -> str | None:
    """Endpoint ``model_backend.get_backend`` would call (provider omitted)."""
    from app import config_manager
    from app.model_backend import DEFAULT_OPENAI_BASE, OLLAMA_URL
    if project_root is None:
        return OLLAMA_URL
    try:
        sel = (config_manager.get_key(project_root, "MODEL_BACKEND") or "ollama").strip().lower()
        if sel == "openai":
            return config_manager.get_key(project_root, "OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE
    except Exception:
        return None
    return OLLAMA_URL


def is_local_provider(provider, project_root=None) -> bool:
    """Classify a chat target. ``provider`` None means the ``model_backend`` path."""
    if provider is None:
        return is_loopback_url(_legacy_backend_url(project_root))
    from app.providers.errors import ProviderError
    from app.providers.registry import canonicalize, configured_base_url
    try:
        canonical = canonicalize(provider)
    except ProviderError:
        return False
    if canonical not in SELF_HOSTABLE:
        return False
    try:
        return is_loopback_url(configured_base_url(canonical, project_root))
    except Exception:
        return False
