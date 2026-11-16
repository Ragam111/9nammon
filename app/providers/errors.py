"""Normalized provider errors.

Messages name the provider and the failure class. They never include an API
key. Callers map these onto HTTP statuses (401 auth, 429 rate limit, 504
timeout) without parsing vendor wording.
"""

from __future__ import annotations


class ProviderError(Exception):
    """The provider call failed, or the request was rejected locally."""

    kind = "error"

    def __init__(self, message: str, *, provider: str | None = None, status: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.status = status


class ProviderAuthError(ProviderError):
    """Missing key, or the provider returned 401/403."""

    kind = "auth"


class ProviderRateLimitError(ProviderError):
    """Provider returned 429. ``retry_after`` is seconds when the header parses."""

    kind = "rate_limit"

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        retry_after_raw: str | None = None,
        provider: str | None = None,
        status: int | None = 429,
    ):
        super().__init__(message, provider=provider, status=status)
        self.retry_after = retry_after
        self.retry_after_raw = retry_after_raw


class ProviderTimeoutError(ProviderError):
    """Socket timeout, or the provider returned 408/504."""

    kind = "timeout"


class ProviderNetworkError(ProviderError):
    """DNS, connection, or HTTP-library failure before a usable response."""

    kind = "network"
