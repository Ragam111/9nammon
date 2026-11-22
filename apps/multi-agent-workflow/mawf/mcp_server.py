"""Read-only MCP server over stdio for one local folder (JSON-RPC 2.0, newline-delimited).

Exposes exactly two tools: list_dir and read_file. Paths are confined by FileSandbox from mawf.files.
A name denylist hides secret-looking files and folders. Nothing is written, deleted or executed,
no port is opened, and stdout carries only protocol lines. Logs go to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .files import FileSandbox, SandboxError

SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "mawf-lca-files", "version": "0.1.0"}
MAX_LINE_BYTES = 256 * 1024
DEFAULT_MAX_BYTES = 200_000
BINARY_PROBE_BYTES = 8 * 1024
READ_EXTENSIONS = frozenset({".md", ".txt", ".csv", ".log", ".json", ".jsonl"})

# Denylist, matched case-insensitively against every path segment (requested and resolved).
DENIED_EXACT = frozenset({"config.json", "org.json", ".env", "localcodeassistant", "anthropic_api_key"})
DENIED_PREFIX = (".env",)
DENIED_SUFFIX = (".db", ".db-wal", ".db-shm", ".db-journal", ".pem", ".key", ".p12", ".pfx")
DENIED_PART = ("secret", "token", "password", "apikey", "api_key")

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_dir",
        "description": "List one folder under the root. Returns sorted entries with name, type and size for files.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Folder relative to the root. Empty or '.' is the root."}},
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read one text file under the root (.md .txt .csv .log .json .jsonl). Long files are cut and marked truncated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File relative to the root."},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": DEFAULT_MAX_BYTES, "default": DEFAULT_MAX_BYTES},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
]


class RpcError(Exception):
    """A JSON-RPC protocol error. The reply carries this code and message."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolError(Exception):
    """A tool-level failure. It becomes a result with isError true, never a JSON-RPC error."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def is_denied_name(name: str) -> bool:
    """True when one path segment matches the denylist.

    A colon is always refused. Windows allows it only for drives and NTFS alternate data
    streams ("config.json:x.md"), and a stream would otherwise hide the base name from the check.
    """
    low = name.lower()
    if ":" in low:
        return True
    return (
        low in DENIED_EXACT
        or low.startswith(DENIED_PREFIX)
        or low.endswith(DENIED_SUFFIX)
        or any(part in low for part in DENIED_PART)
    )


def _is_hard_linked(path: Path) -> bool:
    """A file with more than one directory entry may alias content outside the root. Refuse it."""
    return path.stat().st_nlink > 1


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_result(text: str, is_error: bool) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _valid_id(value: Any) -> bool:
    if value is None or isinstance(value, str):
        return True
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_object(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise RpcError(-32602, "params must be an object")
    return params


def _required_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise RpcError(-32602, f"{key} is required and must be a string")
    return value


def _max_bytes(args: dict[str, Any]) -> int:
    value = args.get("max_bytes", DEFAULT_MAX_BYTES)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= DEFAULT_MAX_BYTES:
        raise RpcError(-32602, f"max_bytes must be an integer from 1 to {DEFAULT_MAX_BYTES}")
    return value


def _decode(data: bytes, truncated: bool) -> str:
    """Decode UTF-8. When cut, drop up to 3 trailing bytes that split a character."""
    cuts = range(4) if truncated else range(1)
    for cut in cuts:
        if cut > len(data):
            break
        try:
            return data[: len(data) - cut].decode("utf-8")
        except UnicodeDecodeError:
            continue
    raise ToolError("not UTF-8 text")


class McpServer:
    """Protocol state for one server. handle_message returns the reply dict, or None for no reply."""

    def __init__(self, sandbox: FileSandbox) -> None:
        self.sandbox = sandbox

    def handle_message(self, line: str) -> dict[str, Any] | None:
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            return _error(None, -32600, "request too large")
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError):
            return _error(None, -32700, "parse error")
        return self._dispatch(msg)

    def _dispatch(self, msg: Any) -> dict[str, Any] | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _error(None, -32600, "invalid request")
        if "id" not in msg:
            return None  # notifications never get a reply
        req_id = msg["id"]
        if not _valid_id(req_id):
            return _error(None, -32600, "invalid id")
        try:
            result = self._route(msg["method"], msg.get("params", {}))
        except RpcError as exc:
            return _error(req_id, exc.code, exc.message)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _route(self, method: str, params: Any) -> dict[str, Any]:
        if method == "notifications/initialized" or method.startswith("notifications/"):
            return {}
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self._call(params)
        raise RpcError(-32601, "method not found")

    def _initialize(self, params: Any) -> dict[str, Any]:
        version = _require_object(params).get("protocolVersion")
        if not isinstance(version, str):
            raise RpcError(-32602, "protocolVersion must be a string")
        chosen = version if version in SUPPORTED else SUPPORTED[0]
        return {"protocolVersion": chosen, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}

    def _call(self, params: Any) -> dict[str, Any]:
        body = _require_object(params)
        name = body.get("name")
        if not isinstance(name, str):
            raise RpcError(-32602, "name must be a string")
        arguments = body.get("arguments", {})
        if not isinstance(arguments, dict):
            raise RpcError(-32602, "arguments must be an object")
        handlers = {"list_dir": self._list_dir, "read_file": self._read_file}
        if name not in handlers:
            return _tool_result("unknown tool", True)
        try:
            payload = handlers[name](arguments)
        except ToolError as exc:
            return _tool_result(exc.reason, True)
        except OSError:
            return _tool_result("read failed", True)
        return _tool_result(json.dumps(payload), False)

    def _check(self, rel: str) -> Path:
        """Refuse denied names, then resolve inside the root. Returns the real path."""
        if any(is_denied_name(part) for part in Path(rel).parts):
            raise ToolError("denied")
        try:
            target = self.sandbox.resolve(rel)
        except SandboxError:
            raise ToolError("invalid path or outside root") from None
        if any(is_denied_name(part) for part in target.relative_to(self.sandbox.root).parts):
            raise ToolError("denied")
        return target

    def _rel(self, target: Path) -> str:
        return target.relative_to(self.sandbox.root).as_posix()

    def _read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = _required_str(args, "path")
        max_bytes = _max_bytes(args)
        target = self._check(rel)
        if target.suffix.lower() not in READ_EXTENSIONS:
            raise ToolError("extension not allowed")
        if target.is_dir():
            raise ToolError("not a file")
        if not target.is_file():
            raise ToolError("not found")
        if _is_hard_linked(target):
            raise ToolError("denied")
        with target.open("rb") as handle:
            # Check the link count on the opened handle: a link created after the path check
            # above would otherwise be read as outside content (time-of-check to time-of-use).
            if os.fstat(handle.fileno()).st_nlink > 1:
                raise ToolError("denied")
            head = handle.read(max_bytes + 1)
        if b"\x00" in head[:BINARY_PROBE_BYTES]:
            raise ToolError("binary file refused")
        truncated = len(head) > max_bytes
        text = _decode(head[:max_bytes], truncated)
        return {"path": self._rel(target), "text": text, "truncated": truncated}

    def _list_dir(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = args.get("path", "")
        if not isinstance(rel, str):
            raise RpcError(-32602, "path must be a string")
        base = self._check(rel or ".")
        if not base.is_dir():
            raise ToolError("not a directory")
        entries: list[dict[str, Any]] = []
        for child in sorted(base.iterdir(), key=lambda p: p.name):
            if is_denied_name(child.name):
                continue
            try:
                target = self._check(child.relative_to(self.sandbox.root).as_posix())
            except ToolError:
                continue  # denied or escaping entries are hidden completely
            if target.is_dir():
                entries.append({"name": child.name, "type": "dir"})
            elif target.is_file() and not _is_hard_linked(target):
                entries.append({"name": child.name, "type": "file", "size": target.stat().st_size})
        return {"path": self._rel(base), "entries": entries}


def _reply_for_bytes(server: McpServer, raw: bytes) -> dict[str, Any] | None:
    line = raw.rstrip(b"\r\n")
    if not line.strip():
        return None
    if len(line) > MAX_LINE_BYTES:
        return _error(None, -32600, "request too large")
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return _error(None, -32700, "parse error")
    return server.handle_message(text)


def parse_args(argv: Sequence[str] | None) -> Path:
    parser = argparse.ArgumentParser(prog="mawf.mcp_server", description="Read-only MCP server for one folder.")
    parser.add_argument("--root", required=True, help="existing folder to expose, read-only")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        parser.error("--root must be an existing directory")
    return root.resolve()


def main(argv: Sequence[str] | None = None) -> int:
    root = parse_args(argv)
    server = McpServer(FileSandbox(root))
    print("mawf-lca-files: serving one folder, read-only", file=sys.stderr, flush=True)
    for raw in sys.stdin.buffer:
        reply = _reply_for_bytes(server, raw)
        if reply is not None:
            sys.stdout.buffer.write((json.dumps(reply) + "\n").encode("ascii"))
            sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
