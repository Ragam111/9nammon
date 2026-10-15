"""Data model for a single point-in-time view of the machine.

A :class:`Snapshot` is a plain, serialisable record. The collector fills it in;
the analyzer reads it. Keeping it free of any psutil types means snapshots can
be stored, shipped over the communication layer, or fed to the AI engine
without the consumer needing psutil installed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class CpuMetrics:
    """CPU utilisation over the sampling window."""

    percent: float  # overall utilisation, 0-100
    per_core: list[float] = field(default_factory=list)
    logical_cores: int = 0
    physical_cores: Optional[int] = None
    # 1-minute load average normalised by core count (unix only; None on Windows)
    load_avg_1m: Optional[float] = None
    load_per_core: Optional[float] = None
    freq_mhz: Optional[float] = None


@dataclass
class MemoryMetrics:
    """Physical RAM and swap usage, in bytes unless noted."""

    total: int
    available: int
    used: int
    percent: float
    swap_total: int = 0
    swap_used: int = 0
    swap_percent: float = 0.0


@dataclass
class DiskUsage:
    """Capacity usage for one mounted filesystem."""

    mountpoint: str
    device: str
    fstype: str
    total: int
    used: int
    free: int
    percent: float
    # Read-only mounts (e.g. squashfs, mounted images) sit at 100% by design;
    # the analyzer must not mistake that for a capacity bottleneck.
    readonly: bool = False


@dataclass
class DiskIoMetrics:
    """Aggregate and busiest-disk I/O rates over the sampling window."""

    read_bytes_per_s: float = 0.0
    write_bytes_per_s: float = 0.0
    read_iops: float = 0.0
    write_iops: float = 0.0
    # Fraction of time the busiest disk spent servicing requests, 0-100.
    # Derived from busy_time; None when the platform does not report it.
    busiest_util_percent: Optional[float] = None
    busiest_device: Optional[str] = None


@dataclass
class NetworkMetrics:
    """Network throughput over the sampling window."""

    sent_bytes_per_s: float = 0.0
    recv_bytes_per_s: float = 0.0


@dataclass
class ProcessInfo:
    """A single process as seen during the window."""

    pid: int
    name: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_rss: int = 0


@dataclass
class Snapshot:
    """Everything the monitor captured in one sampling window."""

    timestamp: float
    interval: float
    hostname: str
    platform: str
    cpu: CpuMetrics
    memory: MemoryMetrics
    disks: list[DiskUsage] = field(default_factory=list)
    disk_io: DiskIoMetrics = field(default_factory=DiskIoMetrics)
    network: NetworkMetrics = field(default_factory=NetworkMetrics)
    top_by_cpu: list[ProcessInfo] = field(default_factory=list)
    top_by_memory: list[ProcessInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict (all nested dataclasses expanded)."""
        return asdict(self)
