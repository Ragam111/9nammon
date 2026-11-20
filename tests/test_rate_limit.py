"""
test_rate_limit.py — unittest สำหรับ RateLimiter (sliding window, stdlib)
ใช้พารามิเตอร์ now= เพื่อคุมเวลาแบบ deterministic (ไม่ต้อง sleep จริง)
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
        self.assertFalse(rl.allow("ip1", now=3))  # ครั้งที่ 4 ในหน้าต่างเดียว -> บล็อก

    def test_window_slides(self):
        rl = RateLimiter(max_requests=2, window_seconds=10)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertTrue(rl.allow("ip1", now=1))
        self.assertFalse(rl.allow("ip1", now=2))
        # พอเวลาเลยหน้าต่าง (เกิน 10s จาก now=0,1) รายการเก่าหลุด -> อนุญาตอีก
        self.assertTrue(rl.allow("ip1", now=12))

    def test_per_client_isolation(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertFalse(rl.allow("ip1", now=0))
        self.assertTrue(rl.allow("ip2", now=0))  # คนละ IP นับแยกกัน

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


class RateLimitExtraTest(unittest.TestCase):
    def test_allow_returns_bool(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        result = rl.allow("ip1", now=0)
        self.assertIsInstance(result, bool)

    def test_initial_allow_is_true(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("x", now=0))

    def test_exceeding_limit_returns_false(self):
        rl = RateLimiter(max_requests=2, window_seconds=60)
        rl.allow("x", now=0)
        rl.allow("x", now=1)
        self.assertFalse(rl.allow("x", now=2))

    def test_reset_re_enables_client(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.allow("x", now=0)
        rl.reset("x")
        self.assertTrue(rl.allow("x", now=0))

    def test_unlimited_max_always_allows(self):
        rl = RateLimiter(max_requests=0)
        for i in range(100):
            self.assertTrue(rl.allow("x", now=i))

    def test_different_keys_are_independent(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("a", now=0))
        self.assertFalse(rl.allow("a", now=0))
        self.assertTrue(rl.allow("b", now=0))


if __name__ == "__main__":
    unittest.main()
