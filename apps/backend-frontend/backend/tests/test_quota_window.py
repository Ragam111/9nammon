"""5-hour quota windows start at 00:00 Bangkok time and reset on their own."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta, timezone

from app import quota
from app.auth import create_user
from app.db import Database
from tests.helpers import make_settings

BANGKOK = timezone(timedelta(hours=7))


def _bkk(hour: int, minute: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=BANGKOK)


class WindowTest(unittest.TestCase):
    def test_window_boundaries_in_bangkok_time(self) -> None:
        self.assertEqual(quota.current_window(_bkk(0)), "2026-11-21T00")
        self.assertEqual(quota.current_window(_bkk(4, 59)), "2026-11-21T00")
        self.assertEqual(quota.current_window(_bkk(5)), "2026-11-21T05")
        self.assertEqual(quota.current_window(_bkk(9, 59)), "2026-11-21T05")
        self.assertEqual(quota.current_window(_bkk(23, 59)), "2026-11-21T20")

    def test_utc_input_is_converted_to_bangkok(self) -> None:
        # 22:00 UTC on 20 Nov is 05:00 Bangkok on 21 Nov, the start of a new window
        self.assertEqual(quota.current_window(datetime(2026, 11, 20, 22, 0, tzinfo=UTC)), "2026-11-21T05")
        self.assertEqual(quota.current_window(datetime(2026, 11, 20, 21, 59, tzinfo=UTC)), "2026-11-21T00")

    def test_reset_time_is_the_next_boundary(self) -> None:
        self.assertEqual(quota.window_resets_at(_bkk(4, 59)), "2026-11-21T05:00:00+07:00")
        self.assertEqual(quota.window_resets_at(_bkk(20, 30)), "2026-11-22T00:00:00+07:00")

    def test_usage_does_not_carry_into_the_next_window(self) -> None:
        db = Database(make_settings().data_dir / "app.db")
        uid = create_user(db, "dana", "correct-horse-4").id
        first, second = quota.current_window(_bkk(4)), quota.current_window(_bkk(5))
        quota.record(db, uid, 900_000, window=first)
        self.assertEqual(quota.remaining(db, uid, 1_000_000, second), 1_000_000)
        self.assertEqual(quota.remaining(db, uid, 1_000_000, first), 100_000)


if __name__ == "__main__":
    unittest.main()
