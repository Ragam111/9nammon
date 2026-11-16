"""Shared chat result types and the provider base class.

``chat`` returns ``ChatResponse``. ``stream`` returns a ``TextStream`` of text
deltas (``str``). After the stream is consumed or closed, ``usage`` and
``cost`` are set. Token counts missing from the provider are filled with
``estimate_tokens`` and marked ``estimated``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.errors import ProviderAuthError, ProviderError
from app.providers.keys import lookup_secret
from app.providers.messages import prepare_messages
from app.providers.pricing import estimate_cost, estimate_message_tokens, estimate_tokens
from app.providers.transport import close_response


def as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value, 10)
        except ValueError:
            return None
    return None


def first_int(mapping, *keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return as_int(mapping[key])
    return None


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated: bool
    source: str


@dataclass(frozen=True)
class ChatResponse:
    text: str
    model: str
    provider: str
    usage: Usage
    cost: object


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider: str
    display_name: str | None = None


def merge_usage(bucket: dict, part: dict | None) -> None:
    if not part:
        return
    for key in ("input", "output", "total"):
        if key in part and part[key] is not None:
            number = as_int(part[key])
            if number is not None:
                bucket[key] = number


def finalize_usage(parts: dict, messages, output_text: str) -> Usage:
    """Prefer provider counts. Fill gaps with the character estimate."""
    in_tokens = as_int(parts.get("input"))
    out_tokens = as_int(parts.get("output"))
    total = as_int(parts.get("total"))
    had_in = in_tokens is not None
    had_out = out_tokens is not None
    if in_tokens is None:
        in_tokens = estimate_message_tokens(messages)
    if out_tokens is None:
        out_tokens = estimate_tokens(output_text or "")
    if had_in and had_out:
        estimated = False
        source = "provider"
    elif not had_in and not had_out:
        estimated = True
        source = "estimate"
    else:
        estimated = True
        source = "mixed"
    if total is None and in_tokens is not None and out_tokens is not None:
        total = in_tokens + out_tokens
    return Usage(in_tokens, out_tokens, total, estimated, source)


def complete(provider_name, model, text, parts, messages, price_table) -> ChatResponse:
    usage = finalize_usage(parts, messages, text)
    cost = estimate_cost(provider_name, model, usage, table=price_table)
    return ChatResponse(
        text=text,
        model=model,
        provider=provider_name,
        usage=usage,
        cost=cost,
    )


class TextStream:
    """Iterator of text deltas. ``usage`` and ``cost`` are ready after exhaustion or ``close``."""

    def __init__(self, iterator, holder: dict):
        self._it = iter(iterator)
        self._holder = holder
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._it)
        except StopIteration:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        closer = getattr(self._it, "close", None)
        if closer is not None:
            try:
                closer()
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @property
    def usage(self):
        return self._holder.get("usage")

    @property
    def cost(self):
        return self._holder.get("cost")


def attach_stream(provider_name, model, messages, price_table, resp, events):
    """Wrap an open response. ``events`` yields ``("delta", str)`` or ``("usage", dict)``."""
    bucket = {"input": None, "output": None, "total": None}
    holder: dict = {}

    def gen():
        parts: list[str] = []
        try:
            for kind, value in events:
                if kind == "usage":
                    merge_usage(bucket, value)
                elif kind == "delta" and value:
                    parts.append(value)
                    yield value
        finally:
            closer = getattr(events, "close", None)
            if closer is not None:
                try:
                    closer()
                except Exception:
                    pass
            close_response(resp)
            usage = finalize_usage(bucket, messages, "".join(parts))
            holder["usage"] = usage
            holder["cost"] = estimate_cost(provider_name, model, usage, table=price_table)

    return TextStream(gen(), holder)


def checked_model(model) -> str:
    if not isinstance(model, str) or not model.strip():
        raise ProviderError("model is required")
    model = model.strip()
    if any(ch in model for ch in "\r\n\x00"):
        raise ProviderError("model id is invalid")
    return model


def _number(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(f"{name} must be a number")
    return value


def _positive_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProviderError(f"{name} must be a positive integer")
    return value


def take_options(opts: dict) -> dict:
    opts = dict(opts)
    timeout = opts.pop("timeout", None)
    system = opts.pop("system", None)
    api = opts.pop("api", None)
    if api is None:
        api = opts.pop("openai_api", None)
    else:
        opts.pop("openai_api", None)
    price_table = opts.pop("price_table", None)
    if timeout is not None and (
        isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0
    ):
        raise ProviderError("timeout must be a positive number")
    sampling: dict = {}
    if "temperature" in opts:
        sampling["temperature"] = _number("temperature", opts.pop("temperature"))
    if "top_p" in opts:
        sampling["top_p"] = _number("top_p", opts.pop("top_p"))
    if "max_tokens" in opts:
        sampling["max_tokens"] = _positive_int("max_tokens", opts.pop("max_tokens"))
    if opts:
        raise ProviderError("unsupported options: " + ", ".join(sorted(opts)))
    return {
        "timeout": timeout,
        "system": system,
        "api": api,
        "price_table": price_table,
        "sampling": sampling,
    }


class Provider:
    """Common surface: ``chat``, ``stream``, ``list_models``."""

    name = "base"
    key_names: tuple[str, ...] = ()
    requires_key = False
    default_timeout = 120
    default_base = ""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        project_root=None,
        timeout: float | None = None,
        price_table=None,
    ):
        if api_key is not None and not isinstance(api_key, str):
            raise ProviderError("api_key must be a string")
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        self.base_url = (base_url if base_url else self.default_base).rstrip("/")
        self.project_root = project_root
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0):
            raise ProviderError("timeout must be a positive number")
        self.timeout = self.default_timeout if timeout is None else timeout
        self.price_table = price_table

    def resolve_key(self) -> str | None:
        if self.api_key:
            return self.api_key
        if not self.key_names:
            return None
        return lookup_secret(self.project_root, self.key_names)

    def require_key(self) -> str | None:
        key = self.resolve_key()
        if self.requires_key and not key:
            names = ", ".join(self.key_names) or "API key"
            raise ProviderAuthError(
                f"{self.name}: no API key configured ({names})",
                provider=self.name,
                status=401,
            )
        return key

    def secret_values(self, key: str | None) -> list[str]:
        return [key] if key else []

    def begin(self, messages, model, opts, *, allow_api: bool = False):
        model = checked_model(model)
        parsed = take_options(opts)
        if parsed["api"] is not None and not allow_api:
            raise ProviderError(f"{self.name}: unsupported option api")
        msgs = prepare_messages(messages, parsed["system"])
        timeout = self.timeout if parsed["timeout"] is None else parsed["timeout"]
        table = self.price_table if parsed["price_table"] is None else parsed["price_table"]
        key = self.require_key()
        if not self.base_url:
            raise ProviderError(f"{self.name}: base_url is required")
        return model, parsed, msgs, timeout, table, key

    def chat(self, messages, model, **opts) -> ChatResponse:
        raise NotImplementedError

    def stream(self, messages, model, **opts) -> TextStream:
        raise NotImplementedError

    def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError
