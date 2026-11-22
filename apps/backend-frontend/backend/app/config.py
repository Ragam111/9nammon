"""Settings read from environment variables. See ../../.env.example for every variable."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Model ids offered for chat when the CHAT_*_MODELS variables are not set.
DEFAULT_OPENAI_MODELS = ("gpt-4o-mini", "gpt-4o")
DEFAULT_GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.5-pro")
DEFAULT_ANTHROPIC_MODELS = ("claude-sonnet-4-6", "claude-haiku-4-5")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return default if not raw else raw in {"1", "true", "yes", "on"}


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    return default if not raw else [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    """All runtime settings. Secret values (the model API key) are never logged or returned."""

    data_dir: Path
    model_base_url: str
    model_name: str
    model_api_key: str = field(repr=False)
    model_timeout_s: float
    model_max_retries: int
    retry_base_delay_s: float
    max_input_chars: int
    max_output_tokens: int
    quota_tokens_per_window: int
    rate_limit_user_per_min: int
    rate_limit_ip_per_min: int
    session_ttl_hours: int
    cookie_secure: bool
    cors_origins: list[str]
    cost_per_1k_tokens: float
    # Proxies whose X-Real-IP header is trusted for rate limits (e.g. the nginx container). Empty = trust none.
    trusted_proxies: list[str] = field(default_factory=list)
    # Logins per client IP and per username, per minute. The E2E server raises them; keep defaults in production.
    login_per_ip_per_min: int = 10
    login_per_user_per_min: int = 5
    # Weekly limits (all models, and models listed in HEAVY_MODELS). Windows reset Wednesday 15:00 Bangkok time.
    quota_tokens_weekly: int = 5_000_000
    quota_tokens_heavy_weekly: int = 1_000_000
    heavy_models: list[str] = field(default_factory=list)
    # Public address of the site, used to build OAuth redirect URLs (no trailing slash)
    public_base_url: str = "http://127.0.0.1:8080"
    oauth_google_client_id: str = ""
    oauth_google_client_secret: str = field(default="", repr=False)
    oauth_github_client_id: str = ""
    oauth_github_client_secret: str = field(default="", repr=False)
    # Chat providers over OpenAI-compatible endpoints. Keys come only from the environment (never stored or returned).
    chat_openai_base_url: str = "https://api.openai.com/v1"
    chat_openai_api_key: str = field(default="", repr=False)
    chat_openai_models: list[str] = field(default_factory=lambda: list(DEFAULT_OPENAI_MODELS))
    chat_gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    chat_gemini_api_key: str = field(default="", repr=False)
    chat_gemini_models: list[str] = field(default_factory=lambda: list(DEFAULT_GEMINI_MODELS))
    chat_anthropic_base_url: str = "https://api.anthropic.com/v1"
    chat_anthropic_api_key: str = field(default="", repr=False)
    chat_anthropic_models: list[str] = field(default_factory=lambda: list(DEFAULT_ANTHROPIC_MODELS))

    def oauth_client(self, provider: str) -> tuple[str, str] | None:
        """(client id, client secret) when the provider is fully configured, else None."""
        pairs = {
            "google": (self.oauth_google_client_id, self.oauth_google_client_secret),
            "github": (self.oauth_github_client_id, self.oauth_github_client_secret),
        }
        pair = pairs.get(provider)
        return pair if pair and pair[0] and pair[1] else None


def load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines from a .env file into os.environ. Real environment variables win.
    Stdlib only, so `uvicorn --env-file` (which needs python-dotenv) is not required."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name.strip(), value)


def load_settings() -> Settings:
    """Build Settings from the environment, after loading ENV_FILE (default ./.env) if it exists."""
    load_env_file(Path(os.environ.get("ENV_FILE", ".env")))
    return Settings(
        data_dir=Path(os.environ.get("DATA_DIR", "./data")).resolve(),
        model_base_url=os.environ.get("MODEL_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/"),
        model_name=os.environ.get("MODEL_NAME", "qwen2.5-coder:1.5b"),
        model_api_key=os.environ.get("MODEL_API_KEY", ""),
        model_timeout_s=_float("MODEL_TIMEOUT_S", 60.0),
        model_max_retries=_int("MODEL_MAX_RETRIES", 2),
        retry_base_delay_s=_float("RETRY_BASE_DELAY_S", 0.5),
        max_input_chars=_int("MAX_INPUT_CHARS", 8000),
        max_output_tokens=_int("MAX_OUTPUT_TOKENS", 1024),
        quota_tokens_per_window=_int("QUOTA_TOKENS_PER_WINDOW", 1_000_000),
        rate_limit_user_per_min=_int("RATE_LIMIT_USER_PER_MIN", 20),
        rate_limit_ip_per_min=_int("RATE_LIMIT_IP_PER_MIN", 60),
        session_ttl_hours=_int("SESSION_TTL_HOURS", 24),
        cookie_secure=_bool("COOKIE_SECURE", False),
        cors_origins=_list("CORS_ORIGINS", ["http://127.0.0.1:5173", "http://localhost:5173"]),
        cost_per_1k_tokens=_float("COST_PER_1K_TOKENS", 0.0),
        trusted_proxies=_list("TRUSTED_PROXY_CIDRS", []),
        login_per_ip_per_min=_int("LOGIN_PER_IP_PER_MIN", 10),
        login_per_user_per_min=_int("LOGIN_PER_USER_PER_MIN", 5),
        quota_tokens_weekly=_int("QUOTA_TOKENS_WEEKLY", 5_000_000),
        quota_tokens_heavy_weekly=_int("QUOTA_TOKENS_HEAVY_WEEKLY", 1_000_000),
        heavy_models=_list("HEAVY_MODELS", []),
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8080"),
        oauth_google_client_id=os.environ.get("OAUTH_GOOGLE_CLIENT_ID", ""),
        oauth_google_client_secret=os.environ.get("OAUTH_GOOGLE_CLIENT_SECRET", ""),
        oauth_github_client_id=os.environ.get("OAUTH_GITHUB_CLIENT_ID", ""),
        oauth_github_client_secret=os.environ.get("OAUTH_GITHUB_CLIENT_SECRET", ""),
        chat_openai_base_url=os.environ.get("CHAT_OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
        chat_openai_api_key=os.environ.get("CHAT_OPENAI_API_KEY", "").strip(),
        chat_openai_models=_list("CHAT_OPENAI_MODELS", list(DEFAULT_OPENAI_MODELS)),
        chat_gemini_base_url=os.environ.get(
            "CHAT_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai").strip().rstrip("/"),
        chat_gemini_api_key=os.environ.get("CHAT_GEMINI_API_KEY", "").strip(),
        chat_gemini_models=_list("CHAT_GEMINI_MODELS", list(DEFAULT_GEMINI_MODELS)),
        chat_anthropic_base_url=os.environ.get(
            "CHAT_ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").strip().rstrip("/"),
        chat_anthropic_api_key=os.environ.get("CHAT_ANTHROPIC_API_KEY", "").strip(),
        chat_anthropic_models=_list("CHAT_ANTHROPIC_MODELS", list(DEFAULT_ANTHROPIC_MODELS)),
    )
