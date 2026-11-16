"""Role registry. Config only — no sockets, no bots, no brokers.

Each entry maps a local role name to the modules that implement its duty.
``network`` is always false.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ROLES", "Role", "as_config", "get_role"]


@dataclass(frozen=True)
class Role:
    key: str
    title: str
    duty: str
    modules: tuple[str, ...]
    handlers: tuple[str, ...]
    notes: str


ROLES: dict[str, Role] = {
    "9arm_manager": Role(
        key="9arm_manager",
        title="9arm Manager",
        duty="orchestrator/governor",
        modules=("lca_core.loop", "lca_core.executor"),
        handlers=("lca_core.loop:run_loop",),
        notes="loop metrics and hard stops; does not call out",
    ),
    "new_bot": Role(
        key="new_bot",
        title="New Bot",
        duty="plugins/experimental extensions",
        modules=("lca_core.stubs",),
        handlers=("lca_core.stubs:RagIndex",),
        notes="experimental hooks stay in-process; RAG and MCP stay stubs",
    ),
    "uol_bot": Role(
        key="uol_bot",
        title="UOL Bot",
        duty="sessions + SSE/WebSocket telemetry",
        modules=("lca_core.logs", "lca_core.bus", "lca_core.routes"),
        handlers=("lca_core.routes:dispatch",),
        notes="local session view and /api/logs/stream only",
    ),
    "q_botdata": Role(
        key="q_botdata",
        title="Q Botdata",
        duty="SQLite/WAL/indexing",
        modules=("lca_core.storage",),
        handlers=("lca_core.storage:connect",),
        notes="WAL database files this package created; no remote index",
    ),
    "amd_bot": Role(
        key="amd_bot",
        title="AMD Bot",
        duty="CPU/thread pool",
        modules=("lca_core.executor",),
        handlers=("lca_core.executor:get_executor",),
        notes="shared pool is fixed at 2 workers",
    ),
    "ulo_bot": Role(
        key="ulo_bot",
        title="ULO Bot",
        duty="local file sync + workspace integrity",
        modules=("lca_core.storage",),
        handlers=("lca_core.storage:session",),
        notes="local files only; no remote sync client",
    ),
    "moon_bot": Role(
        key="moon_bot",
        title="Moon Bot",
        duty="background jobs/GC/idle health checks",
        modules=("lca_core.executor", "lca_core.router"),
        handlers=("lca_core.executor:GcHook",),
        notes="gc hook and port probe are caller-driven; no extra process",
    ),
    "bot_trading": Role(
        key="bot_trading",
        title="Bot trading",
        duty="API transaction loops + execution logging",
        modules=("lca_core.loop", "lca_core.logs"),
        handlers=("lca_core.logs:AuditLog",),
        notes="local execution log only; does not submit orders or call a broker",
    ),
}


def get_role(key: str) -> Role:
    return ROLES[key]


def as_config() -> dict:
    """JSON-ready mapping. Safe to log. Contains no URLs and no credentials."""
    return {
        role.key: {
            "title": role.title,
            "duty": role.duty,
            "modules": list(role.modules),
            "handlers": list(role.handlers),
            "notes": role.notes,
            "network": False,
        }
        for role in ROLES.values()
    }
