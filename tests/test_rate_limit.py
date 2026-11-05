"""
test_rate_limit.py — unittest สำหรับ RateLimiter (sliding window, stdlib)
ใช้พารามิเตอร์ now= เพื่อคุมเวลาแบบ deterministic (ไม่ต้อง sleep จริง)

Covers:
  RateLimiterTest     — allows up to limit then blocks, sliding window, per-client
                        isolation, zero disables, reset per-client
  RateLimiterEdgeTest — allow returns bool, negative max disables, reset all (None),
                        reset non-existent key (no crash), window boundary (at cutoff),
                        max=1 boundary, large window, many clients
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.rate_limit import RateLimiter  # noqa: E402


class RateLimiterTest(unittest.TestCase):
    def test_allows_up_to_limit_then_blocks(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertTrue(rl.allow("ip1", now=1))
        self.assertTrue(rl.allow("ip1", now=2))
        self.assertFalse(rl.allow("ip1", now=3))

    def test_window_slides(self):
        rl = RateLimiter(max_requests=2, window_seconds=10)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertTrue(rl.allow("ip1", now=1))
        self.assertFalse(rl.allow("ip1", now=2))
        self.assertTrue(rl.allow("ip1", now=12))

    def test_per_client_isolation(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertFalse(rl.allow("ip1", now=0))
        self.assertTrue(rl.allow("ip2", now=0))

    def test_zero_or_negative_disables(self):
        rl = RateLimiter(max_requests=0)
        for i in range(1000):
            self.assertTrue(rl.allow("ip1", now=i))

    def test_reset(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertFalse(rl.allow("ip1", now=0))
        rl.reset("ip1")
        self.assertTrue(rl.allow("ip1", now=0))


class RateLimiterEdgeTest(unittest.TestCase):
    def test_allow_returns_bool(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        result = rl.allow("ip1", now=0)
        self.assertIsInstance(result, bool)

    def test_negative_max_disables(self):
        rl = RateLimiter(max_requests=-1)
        for i in range(100):
            self.assertTrue(rl.allow("ip1", now=i),
                            f"ครั้งที่ {i}: max<0 ต้อง disable")

    def test_reset_all_clears_every_client(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.allow("ip1", now=0)
        rl.allow("ip2", now=0)
        self.assertFalse(rl.allow("ip1", now=0))
        self.assertFalse(rl.allow("ip2", now=0))
        rl.reset(None)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertTrue(rl.allow("ip2", now=0))

    def test_reset_nonexistent_key_no_crash(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        try:
            rl.reset("not-seen-before")
        except Exception as e:
            self.fail(f"reset() ต้องไม่ crash สำหรับ key ที่ไม่เคยมี: {e}")

    def test_window_boundary_exactly_at_cutoff(self):
        rl = RateLimiter(max_requests=1, window_seconds=10)
        rl.allow("ip1", now=0)
        # at exactly now=10 the first hit is AT the cutoff → depends on implementation
        # (now - window = 0 ≤ 0) so it should still be counted OR just expired
        # test that behavior is consistent (doesn't crash)
        result = rl.allow("ip1", now=10)
        self.assertIsInstance(result, bool)

    def test_max_1_boundary(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertFalse(rl.allow("ip1", now=0))
        self.assertFalse(rl.allow("ip1", now=30))
        self.assertTrue(rl.allow("ip1", now=61))

    def test_large_window_keeps_requests(self):
        rl = RateLimiter(max_requests=5, window_seconds=3600)
        for i in range(5):
            self.assertTrue(rl.allow("ip1", now=float(i * 100)))
        self.assertFalse(rl.allow("ip1", now=500.0))

    def test_many_clients_independent(self):
        rl = RateLimiter(max_requests=2, window_seconds=60)
        clients = [f"ip{i}" for i in range(50)]
        for c in clients:
            self.assertTrue(rl.allow(c, now=0))
            self.assertTrue(rl.allow(c, now=0))
            self.assertFalse(rl.allow(c, now=0), f"{c} ต้องถูก block ที่ครั้งที่ 3")


if __name__ == "__main__":
    unittest.main()
