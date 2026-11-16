"""Collect a :class:`Snapshot` using psutil.

The collector takes a *sampling window* (``interval`` seconds). Rate-based
metrics — CPU %, disk I/O, network, per-process CPU — are measured by diffing
counters across that window, so a longer interval gives steadier numbers.
"""

from __future__ import annotations

import platform
import socket
import time
from typing import Optional

from .snapshot import (
    CpuMetrics,
    DiskIoMetrics,
    DiskUsage,
    MemoryMetrics,
    NetworkMetrics,
    ProcessInfo,
    Snapshot,
)

try:
    import psutil
except ImportError as exc:  # pragma: no cover - exercised only without psutil
    raise ImportError(
        "psutil is required for the performance monitor. "
        "Install it with:  pip install psutil"
    ) from exc


class Collector:
    """Samples the machine. Reusable across windows (keeps no counter state)."""

    def __init__(self, top_n: int = 5) -> None:
        self.top_n = top_n

    def collect(self, interval: float = 1.0) -> Snapshot:
        """Capture one snapshot over ``interval`` seconds (blocks that long)."""
        if interval <= 0:
            raise ValueError("interval must be > 0")

        # --- counters at the start of the window ---------------------------
        disk_io_start = psutil.disk_io_counters(perdisk=True) or {}
        net_start = psutil.net_io_counters()
        # Prime per-process CPU counters; the first call always reads 0.
        procs = self._prime_processes()

        # cpu_percent(interval=...) blocks for the whole window and doubles as
        # our timer, so disk/net deltas below are measured over the same span.
        per_core = psutil.cpu_percent(interval=interval, percpu=True)
        wall = interval

        # --- counters at the end of the window -----------------------------
        disk_io_end = psutil.disk_io_counters(perdisk=True) or {}
        net_end = psutil.net_io_counters()

        cpu = self._cpu_metrics(per_core)
        memory = self._memory_metrics()
        disks = self._disk_usage()
        disk_io = self._disk_io_metrics(disk_io_start, disk_io_end, wall)
        network = self._network_metrics(net_start, net_end, wall)
        top_by_cpu, top_by_memory = self._top_processes(procs)

        return Snapshot(
            timestamp=time.time(),
            interval=wall,
            hostname=socket.gethostname(),
            platform=platform.platform(),
            cpu=cpu,
            memory=memory,
            disks=disks,
            disk_io=disk_io,
            network=network,
            top_by_cpu=top_by_cpu,
            top_by_memory=top_by_memory,
        )

    # -- individual metric helpers ------------------------------------------

    @staticmethod
    def _cpu_metrics(per_core: list[float]) -> CpuMetrics:
        overall = sum(per_core) / len(per_core) if per_core else 0.0
        logical = psutil.cpu_count(logical=True) or len(per_core)
        physical = psutil.cpu_count(logical=False)

        load_1m = load_per_core = None
        getloadavg = getattr(psutil, "getloadavg", None)
        if getloadavg is not None:
            try:
                load_1m = getloadavg()[0]
                if logical:
                    load_per_core = load_1m / logical
            except (OSError, RuntimeError):
                load_1m = load_per_core = None

        freq_mhz = None
        try:
            freq = psutil.cpu_freq()
            if freq is not None:
                freq_mhz = freq.current
        except (NotImplementedError, OSError, AttributeError):
            freq_mhz = None

        return CpuMetrics(
            percent=round(overall, 1),
            per_core=[round(c, 1) for c in per_core],
            logical_cores=logical,
            physical_cores=physical,
            load_avg_1m=round(load_1m, 2) if load_1m is not None else None,
            load_per_core=round(load_per_core, 2) if load_per_core is not None else None,
            freq_mhz=round(freq_mhz, 0) if freq_mhz is not None else None,
        )

    @staticmethod
    def _memory_metrics() -> MemoryMetrics:
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return MemoryMetrics(
            total=vm.total,
            available=vm.available,
            used=vm.total - vm.available,
            percent=vm.percent,
            swap_total=sw.total,
            swap_used=sw.used,
            swap_percent=sw.percent,
        )

    @staticmethod
    def _disk_usage() -> list[DiskUsage]:
        disks: list[DiskUsage] = []
        seen: set[str] = set()
        for part in psutil.disk_partitions(all=False):
            if part.mountpoint in seen:
                continue
            seen.add(part.mountpoint)
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue  # e.g. empty CD-ROM drive on Windows
            opts = part.opts or ""
            readonly = "ro" in opts.split(",")
            disks.append(
                DiskUsage(
                    mountpoint=part.mountpoint,
                    device=part.device,
                    fstype=part.fstype,
                    total=usage.total,
                    used=usage.used,
                    free=usage.free,
                    percent=usage.percent,
                    readonly=readonly,
                )
            )
        return disks

    @staticmethod
    def _disk_io_metrics(start: dict, end: dict, wall: float) -> DiskIoMetrics:
        read_bytes = write_bytes = read_count = write_count = 0
        busiest_util: Optional[float] = None
        busiest_dev: Optional[str] = None

        for dev, e in end.items():
            s = start.get(dev)
            if s is None:
                continue
            read_bytes += e.read_bytes - s.read_bytes
            write_bytes += e.write_bytes - s.write_bytes
            read_count += e.read_count - s.read_count
            write_count += e.write_count - s.write_count

            # busy_time is in ms; fraction of the window the disk was busy.
            busy_s = getattr(e, "busy_time", None)
            busy_e = getattr(s, "busy_time", None)
            if busy_s is not None and busy_e is not None:
                util = (e.busy_time - s.busy_time) / (wall * 1000.0) * 100.0
                util = max(0.0, min(util, 100.0))
                if busiest_util is None or util > busiest_util:
                    busiest_util = util
                    busiest_dev = dev

        return DiskIoMetrics(
            read_bytes_per_s=read_bytes / wall,
            write_bytes_per_s=write_bytes / wall,
            read_iops=read_count / wall,
            write_iops=write_count / wall,
            busiest_util_percent=round(busiest_util, 1) if busiest_util is not None else None,
            busiest_device=busiest_dev,
        )

    @staticmethod
    def _network_metrics(start, end, wall: float) -> NetworkMetrics:
        return NetworkMetrics(
            sent_bytes_per_s=(end.bytes_sent - start.bytes_sent) / wall,
            recv_bytes_per_s=(end.bytes_recv - start.bytes_recv) / wall,
        )

    @staticmethod
    def _prime_processes() -> list:
        procs = []
        for p in psutil.process_iter(["pid", "name"]):
            try:
                p.cpu_percent(None)  # prime; returns 0 on first call
                procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs

    def _top_processes(self, procs: list) -> tuple[list[ProcessInfo], list[ProcessInfo]]:
        infos: list[ProcessInfo] = []
        ncpu = psutil.cpu_count(logical=True) or 1
        for p in procs:
            try:
                # cpu_percent here is cumulative across all cores; normalise to
                # a 0-100 whole-machine scale so it lines up with CpuMetrics.
                raw_cpu = p.cpu_percent(None)
                mem_pct = p.memory_percent()
                rss = p.memory_info().rss
                name = p.info.get("name") or f"pid {p.pid}"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            infos.append(
                ProcessInfo(
                    pid=p.pid,
                    name=name,
                    cpu_percent=round(raw_cpu / ncpu, 1),
                    memory_percent=round(mem_pct, 1),
                    memory_rss=rss,
                )
            )

        top_cpu = sorted(infos, key=lambda i: i.cpu_percent, reverse=True)[: self.top_n]
        top_mem = sorted(infos, key=lambda i: i.memory_rss, reverse=True)[: self.top_n]
        return top_cpu, top_mem


def collect(interval: float = 1.0, top_n: int = 5) -> Snapshot:
    """Convenience: one-shot snapshot without managing a Collector instance."""
    return Collector(top_n=top_n).collect(interval=interval)
