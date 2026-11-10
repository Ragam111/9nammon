"""Placeholders for work this machine should not load yet.

RAG / a vector database and an MCP server are out of scope. The classes exist
so callers can depend on a stable name. Every method raises NotImplementedError.
They do not allocate an index and they do not bind a port.
"""

from __future__ import annotations

__all__ = ["McpEndpoint", "RagIndex"]

_RAG = "RAG/vector DB is not enabled (8GB RAM budget)"
_MCP = "MCP server is not enabled (no extra process)"


class RagIndex:
    def add(self, doc_id: str, text: str) -> None:
        raise NotImplementedError(_RAG)

    def query(self, text: str, k: int = 3) -> list:
        raise NotImplementedError(_RAG)


class McpEndpoint:
    def list_tools(self) -> list:
        raise NotImplementedError(_MCP)

    def call_tool(self, name: str, arguments: dict) -> dict:
        raise NotImplementedError(_MCP)
