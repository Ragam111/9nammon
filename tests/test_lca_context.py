"""
test_lca_context.py — unittest สำหรับ Phase 2 LCA context (ตรวจ Ollama + correlate)
สร้าง Snapshot ปลอมป้อน Analyzer แล้วตรวจผล correlate (stdlib เท่านั้น)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sysmanager.monitor import Analyzer  # noqa: E402
from sysmanager.monitor import lca_context  # noqa: E402
from sysmanager.monitor.snapshot import (  # noqa: E402
    CpuMetrics, MemoryMetrics, ProcessInfo, Snapshot,
)

GB = 1024 ** 3


def _snapshot(mem_percent, *, swap_percent=0.0, procs=None):
    """สร้าง Snapshot น้อยสุดที่ analyzer ใช้ได้ — คุม RAM% + process list"""
    total = 8 * GB
    used = int(total * mem_percent / 100)
    return Snapshot(
        timestamp=0.0,
        interval=0.1,
        hostname="test",
        platform="Linux",
        cpu=CpuMetrics(percent=5.0, per_core=[5.0], logical_cores=1),
        memory=MemoryMetrics(
            total=total, available=total - used, used=used, percent=mem_percent,
            swap_total=(2 * GB if swap_percent else 0),
            swap_used=int(2 * GB * swap_percent / 100),
            swap_percent=swap_percent,
        ),
        top_by_memory=procs or [],
        top_by_cpu=[],
    )


class LcaContextTest(unittest.TestCase):
    def _report(self, snap):
        return Analyzer().analyze(snap)

    def test_detect_ollama_by_name(self):
        snap = _snapshot(30, procs=[
            ProcessInfo(pid=10, name="ollama", memory_percent=40.0, memory_rss=3 * GB),
            ProcessInfo(pid=11, name="python", memory_percent=1.0, memory_rss=10 ** 7),
        ])
        found = lca_context.detect_ollama(snap)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["pid"], 10)

    def test_dedupe_across_lists(self):
        p = ProcessInfo(pid=10, name="ollama_llama_server", memory_percent=40.0, memory_rss=3 * GB)
        snap = _snapshot(30, procs=[p])
        snap.top_by_cpu = [p]  # โผล่ทั้งสองลิสต์ ต้องนับครั้งเดียว
        self.assertEqual(len(lca_context.detect_ollama(snap)), 1)

    def test_pressure_with_ollama(self):
        # RAM 95% (CRITICAL) + พบ ollama → ชี้ว่าน่าจะมาจากโหลดโมเดล
        snap = _snapshot(95, procs=[
            ProcessInfo(pid=10, name="ollama", memory_percent=80.0, memory_rss=6 * GB),
        ])
        out = lca_context.correlate(self._report(snap))
        self.assertTrue(out["ollama_running"])
        self.assertTrue(out["memory_pressure"])
        self.assertIn("โมเดล", out["note"])

    def test_pressure_without_ollama(self):
        snap = _snapshot(95, procs=[
            ProcessInfo(pid=20, name="chrome", memory_percent=80.0, memory_rss=6 * GB),
        ])
        out = lca_context.correlate(self._report(snap))
        self.assertFalse(out["ollama_running"])
        self.assertTrue(out["memory_pressure"])
        self.assertIn("ไม่พบ Ollama", out["note"])

    def test_ollama_running_no_pressure(self):
        snap = _snapshot(30, procs=[
            ProcessInfo(pid=10, name="ollama", memory_percent=20.0, memory_rss=1 * GB),
        ])
        out = lca_context.correlate(self._report(snap))
        self.assertTrue(out["ollama_running"])
        self.assertFalse(out["memory_pressure"])
        self.assertIn("ปลอดภัย", out["note"])

    def test_idle_clean(self):
        out = lca_context.correlate(self._report(_snapshot(20)))
        self.assertFalse(out["ollama_running"])
        self.assertFalse(out["memory_pressure"])
        self.assertEqual(out["ollama_rss"], 0)

    def test_correlate_returns_dict(self):
        out = lca_context.correlate(self._report(_snapshot(20)))
        self.assertIsInstance(out, dict)

    def test_correlate_has_required_keys(self):
        out = lca_context.correlate(self._report(_snapshot(20)))
        for key in ("ollama_running", "ollama_rss", "memory_pressure", "note"):
            self.assertIn(key, out)

    def test_detect_ollama_returns_list(self):
        snap = _snapshot(20)
        result = lca_context.detect_ollama(snap)
        self.assertIsInstance(result, list)

    def test_ollama_rss_is_int(self):
        out = lca_context.correlate(self._report(_snapshot(20)))
        self.assertIsInstance(out["ollama_rss"], int)

    def test_memory_pressure_is_bool(self):
        out = lca_context.correlate(self._report(_snapshot(20)))
        self.assertIsInstance(out["memory_pressure"], bool)

    def test_note_is_string(self):
        out = lca_context.correlate(self._report(_snapshot(20)))
        self.assertIsInstance(out["note"], str)

    def test_ollama_rss_nonzero_when_running(self):
        snap = _snapshot(30, procs=[
            ProcessInfo(pid=10, name="ollama", memory_percent=20.0, memory_rss=1 * GB),
        ])
        out = lca_context.correlate(self._report(snap))
        self.assertGreater(out["ollama_rss"], 0)


if __name__ == "__main__":
    unittest.main()
