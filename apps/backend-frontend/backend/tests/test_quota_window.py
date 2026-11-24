"""5-hour quota windows start at 00:00 Bangkok time and reset on their own."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta, timezone

from app import quota
from app.auth import create_user
from app.db import Database
from app.errors import AppError
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


class WeeklyBucketTest(unittest.TestCase):
    def test_week_starts_on_wednesday_three_pm(self) -> None:
        # 2026-11-21 is a Saturday, so the last Wednesday 15:00 is 2026-11-18
        self.assertEqual(quota.week_start(_bkk(10, day=21)), _bkk(15, day=18))
        self.assertEqual(quota.week_start(_bkk(14, 59, day=18)), _bkk(15, day=11))
        self.assertEqual(quota.week_start(_bkk(15, 0, day=18)), _bkk(15, day=18))

    def test_plan_has_heavy_bucket_only_for_heavy_models(self) -> None:
        settings = make_settings()
        names = [b.name for b in quota.plan(settings, heavy=False)]
        self.assertEqual(names, ["five_hour", "weekly"])
        heavy = quota.plan(settings, heavy=True)
        self.assertEqual([b.name for b in heavy], ["five_hour", "weekly", "heavy_weekly"])
        self.assertEqual(heavy[2].limit, settings.quota_tokens_heavy_weekly)

    def test_heavy_bucket_refuses_even_when_five_hour_has_room(self) -> None:
        settings = make_settings(quota_tokens_heavy_weekly=100)
        db = Database(make_settings().data_dir / "app.db")
        uid = create_user(db, "erin", "correct-horse-5").id
        buckets = quota.plan(settings, heavy=True)
        quota.record_all(db, uid, buckets, 100)
        with self.assertRaises(AppError) as ctx:
            quota.check_all(db, uid, buckets, need=1)
        self.assertIn("โมเดลหนัก", ctx.exception.user_message)

    def test_light_run_counts_only_on_all_model_buckets(self) -> None:
        settings = make_settings()
        db = Database(make_settings().data_dir / "app.db")
        uid = create_user(db, "fay", "correct-horse-6").id
        quota.record_all(db, uid, quota.plan(settings, heavy=False), 500)
        heavy = quota.plan(settings, heavy=True)
        self.assertEqual(quota.used(db, uid, heavy[2].key), 0)
        self.assertEqual(quota.used(db, uid, heavy[1].key), 500)


class HoldExpiryTest(unittest.TestCase):
    """A hold counts while it is live, is removed by settling, and stops counting after HOLD_TTL on its own."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path as _Path

        self.tmp = tempfile.TemporaryDirectory()
        self.settings = make_settings(data_dir=_Path(self.tmp.name))
        self.db = Database(self.settings.data_dir / "app.db")
        create_user(self.db, "alice", "correct-horse-battery")
        with self.db.session() as conn:
            self.uid = int(conn.execute("SELECT id FROM users WHERE username = 'alice'").fetchone()["id"])
        self.bucket = quota.plan(self.settings, heavy=False)[0]
        self.start = datetime(2026, 11, 21, 10, 0, tzinfo=BANGKOK)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_live_hold_counts_and_settling_replaces_it(self) -> None:
        hold = quota.reserve_all(self.db, self.uid, [self.bucket], 50, now=self.start)
        self.assertEqual(quota.used(self.db, self.uid, self.bucket.key, now=self.start), 50)
        quota.settle_all(self.db, self.uid, [self.bucket], hold, charged=3)
        self.assertEqual(quota.used(self.db, self.uid, self.bucket.key, now=self.start), 3)

    def test_unsettled_hold_stops_counting_after_the_ttl(self) -> None:
        quota.reserve_all(self.db, self.uid, [self.bucket], 50, now=self.start)
        later = self.start + quota.HOLD_TTL + timedelta(minutes=1)
        self.assertEqual(quota.used(self.db, self.uid, self.bucket.key, now=later), 0)

    def test_settling_after_expiry_still_charges(self) -> None:
        hold = quota.reserve_all(self.db, self.uid, [self.bucket], 50, now=self.start)
        later = self.start + quota.HOLD_TTL + timedelta(minutes=1)
        quota.settle_all(self.db, self.uid, [self.bucket], hold, charged=7)
        self.assertEqual(quota.used(self.db, self.uid, self.bucket.key, now=later), 7)


if __name__ == "__main__":
    unittest.main()
