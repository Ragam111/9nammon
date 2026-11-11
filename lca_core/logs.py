"""L2 — rotating file logs, a JSON audit log, an error counter, 32KB tail reads.

The audit file is the source for ``/api/logs/stream``. Text is stored as plain text.
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from lca_core.constants import CHUNK_BYTES, LOG_BACKUPS, LOG_MAX_BYTES

__all__ = [
    "AuditLog",
    "LogOffline",
    "close_log",
    "format_sse",
    "iter_sse_chunks",
    "iter_tail_chunks",
    "open_log",
    "tail_records",
]


class LogOffline(Exception):
    def __init__(self, detail: str = "database locked"):
        super().__init__(detail)
        self.detail = detail


def open_log(
    path: Path,
    *,
    name: str | None = None,
    max_bytes: int = LOG_MAX_BYTES,
    backup_count: int = LOG_BACKUPS,
) -> logging.Logger:
    """Attach one RotatingFileHandler. Caps default to 256KiB x 2 backups."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    logger_name = name or f"lca_core.file.{path.resolve()}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    close_log(logger)
    handler = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def close_log(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


class AuditLog:
    """JSON lines on a rotating file, plus a process-local error counter."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = LOG_MAX_BYTES,
        backup_count: int = LOG_BACKUPS,
    ):
        self.path = Path(path)
        self.error_count = 0
        self._next_id = 1
        self._logger = open_log(
            self.path,
            name=f"lca_core.audit.{id(self)}",
            max_bytes=max_bytes,
            backup_count=backup_count,
        )

    def write(self, level: str, text: str, *, ts: str | None = None) -> dict:
        level_name = (level or "info").strip().lower()
        record = {
            "id": self._next_id,
            "ts": ts or _now_iso(),
            "level": level_name,
            "text": "" if text is None else str(text),
        }
        self._next_id += 1
        if level_name == "error":
            self.error_count += 1
        self._logger.info(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        for handler in self._logger.handlers:
            handler.flush()
        return record

    def close(self) -> None:
        close_log(self._logger)


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def iter_tail_chunks(
    path: Path,
    *,
    chunk_size: int = CHUNK_BYTES,
    max_bytes: int = LOG_MAX_BYTES,
):
    """Yield at most ``chunk_size`` bytes per read, from the tail of the file."""
    if chunk_size < 1 or chunk_size > CHUNK_BYTES:
        raise ValueError("chunk_size must be 1..32768")
    path = Path(path)
    try:
        size = path.stat().st_size
        start = 0 if max_bytes is None else max(0, size - max(0, int(max_bytes)))
        with path.open("rb") as handle:
            handle.seek(start)
            while True:
                block = handle.read(chunk_size)
                if not block:
                    break
                if len(block) > chunk_size:
                    raise RuntimeError("read exceeded chunk cap")
                yield block
    except OSError as exc:
        raise LogOffline("database locked") from exc


def tail_records(
    path: Path,
    *,
    limit: int = 100,
    chunk_size: int = CHUNK_BYTES,
    max_bytes: int = LOG_MAX_BYTES,
) -> list[dict]:
    """Parse JSON audit lines from a bounded tail. Missing file returns []."""
    path = Path(path)
    if not path.exists():
        return []
    raw = b"".join(iter_tail_chunks(path, chunk_size=chunk_size, max_bytes=max_bytes))
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # A bounded tail can start mid-line. Drop the first fragment when we did not
    # read the whole file and the fragment is not valid JSON.
    records: list[dict] = []
    for index, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            if index == 0:
                continue
            continue
        if not isinstance(item, dict):
            continue
        records.append(_public_record(item))
    if limit is not None and limit >= 0:
        records = records[-int(limit):]
    return records


def _public_record(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "ts": item.get("ts"),
        "level": item.get("level"),
        "text": item.get("text") if isinstance(item.get("text"), str) else str(item.get("text") or ""),
    }


def format_sse(record: dict) -> bytes:
    data = json.dumps(
        {
            "id": record.get("id"),
            "ts": record.get("ts"),
            "level": record.get("level"),
            "text": record.get("text") if isinstance(record.get("text"), str) else str(record.get("text") or ""),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: log\ndata: {data}\n\n".encode("utf-8")


def iter_sse_chunks(records, *, chunk_size: int = CHUNK_BYTES):
    """Yield socket writes that are each at most 32KB."""
    if chunk_size < 1 or chunk_size > CHUNK_BYTES:
        raise ValueError("chunk_size must be 1..32768")
    buf = bytearray()
    for record in records:
        payload = format_sse(record)
        offset = 0
        while offset < len(payload):
            room = chunk_size - len(buf)
            take = payload[offset:offset + room]
            buf.extend(take)
            offset += len(take)
            if len(buf) == chunk_size:
                yield bytes(buf)
                buf.clear()
    if buf:
        yield bytes(buf)
