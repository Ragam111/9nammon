"""HTTP for provider adapters. Stdlib only.

TLS verification stays on: HTTPS uses ``ssl.create_default_context()`` with
``CERT_REQUIRED`` and hostname checks. Requests go through ``urllib``, which
uses ``http.client``. Tests patch ``open_request``; nothing in this module
retries a call (a retry could bill the provider twice).

API keys are sent as headers. Error text is passed through ``scrub`` so a
provider that echoes a key does not surface it.
"""

from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

import http.client

from app.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

_SSL_CONTEXT: ssl.SSLContext | None = None
DONE = object()


def ssl_context() -> ssl.SSLContext:
    """Verifying context. Certificate checks are not disabled."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        ctx = ssl.create_default_context()
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = True
        _SSL_CONTEXT = ctx
    return _SSL_CONTEXT


def open_request(req: urllib.request.Request, timeout: float):
    """Perform one HTTP request. Patched in tests — do not call the network from there."""
    if req.type == "https":
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl_context())
        )
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def scrub(text: str, secrets: list[str] | tuple[str, ...]) -> str:
    out = "" if text is None else str(text)
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 6:
            out = out.replace(secret, "[redacted]")
    return out


def build_request(method: str, url: str, headers: dict, body: dict | None):
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(url, data=data, headers=headers, method=method)


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After delta or HTTP-date. ``None`` if it does not parse."""
    if not value:
        return None
    text = str(value).strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _header(headers, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    if value is None:
        return None
    return str(value)


def _error_detail(body: str) -> str:
    text = (body or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text[:200]
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            message = err.get("message") or err.get("type") or ""
            return str(message)[:200]
        if isinstance(err, str):
            return err[:200]
        if data.get("message"):
            return str(data["message"])[:200]
    return ""


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw or "")


def _http_error(exc: urllib.error.HTTPError, *, provider: str, secrets: list[str]):
    status = getattr(exc, "code", None) or 0
    detail = scrub(_error_detail(_read_error_body(exc)), secrets)
    suffix = f": {detail}" if detail else ""
    if status in (401, 403):
        return ProviderAuthError(
            f"{provider}: authentication failed (HTTP {status}){suffix}",
            provider=provider,
            status=status,
        )
    if status == 429:
        raw = _header(exc.headers, "Retry-After")
        return ProviderRateLimitError(
            f"{provider}: rate limited (HTTP 429){suffix}",
            retry_after=parse_retry_after(raw),
            retry_after_raw=raw,
            provider=provider,
            status=429,
        )
    if status in (408, 504):
        return ProviderTimeoutError(
            f"{provider}: timed out (HTTP {status}){suffix}",
            provider=provider,
            status=status,
        )
    return ProviderError(
        f"{provider}: HTTP {status}{suffix}",
        provider=provider,
        status=status,
    )


def _wrap_network(exc: BaseException, *, provider: str, secrets: list[str]):
    if isinstance(exc, urllib.error.HTTPError):
        return _http_error(exc, provider=provider, secrets=secrets)
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return ProviderTimeoutError(f"{provider}: request timed out", provider=provider)
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return ProviderTimeoutError(f"{provider}: request timed out", provider=provider)
        return ProviderNetworkError(
            f"{provider}: network error ({type(reason).__name__})",
            provider=provider,
        )
    if isinstance(exc, (http.client.HTTPException, OSError)):
        return ProviderNetworkError(
            f"{provider}: network error ({type(exc).__name__})",
            provider=provider,
        )
    return None


def perform(req, timeout: float, *, provider: str, secrets: list[str]):
    try:
        return open_request(req, timeout=timeout)
    except Exception as exc:
        wrapped = _wrap_network(exc, provider=provider, secrets=secrets)
        if wrapped is not None:
            raise wrapped from None
        raise


def close_response(resp) -> None:
    close = getattr(resp, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:
        return


def request_json(req, timeout: float, *, provider: str, secrets: list[str]) -> dict:
    with perform(req, timeout, provider=provider, secrets=secrets) as resp:
        raw = resp.read()
    if isinstance(raw, str):
        text = raw
    else:
        text = bytes(raw or b"").decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ProviderError(f"{provider}: response was not JSON", provider=provider) from None
    if not isinstance(data, dict):
        raise ProviderError(f"{provider}: response JSON was not an object", provider=provider)
    return data


def iter_sse(resp):
    """Yield ``(event_name, data_string)`` for one Server-Sent Events body.

    A blank line ends an event. A ``data:`` line that starts a new event also
    flushes the previous one, so a stream that omits the blank line still
    parses. Comment lines (``:``) are ignored.
    """
    event_name = None
    data_lines: list[str] = []

    def flush():
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = None
            return None
        payload = "\n".join(data_lines)
        name = event_name
        event_name = None
        data_lines = []
        return name, payload

    for raw in resp:
        if isinstance(raw, bytes):
            line = raw.decode("utf-8", errors="replace")
        else:
            line = str(raw)
        line = line.rstrip("\r\n")
        if line == "":
            item = flush()
            if item is not None:
                yield item
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("data:"):
            if data_lines:
                item = flush()
                if item is not None:
                    yield item
            data_lines.append(line[5:].lstrip())
            continue
    item = flush()
    if item is not None:
        yield item


def iter_sse_json(resp):
    """Yield ``(event_name, object)``. ``data: [DONE]`` yields ``DONE`` and stops."""
    for name, data in iter_sse(resp):
        if data.strip() == "[DONE]":
            yield name, DONE
            return
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        yield name, parsed


def iter_ndjson(resp):
    """Yield JSON objects from an Ollama-style NDJSON body. Bad lines are skipped."""
    for raw in resp:
        if isinstance(raw, bytes):
            line = raw.decode("utf-8", errors="replace")
        else:
            line = str(raw)
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            yield parsed
