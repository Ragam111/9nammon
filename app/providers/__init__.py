"""LCA Chat Hub provider adapters.

One transcript (``role`` + text ``content``) can move between providers
mid-conversation. Each provider implements:

* ``chat(messages, model, **opts) -> ChatResponse``
* ``stream(messages, model, **opts) -> TextStream`` yielding text deltas
* ``list_models() -> list[ModelInfo]``

``ChatResponse.usage`` is taken from the provider when it sends counts, and
filled with a 4-characters-per-token estimate otherwise. ``ChatResponse.cost``
is a configurable USD estimate (see ``pricing.PRICES``); ``authoritative`` is
always false.

Stdlib HTTP only (``urllib``, ``json``, ``http.client``, ``ssl``). Keys come
from the constructor or ``keys.lookup_secret`` (``config_manager.get_key``,
then ``app.secrets`` when PR #108 is present). This package does not replace
``model_backend.generate``; existing server and agent callers stay on that path.
"""

from __future__ import annotations

from app.providers.base import ChatResponse, ModelInfo, Provider, TextStream, Usage
from app.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from app.providers.keys import lookup_secret
from app.providers.messages import Message, normalize_messages, prepare_messages
from app.providers.pricing import (
    PRICES,
    CostEstimate,
    Price,
    estimate_cost,
    estimate_tokens,
    lookup_price,
    register_price,
)
from app.providers.registry import get_provider, supported_providers

__all__ = [
    "ChatResponse",
    "CostEstimate",
    "Message",
    "ModelInfo",
    "PRICES",
    "Price",
    "Provider",
    "ProviderAuthError",
    "ProviderError",
    "ProviderNetworkError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "TextStream",
    "Usage",
    "chat",
    "estimate_cost",
    "estimate_tokens",
    "get_provider",
    "list_models",
    "lookup_price",
    "lookup_secret",
    "normalize_messages",
    "prepare_messages",
    "register_price",
    "stream",
    "supported_providers",
]


def _resolve(provider, project_root):
    if isinstance(provider, Provider):
        return provider
    return get_provider(provider, project_root=project_root)


def chat(messages, model, *, provider, project_root=None, **opts) -> ChatResponse:
    return _resolve(provider, project_root).chat(messages, model, **opts)


def stream(messages, model, *, provider, project_root=None, **opts) -> TextStream:
    return _resolve(provider, project_root).stream(messages, model, **opts)


def list_models(provider, *, project_root=None):
    return _resolve(provider, project_root).list_models()
