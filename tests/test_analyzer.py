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

    def test_report_has_verdict(self):
        report = Analyzer().analyze(make_snapshot())
        self.assertIsInstance(report.verdict, str)
        self.assertGreater(len(report.verdict), 0)

    def test_report_worst_is_severity(self):
        report = Analyzer().analyze(make_snapshot())
        self.assertIsInstance(report.worst, Severity)

    def test_findings_is_list(self):
        report = Analyzer().analyze(make_snapshot())
        self.assertIsInstance(report.findings, list)


class SeverityTest(unittest.TestCase):
    def test_severity_has_ok(self):
        self.assertTrue(hasattr(Severity, "OK"))

    def test_severity_has_warning(self):
        self.assertTrue(hasattr(Severity, "WARNING"))

    def test_severity_has_critical(self):
        self.assertTrue(hasattr(Severity, "CRITICAL"))

    def test_critical_greater_than_warning(self):
        self.assertGreater(Severity.CRITICAL, Severity.WARNING)

    def test_warning_greater_than_ok(self):
        self.assertGreater(Severity.WARNING, Severity.OK)


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

    def test_low_cpu_no_cpu_warning(self):
        snap = make_snapshot(cpu_percent=10.0, per_core=[10.0, 10.0])
        report = Analyzer().analyze(snap)
        cpu_warnings = [f for f in report.findings if f.resource == "CPU" and f.severity >= Severity.WARNING]
        self.assertEqual(cpu_warnings, [])


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

    def test_half_full_disk_no_critical(self):
        disk = DiskUsage("/", "sda1", "ext4", 100 * GB, 50 * GB, 50 * GB, 50.0)
        report = Analyzer().analyze(make_snapshot(disks=[disk]))
        self.assertFalse(
            any(f.resource == "DISK" and f.severity == Severity.CRITICAL for f in report.findings)
        )


class PriorityTest(unittest.TestCase):
    def test_memory_wins_tie_against_cpu(self):
        # Both critical; memory should be named primary per priority order.
        snap = make_snapshot(
            cpu_percent=99.0, per_core=[99.0, 99.0],
            mem_percent=99.0, mem_available=100 * 1024 * 1024,
        )
        report = Analyzer().analyze(snap)
        self.assertEqual(report.primary_bottleneck.resource, "MEMORY")

    def test_primary_bottleneck_is_none_when_healthy(self):
        report = Analyzer().analyze(make_snapshot())
        self.assertIsNone(report.primary_bottleneck)


class ThresholdValidationTest(unittest.TestCase):
    def test_invalid_thresholds_rejected(self):
        with self.assertRaises(ValueError):
            Analyzer(Thresholds(cpu_warn=96.0, cpu_crit=95.0))

    def test_valid_custom_thresholds_accepted(self):
        a = Analyzer(Thresholds(cpu_warn=70.0, cpu_crit=90.0))
        self.assertIsNotNone(a)

    def test_custom_threshold_lowers_cpu_warn(self):
        # With a low warn threshold, moderate CPU should trigger a finding.
        a = Analyzer(Thresholds(cpu_warn=20.0, cpu_crit=90.0))
        snap = make_snapshot(cpu_percent=50.0, per_core=[50.0, 50.0])
        report = a.analyze(snap)
        self.assertTrue(any(f.resource == "CPU" for f in report.findings))


if __name__ == "__main__":
    unittest.main()
