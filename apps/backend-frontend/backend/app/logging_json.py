"""Structured JSON logs, one object per line on stdout. Sensitive fields are dropped, never logged."""

from __future__ import annotations

import json
import sys
import time
from typing import Any, TextIO

# Never written, whatever a caller passes.
FORBIDDEN_FIELDS = frozenset({"prompt", "output", "api_key", "key", "password", "authorization", "cookie", "token"})


def log_event(event: str, stream: TextIO | None = None, **fields: Any) -> dict[str, Any]:
    """Write one JSON log line and return the record that was written."""
    record: dict[str, Any] = {"ts": round(time.time(), 3), "event": event}
    for name, value in fields.items():
        if name.lower() in FORBIDDEN_FIELDS or value is None:
            continue
        record[name] = value
    out = stream or sys.stdout
    out.write(json.dumps(record, ensure_ascii=False) + "\n")
    out.flush()
    return record


def estimate_cost(tokens: int, cost_per_1k: float) -> float:
    """Approximate cost in the currency of COST_PER_1K_TOKENS."""
    return round(tokens / 1000 * cost_per_1k, 6)
