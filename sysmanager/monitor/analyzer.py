"""Turn a :class:`Snapshot` into a diagnosis.

This is the part that answers the real question: *are we slow because of RAM,
CPU, or disk I/O?* It is deliberately rule-based and transparent so a human (or
the AI engine) can see exactly why each conclusion was reached. The optimizer
will later consume the same :class:`Finding` list to decide what to tune.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from .snapshot import Snapshot
from .thresholds import Thresholds


class Severity(IntEnum):
    OK = 0
    INFO = 1
    WARNING = 2
    CRITICAL = 3

    @property
    def label(self) -> str:
        return self.name


# Resources ordered by how strongly they usually explain "the machine feels
# slow", used to break ties when two resources share the top severity.
_BOTTLENECK_PRIORITY = ["MEMORY", "DISK_IO", "CPU", "SWAP", "DISK", "NETWORK"]


@dataclass
class Finding:
    """One observation about one resource."""

    resource: str  # CPU / MEMORY / SWAP / DISK / DISK_IO / NETWORK
    severity: Severity
    value: float
    message: str
    suggestion: str = ""

    def __str__(self) -> str:
        tail = f"  ->  {self.suggestion}" if self.suggestion else ""
        return f"[{self.severity.label:8}] {self.resource:8} {self.message}{tail}"


@dataclass
class Report:
    """The full diagnosis for one snapshot."""

    snapshot: Snapshot
    findings: list[Finding] = field(default_factory=list)

    @property
    def worst(self) -> Severity:
        return max((f.severity for f in self.findings), default=Severity.OK)

    @property
    def primary_bottleneck(self) -> Optional[Finding]:
        """The finding that best explains current slowness, if any."""
        candidates = [f for f in self.findings if f.severity >= Severity.WARNING]
        if not candidates:
            return None
        worst = max(f.severity for f in candidates)
        tied = [f for f in candidates if f.severity == worst]
        tied.sort(key=lambda f: _priority_rank(f.resource))
        return tied[0]

    @property
    def verdict(self) -> str:
        bottleneck = self.primary_bottleneck
        if bottleneck is None:
            if self.worst == Severity.OK:
                return "System healthy — no resource under pressure."
            return "System nominal — minor notices only, no bottleneck."
        return (
            f"Primary bottleneck: {bottleneck.resource} "
            f"({bottleneck.severity.label}). {bottleneck.suggestion}"
        )


def _priority_rank(resource: str) -> int:
    try:
        return _BOTTLENECK_PRIORITY.index(resource)
    except ValueError:
        return len(_BOTTLENECK_PRIORITY)


def _level(value: float, warn: float, crit: float) -> Severity:
    if value >= crit:
        return Severity.CRITICAL
    if value >= warn:
        return Severity.WARNING
    return Severity.OK


def _fmt_bytes(n: float) -> str:
    step = 1024.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < step:
            return f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} PiB"


class Analyzer:
    def __init__(self, thresholds: Optional[Thresholds] = None) -> None:
        self.thresholds = thresholds or Thresholds()
        self.thresholds.validate()

    def analyze(self, snap: Snapshot) -> Report:
        findings: list[Finding] = []
        findings.extend(self._cpu(snap))
        findings.append(self._memory(snap))
        swap = self._swap(snap)
        if swap is not None:
            findings.append(swap)
        findings.extend(self._disks(snap))
        io = self._disk_io(snap)
        if io is not None:
            findings.append(io)
        return Report(snapshot=snap, findings=findings)

    # -- per-resource rules --------------------------------------------------

    def _cpu(self, snap: Snapshot) -> list[Finding]:
        t = self.thresholds
        c = snap.cpu
        out: list[Finding] = []

        sev = _level(c.percent, t.cpu_warn, t.cpu_crit)
        busy_cores = sum(1 for v in c.per_core if v >= t.cpu_warn)
        if sev >= Severity.WARNING:
            msg = f"CPU at {c.percent:.0f}% ({busy_cores}/{c.logical_cores} cores saturated)"
            sug = (
                "A single workload may be CPU-bound; check top-by-CPU processes "
                "and consider parallelising or scheduling off-peak."
            )
        else:
            msg = f"CPU at {c.percent:.0f}% across {c.logical_cores} cores"
            sug = ""
        out.append(Finding("CPU", sev, c.percent, msg, sug))

        # Load average catches sustained run-queue backlog that a single
        # instantaneous CPU% can miss (unix only).
        if c.load_per_core is not None:
            lsev = _level(c.load_per_core, t.load_per_core_warn, t.load_per_core_crit)
            if lsev >= Severity.WARNING:
                out.append(
                    Finding(
                        "CPU",
                        lsev,
                        c.load_per_core,
                        f"Load average {c.load_avg_1m:.2f} = {c.load_per_core:.2f}x "
                        f"per core — more runnable work than cores",
                        "Run queue is backed up; reduce concurrency or add cores.",
                    )
                )
        return out

    def _memory(self, snap: Snapshot) -> Finding:
        t = self.thresholds
        m = snap.memory
        sev = _level(m.percent, t.mem_warn, t.mem_crit)
        avail = _fmt_bytes(m.available)
        if sev >= Severity.WARNING:
            msg = f"RAM at {m.percent:.0f}% — only {avail} free"
            sug = (
                "Low headroom causes paging and slowdowns; close memory-heavy "
                "processes (see top-by-memory) or add RAM."
            )
        else:
            msg = f"RAM at {m.percent:.0f}% — {avail} free"
            sug = ""
        return Finding("MEMORY", sev, m.percent, msg, sug)

    def _swap(self, snap: Snapshot) -> Optional[Finding]:
        t = self.thresholds
        m = snap.memory
        if m.swap_total == 0:
            return None
        sev = _level(m.swap_percent, t.swap_warn, t.swap_crit)
        if sev == Severity.OK:
            return None
        return Finding(
            "SWAP",
            sev,
            m.swap_percent,
            f"Swap at {m.swap_percent:.0f}% ({_fmt_bytes(m.swap_used)} used)",
            "Active swapping means RAM pressure — this is often the real cause "
            "of disk thrashing and lag. Treat as a memory shortage.",
        )

    def _disks(self, snap: Snapshot) -> list[Finding]:
        t = self.thresholds
        out: list[Finding] = []
        for d in snap.disks:
            # Read-only mounts (squashfs, mounted images) are full by design —
            # a write bottleneck is impossible, so never raise one.
            if d.readonly:
                continue
            sev = _level(d.percent, t.disk_warn, t.disk_crit)
            if sev == Severity.OK:
                continue
            out.append(
                Finding(
                    "DISK",
                    sev,
                    d.percent,
                    f"{d.mountpoint} at {d.percent:.0f}% "
                    f"({_fmt_bytes(d.free)} free of {_fmt_bytes(d.total)})",
                    "Low free space degrades writes and can halt services; "
                    "clean up or expand this volume.",
                )
            )
        return out

    def _disk_io(self, snap: Snapshot) -> Optional[Finding]:
        t = self.thresholds
        io = snap.disk_io
        rate = _fmt_bytes(io.read_bytes_per_s + io.write_bytes_per_s) + "/s"
        if io.busiest_util_percent is None:
            # Platform gave no busy_time; report throughput as context only.
            return Finding(
                "DISK_IO",
                Severity.INFO,
                io.read_bytes_per_s + io.write_bytes_per_s,
                f"Disk I/O {rate} (utilisation not reported on this platform)",
            )
        sev = _level(io.busiest_util_percent, t.disk_io_warn, t.disk_io_crit)
        dev = io.busiest_device or "disk"
        if sev >= Severity.WARNING:
            msg = f"{dev} busy {io.busiest_util_percent:.0f}% of the time ({rate})"
            sug = (
                "Disk is the bottleneck — requests are queueing on storage. "
                "Reduce I/O, add caching, or move hot data to a faster disk."
            )
        else:
            msg = f"{dev} busy {io.busiest_util_percent:.0f}% of the time ({rate})"
            sug = ""
        return Finding("DISK_IO", sev, io.busiest_util_percent, msg, sug)
