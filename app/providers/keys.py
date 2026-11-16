"""API key lookup.

Order, first non-empty wins:

1. ``api_key`` passed to the provider constructor (never read from disk).
2. ``config_manager.get_key`` — config.json, then the environment. After PR
   #108 is merged, that function unseals ``app.secrets`` and still returns
   plaintext. This module does not duplicate that seal/unseal path.
3. If ``app.secrets`` imports and exposes ``reveal`` (PR #108,
   ``cursor/secrets-at-rest-2eae``, not on main as of this change), a
   ``{"$lca_secret_ref": ...}`` value or a direct ``config:<NAME>`` entry is
   revealed. If the module is absent, a sealed ref cannot be opened and the
   lookup returns ``None``.

The plaintext is returned to the caller and placed on an HTTP header. It is
not logged, not interpolated into errors, and not written to disk here.
"""

from __future__ import annotations

from pathlib import Path

from app import config_manager

REF_KEY = "$lca_secret_ref"

# Names are credentials under PR #108's ``is_secret_name`` rules (*_API_KEY).
PROVIDER_KEY_NAMES = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "xai": ("XAI_API_KEY",),
    "ollama": ("OLLAMA_API_KEY",),
    "openai_compat": ("OPENAI_COMPAT_API_KEY", "OPENAI_API_KEY"),
}


def load_secrets_module():
    """Return ``app.secrets`` when PR #108 is present, else ``None``."""
    try:
        from app import secrets as secrets_mod
    except ImportError:
        return None
    if not hasattr(secrets_mod, "reveal"):
        return None
    return secrets_mod


def _reveal(secrets_mod, project_root: Path, name: str) -> str | None:
    try:
        plain = secrets_mod.reveal(project_root, name)
    except Exception:
        return None
    if isinstance(plain, str) and plain.strip():
        return plain.strip()
    return None


def _from_config_value(project_root: Path, value, secrets_mod) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict) and secrets_mod is not None:
        name = value.get(REF_KEY)
        if isinstance(name, str) and name.strip():
            return _reveal(secrets_mod, project_root, name.strip())
    return None


def lookup_secret(project_root, names, *, secrets_module=None) -> str | None:
    """Return the first configured secret, or ``None``.

    ``secrets_module`` lets tests inject a double. ``None`` means "import
    ``app.secrets`` if it exists". Pass ``False`` to skip the store.
    """
    if project_root is None or not names:
        return None
    root = Path(project_root)
    if secrets_module is False:
        secrets_mod = None
    elif secrets_module is not None:
        secrets_mod = secrets_module
    else:
        secrets_mod = load_secrets_module()
    for name in names:
        try:
            raw = config_manager.get_key(root, name)
        except Exception:
            raw = None
        plain = _from_config_value(root, raw, secrets_mod)
        if plain:
            return plain
        if secrets_mod is None or raw not in (None, ""):
            continue
        entries = []
        if hasattr(secrets_mod, "config_entry_name"):
            entries.append(secrets_mod.config_entry_name(name))
        else:
            entries.append(f"config:{name}")
        entries.append(name)
        for entry in entries:
            revealed = _reveal(secrets_mod, root, entry)
            if revealed:
                return revealed
    return None
