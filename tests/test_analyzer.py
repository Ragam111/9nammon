"""Unit tests for the bottleneck analyzer.

These build synthetic snapshots so the diagnosis logic is tested in isolation,
without depending on the state of the machine running the tests.
"""

import unittest

from sysmanager.monitor import (
    Analyzer,
    CpuMetrics,
    DiskIoMetrics,
    DiskUsage,
    MemoryMetrics,
    NetworkMetrics,
    Severity,
    Snapshot,
    Thresholds,
)

GB = 1024 ** 3


def make_snapshot(
    cpu_percent=10.0,
    per_core=None,
    load_per_core=None,
    mem_percent=30.0,
    mem_available=12 * GB,
    swap_percent=0.0,
    swap_total=8 * GB,
    disks=None,
    io_util=5.0,
):
    return Snapshot(
        timestamp=0.0,
        interval=1.0,
        hostname="test",
        platform="test-os",
        cpu=CpuMetrics(
            percent=cpu_percent,
            per_core=per_core or [cpu_percent, cpu_percent],
            logical_cores=len(per_core or [0, 0]),
            physical_cores=2,
            load_avg_1m=(load_per_core * 2) if load_per_core else None,
            load_per_core=load_per_core,
        ),
        memory=MemoryMetrics(
            total=16 * GB,
            available=mem_available,
            used=16 * GB - mem_available,
            percent=mem_percent,
            swap_total=swap_total,
            swap_used=int(swap_total * swap_percent / 100),
            swap_percent=swap_percent,
        ),
        disks=disks or [],
        disk_io=DiskIoMetrics(
            read_bytes_per_s=1e6,
            write_bytes_per_s=1e6,
            busiest_util_percent=io_util,
            busiest_device="sda",
        ),
        network=NetworkMetrics(),
    )


class HealthyTest(unittest.TestCase):
    def test_idle_machine_has_no_bottleneck(self):
        report = Analyzer().analyze(make_snapshot())
        self.assertEqual(report.worst, Severity.OK)
        self.assertIsNone(report.primary_bottleneck)
        self.assertIn("healthy", report.verdict.lower())


class CpuTest(unittest.TestCase):
    def test_saturated_cpu_is_critical(self):
        snap = make_snapshot(cpu_percent=98.0, per_core=[99.0, 97.0])
        report = Analyzer().analyze(snap)
        bn = report.primary_bottleneck
        self.assertIsNotNone(bn)
        self.assertEqual(bn.resource, "CPU")
        self.assertEqual(bn.severity, Severity.CRITICAL)

    def test_high_load_average_flags_cpu(self):
        snap = make_snapshot(cpu_percent=40.0, load_per_core=2.5)
        report = Analyzer().analyze(snap)
        self.assertTrue(
            any(f.resource == "CPU" and f.severity >= Severity.WARNING for f in report.findings)
        )


class MemoryTest(unittest.TestCase):
    def test_low_memory_is_the_bottleneck(self):
        snap = make_snapshot(mem_percent=97.0, mem_available=200 * 1024 * 1024)
        report = Analyzer().analyze(snap)
        bn = report.primary_bottleneck
        self.assertEqual(bn.resource, "MEMORY")
        self.assertEqual(bn.severity, Severity.CRITICAL)

    def test_active_swap_reported_as_pressure(self):
        snap = make_snapshot(swap_percent=70.0)
        report = Analyzer().analyze(snap)
        self.assertTrue(any(f.resource == "SWAP" for f in report.findings))

    def test_no_swap_device_produces_no_swap_finding(self):
        snap = make_snapshot(swap_total=0, swap_percent=0.0)
        report = Analyzer().analyze(snap)
        self.assertFalse(any(f.resource == "SWAP" for f in report.findings))


class DiskTest(unittest.TestCase):
    def test_full_disk_is_flagged(self):
        disk = DiskUsage("/", "sda1", "ext4", 100 * GB, 96 * GB, 4 * GB, 96.0)
        report = Analyzer().analyze(make_snapshot(disks=[disk]))
        self.assertTrue(
            any(f.resource == "DISK" and f.severity == Severity.CRITICAL for f in report.findings)
        )

    def test_readonly_full_disk_is_ignored(self):
        # A read-only mount at 100% (e.g. squashfs) must not be a bottleneck.
        ro = DiskUsage("/snap", "loop0", "squashfs", 10 * GB, 10 * GB, 0, 100.0, readonly=True)
        report = Analyzer().analyze(make_snapshot(disks=[ro]))
        self.assertFalse(any(f.resource == "DISK" for f in report.findings))
        self.assertEqual(report.worst, Severity.OK)

    def test_saturated_io_is_bottleneck(self):
        report = Analyzer().analyze(make_snapshot(io_util=95.0))
        bn = report.primary_bottleneck
        self.assertEqual(bn.resource, "DISK_IO")


class PriorityTest(unittest.TestCase):
    def test_memory_wins_tie_against_cpu(self):
        # Both critical; memory should be named primary per priority order.
        snap = make_snapshot(
            cpu_percent=99.0, per_core=[99.0, 99.0],
            mem_percent=99.0, mem_available=100 * 1024 * 1024,
        )
        report = Analyzer().analyze(snap)
        self.assertEqual(report.primary_bottleneck.resource, "MEMORY")


class ThresholdValidationTest(unittest.TestCase):
    def test_invalid_thresholds_rejected(self):
        with self.assertRaises(ValueError):
            Analyzer(Thresholds(cpu_warn=96.0, cpu_crit=95.0))


if __name__ == "__main__":
    unittest.main()
