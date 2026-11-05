"""
test_rate_limit.py — unittest สำหรับ RateLimiter (sliding window, stdlib)

Covers:
  allow()  — up-to-limit, sliding window, per-client isolation, disabled (0/negative),
             exact boundary, no-now parameter, max_requests=1 edge case
  reset()  — single client, all clients, reset-one-not-other independence
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.rate_limit import RateLimiter  # noqa: E402


class TestRateLimiterAllow(unittest.TestCase):
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
        # oldest entry at t=0 expires when cutoff=now-window=12-10=2; 0<=2 → pops
        self.assertTrue(rl.allow("ip1", now=12))

    def test_per_client_isolation(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertFalse(rl.allow("ip1", now=0))
        self.assertTrue(rl.allow("ip2", now=0))

    def test_zero_max_requests_disables(self):
        rl = RateLimiter(max_requests=0)
        for i in range(1000):
            self.assertTrue(rl.allow("ip1", now=i))

    def test_negative_max_requests_disables(self):
        rl = RateLimiter(max_requests=-5)
        for i in range(100):
            self.assertTrue(rl.allow("ip1", now=i))

    def test_max_requests_one_allows_first_blocks_second(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("x", now=0))
        self.assertFalse(rl.allow("x", now=0))

    def test_exact_window_boundary_expires_entry(self):
        # entry at t=0, window=10; cutoff = 10 - 10 = 0; 0 <= 0 → pops → allowed
        rl = RateLimiter(max_requests=1, window_seconds=10)
        self.assertTrue(rl.allow("x", now=0))
        self.assertFalse(rl.allow("x", now=5))   # still inside window
        self.assertTrue(rl.allow("x", now=10))   # exactly at boundary: entry expires

    def test_allow_without_now_uses_monotonic(self):
        rl = RateLimiter(max_requests=10, window_seconds=60)
        t_before = time.monotonic()
        result = rl.allow("x")
        t_after = time.monotonic()
        self.assertTrue(result)
        # Verify an entry was recorded (queue is non-empty for this client)
        with rl._lock:
            q = rl._hits["x"]
            self.assertEqual(len(q), 1)
            self.assertGreaterEqual(q[0], t_before)
            self.assertLessEqual(q[0], t_after)

    def test_multiple_clients_do_not_interfere(self):
        rl = RateLimiter(max_requests=2, window_seconds=60)
        # exhaust client A
        rl.allow("A", now=0)
        rl.allow("A", now=0)
        self.assertFalse(rl.allow("A", now=0))
        # client B still has full quota
        self.assertTrue(rl.allow("B", now=0))
        self.assertTrue(rl.allow("B", now=0))
        self.assertFalse(rl.allow("B", now=0))


class TestRateLimiterReset(unittest.TestCase):
    def test_reset_single_client_clears_its_queue(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertFalse(rl.allow("ip1", now=0))
        rl.reset("ip1")
        self.assertTrue(rl.allow("ip1", now=0))

    def test_reset_all_clears_every_client(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.allow("a", now=0)
        rl.allow("b", now=0)
        self.assertFalse(rl.allow("a", now=0))
        self.assertFalse(rl.allow("b", now=0))
        rl.reset()          # None → clear all
        self.assertTrue(rl.allow("a", now=0))
        self.assertTrue(rl.allow("b", now=0))

    def test_reset_specific_does_not_affect_other_clients(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.allow("keep", now=0)
        rl.allow("clear", now=0)
        # both are now blocked
        self.assertFalse(rl.allow("keep", now=0))
        self.assertFalse(rl.allow("clear", now=0))
        rl.reset("clear")
        # 'clear' recovered, 'keep' still blocked
        self.assertTrue(rl.allow("clear", now=0))
        self.assertFalse(rl.allow("keep", now=0))

    def test_reset_unknown_client_does_not_raise(self):
        rl = RateLimiter(max_requests=5)
        rl.reset("never_seen")  # must not raise


if __name__ == "__main__":
    unittest.main()
