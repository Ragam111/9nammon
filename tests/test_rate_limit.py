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
        self.assertFalse(rl.allow("ip1", now=3))  # ครั้งที่ 4 ในหน้าต่างเดียว -> บล็อค

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


class RateLimiterExtraTest(unittest.TestCase):
    def test_new_client_is_allowed(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        self.assertTrue(rl.allow("brand-new-client", now=0))

    def test_multiple_clients_independent(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("a", now=0))
        self.assertTrue(rl.allow("b", now=0))
        self.assertTrue(rl.allow("c", now=0))

    def test_allow_returns_bool(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        result = rl.allow("ip1", now=0)
        self.assertIsInstance(result, bool)

    def test_max_requests_one_allows_exactly_one(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(rl.allow("ip1", now=0))
        self.assertFalse(rl.allow("ip1", now=1))

    def test_reset_clears_history(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.allow("ip1", now=0)
        rl.reset("ip1")
        self.assertTrue(rl.allow("ip1", now=0))

    def test_window_exact_boundary(self):
        rl = RateLimiter(max_requests=1, window_seconds=10)
        rl.allow("ip1", now=0)
        self.assertTrue(rl.allow("ip1", now=11))


if __name__ == "__main__":
    unittest.main()
