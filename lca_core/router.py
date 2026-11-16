"""L5 — port registry for 8420 (worker) and 8421 (dashboard).

Probes are injected. This module does not bind a socket and does not start a server.
``tcp_probe`` is a client connect helper for the gateway to call explicitly.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Callable

from lca_core.constants import DASHBOARD_PORT, PROBE_TIMEOUT_S, WORKER_PORT

Probe = Callable[[str, int, float], dict]

__all__ = [
    "NodeSpec",
    "cluster_status",
    "default_registry",
    "probe_node",
    "tcp_probe",
]


@dataclass(frozen=True)
class NodeSpec:
    port: int
    role: str
    primary: str = "127.0.0.1"
    fallback: str = "localhost"


def default_registry() -> tuple[NodeSpec, ...]:
    return (
        NodeSpec(port=WORKER_PORT, role="worker"),
        NodeSpec(port=DASHBOARD_PORT, role="dashboard"),
    )


def tcp_probe(host: str, port: int, timeout: float) -> dict:
    """One outbound connect, then close. Does not listen.

    The gateway should run this inside the shared executor so the HTTP thread
    is not blocked on port 8420. Tests pass their own probe and never call this.
    """
    started = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            pass
    except OSError:
        return {"status": "down", "latency_ms": None}
    elapsed = int((time.perf_counter() - started) * 1000)
    return {"status": "up", "latency_ms": elapsed}


def _normalize(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {"status": "down", "latency_ms": None}
    status = result.get("status")
    if status not in ("up", "down", "not_implemented"):
        status = "down"
    latency = result.get("latency_ms")
    if status != "up":
        latency_out = None if latency is None else _as_int(latency)
        if status == "down":
            latency_out = None
        return {"status": status, "latency_ms": latency_out}
    return {"status": "up", "latency_ms": 0 if latency is None else _as_int(latency)}


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def probe_node(spec: NodeSpec, probe: Probe, timeout: float = PROBE_TIMEOUT_S) -> dict:
    """Try the primary host, then the fallback host.

    ``up`` and ``not_implemented`` are final answers from a live peer.
    A connection error or ``down`` tries the fallback host once.
    """
    last = {"status": "down", "latency_ms": None}
    for host in (spec.primary, spec.fallback):
        try:
            raw = probe(host, spec.port, timeout)
        except Exception:
            last = {"status": "down", "latency_ms": None}
            continue
        last = _normalize(raw)
        if last["status"] in ("up", "not_implemented"):
            break
    return {
        "port": spec.port,
        "role": spec.role,
        "status": last["status"],
        "latency_ms": last["latency_ms"],
    }


def cluster_status(
    probe: Probe,
    *,
    registry: tuple[NodeSpec, ...] | None = None,
    executor=None,
    timeout: float = PROBE_TIMEOUT_S,
) -> dict:
    """Body of ``GET /api/cluster/status``. ``probe`` is required so import is idle.

    Pass the shared executor (max_workers=2) so each probe runs off the HTTP thread.
    """
    specs = registry if registry is not None else default_registry()
    if executor is None:
        nodes = [probe_node(spec, probe, timeout) for spec in specs]
    else:
        futures = [executor.submit(probe_node, spec, probe, timeout) for spec in specs]
        nodes = [item.result() for item in futures]
    return {"nodes": nodes}
