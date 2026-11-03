"""Build a provider by name.

``get_provider("openai")`` talks to ``api.openai.com``. ``MODEL_BACKEND=openai``
in the existing config still means the OpenAI-compatible adapter
(``model_backend.OpenAICompatBackend``): a custom ``OPENAI_BASE_URL``, not the
official OpenAI API. Set ``CHAT_PROVIDER`` to pick a chat-hub provider without
changing that legacy switch.

``server.py`` keeps calling ``model_backend.generate``. This registry does not
replace those calls.
"""

from __future__ import annotations

from pathlib import Path

from app import config_manager
from app.providers.anthropic import AnthropicProvider
from app.providers.completions import OpenAICompatProvider, OpenAIProvider, XAIProvider
from app.providers.errors import ProviderError
from app.providers.gemini import GeminiProvider
from app.providers.ollama import OllamaProvider, default_ollama_root

REGISTRY = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "xai": XAIProvider,
    "ollama": OllamaProvider,
    "openai_compat": OpenAICompatProvider,
}

ALIASES = {
    "claude": "anthropic",
    "google": "gemini",
    "google-gemini": "gemini",
    "grok": "xai",
    "openai-compat": "openai_compat",
    "openai_compatible": "openai_compat",
}

BASE_CONFIG_KEYS = {
    "anthropic": "ANTHROPIC_BASE_URL",
    "openai": "OPENAI_OFFICIAL_BASE_URL",
    "gemini": "GEMINI_BASE_URL",
    "xai": "XAI_BASE_URL",
    "ollama": "OLLAMA_BASE_URL",
    "openai_compat": "OPENAI_BASE_URL",
}


def supported_providers() -> tuple[str, ...]:
    return tuple(REGISTRY)


def canonicalize(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ProviderError("provider name is required")
    key = name.strip().lower().replace(" ", "")
    key = ALIASES.get(key, key)
    if key not in REGISTRY:
        known = ", ".join(supported_providers())
        raise ProviderError(f"unknown provider {name!r} (expected one of: {known})")
    return key


def _cfg(project_root, key: str) -> str | None:
    if project_root is None:
        return None
    try:
        value = config_manager.get_key(project_root, key)
    except Exception:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _select_name(project_root) -> str:
    """CHAT_PROVIDER wins. Otherwise follow MODEL_BACKEND, with openai → compat."""
    if project_root is None:
        return "ollama"
    chosen = (_cfg(project_root, "CHAT_PROVIDER") or "").lower()
    if chosen:
        return chosen
    legacy = (_cfg(project_root, "MODEL_BACKEND") or "ollama").strip().lower()
    if legacy in ("openai", "openai_compat", "openai-compat"):
        return "openai_compat"
    return "ollama"


def _default_openai_compat_base() -> str:
    from app.model_backend import DEFAULT_OPENAI_BASE
    return DEFAULT_OPENAI_BASE


def get_provider(name: str | None = None, project_root=None, **kwargs):
    """Return a provider. ``name`` defaults from config, then Ollama."""
    root = None if project_root is None else Path(project_root)
    if name is None:
        name = _select_name(root)
    canonical = canonicalize(name)
    cls = REGISTRY[canonical]
    if kwargs.get("base_url") in (None, ""):
        kwargs.pop("base_url", None)
    if "base_url" not in kwargs:
        base = configured_base_url(canonical, root)
        if base:
            kwargs["base_url"] = base
    kwargs.setdefault("project_root", root)
    return cls(**kwargs)


def configured_base_url(name: str, project_root=None) -> str | None:
    """Base URL ``get_provider`` would use, or ``None`` for the adapter's own default.

    Config key first (``BASE_CONFIG_KEYS``), then the local defaults for
    ``openai_compat`` and ``ollama``. Cloud adapters with no override return
    ``None`` (their built-in public endpoint).
    """
    canonical = canonicalize(name)
    root = None if project_root is None else Path(project_root)
    configured = _cfg(root, BASE_CONFIG_KEYS[canonical])
    if configured:
        return configured
    if canonical == "openai_compat":
        return _default_openai_compat_base()
    if canonical == "ollama":
        return default_ollama_root()
    return None
