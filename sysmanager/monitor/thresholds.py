"""Tunable thresholds for bottleneck detection.

Defaults are deliberately conservative starting points. The optimizer module
will later learn per-machine values; for now they are hand-set and overridable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Thresholds:
    # CPU utilisation (%) -> warning / critical
    cpu_warn: float = 85.0
    cpu_crit: float = 95.0
    # Load average per core (unix). >1.0 means more runnable work than cores.
    load_per_core_warn: float = 1.0
    load_per_core_crit: float = 2.0

    # Memory utilisation (%)
    mem_warn: float = 85.0
    mem_crit: float = 95.0

    # Swap: any active swap usage above this (%) hints at memory pressure.
    swap_warn: float = 25.0
    swap_crit: float = 60.0

    # Filesystem capacity (%)
    disk_warn: float = 85.0
    disk_crit: float = 95.0

    # Busiest-disk utilisation (% of time busy) -> I/O saturation.
    disk_io_warn: float = 70.0
    disk_io_crit: float = 90.0

    def validate(self) -> None:
        """Raise ValueError if any warn >= crit, where that must hold."""
        pairs = {
            "cpu": (self.cpu_warn, self.cpu_crit),
            "load_per_core": (self.load_per_core_warn, self.load_per_core_crit),
            "mem": (self.mem_warn, self.mem_crit),
            "swap": (self.swap_warn, self.swap_crit),
            "disk": (self.disk_warn, self.disk_crit),
            "disk_io": (self.disk_io_warn, self.disk_io_crit),
        }
        for name, (warn, crit) in pairs.items():
            if warn >= crit:
                raise ValueError(
                    f"threshold {name}: warn ({warn}) must be below crit ({crit})"
                )
