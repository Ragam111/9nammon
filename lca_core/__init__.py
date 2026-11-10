"""Importable pieces for Nammon's localhost dashboard gateway.

Importing this package does not bind a port, start a thread pool, or contact
Ollama. CodexGPT wires the helpers into ``app_server.py`` on the PC.
That file is not part of this package. Product VERSION stays in ``VERSION``.
"""

from __future__ import annotations

from lca_core.bus import EventBus
from lca_core.constants import CHUNK_BYTES, DASHBOARD_PORT, WORKER_PORT
from lca_core.executor import GcHook, get_executor, shutdown_executor
from lca_core.inference import OllamaClient
from lca_core.loop import run_loop
from lca_core.roles import ROLES, as_config
from lca_core.routes import GatewayContext, dispatch
from lca_core.stubs import McpEndpoint, RagIndex

__all__ = [
    "CHUNK_BYTES",
    "DASHBOARD_PORT",
    "EventBus",
    "GATEWAY_ROUTES",
    "GcHook",
    "GatewayContext",
    "McpEndpoint",
    "OllamaClient",
    "ROLES",
    "RagIndex",
    "WORKER_PORT",
    "as_config",
    "dispatch",
    "get_executor",
    "run_loop",
    "shutdown_executor",
]

GATEWAY_ROUTES = ("/auth/google", "/api/cluster/status", "/api/logs/stream")
