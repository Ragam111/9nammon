"""test_schedule_gate.py — เวลาเปิด-ปิดเซิร์ฟเวอร์ (TH timezone)"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import schedule_gate  # noqa: E402


# helper: datetime at a specific Thai hour (UTC+7)
def _utc_at_th_hour(th_hour: int, th_minute: int = 0) -> datetime:
    """คืน datetime UTC ที่ตรงกับเวลาไทย hh:mm วันนี้ (date arbitrary)"""
    utc_hour = (th_hour - 7) % 24
    return datetime(2026, 10, 29, utc_hour, th_minute, tzinfo=timezone.utc)


class IsOpenTest(unittest.TestCase):
    def test_at_open_hour_is_open(self):
        self.assertTrue(schedule_gate.is_open(_utc_at_th_hour(6), 6, 20))

    def test_midday_is_open(self):
        self.assertTrue(schedule_gate.is_open(_utc_at_th_hour(12), 6, 20))

    def test_at_close_hour_is_closed(self):
        # window = [6, 20) — hour 20 ถือว่าปิดแล้ว
        self.assertFalse(schedule_gate.is_open(_utc_at_th_hour(20), 6, 20))

    def test_before_open_is_closed(self):
        self.assertFalse(schedule_gate.is_open(_utc_at_th_hour(5), 6, 20))

    def test_after_close_is_closed(self):
        self.assertFalse(schedule_gate.is_open(_utc_at_th_hour(23), 6, 20))

    def test_midnight_is_closed(self):
        self.assertFalse(schedule_gate.is_open(_utc_at_th_hour(0), 6, 20))

    def test_cross_midnight_window(self):
        # 22..6 → เปิด 22:00-06:00
        self.assertTrue(schedule_gate.is_open(_utc_at_th_hour(23), 22, 6))
        self.assertTrue(schedule_gate.is_open(_utc_at_th_hour(0), 22, 6))
        self.assertTrue(schedule_gate.is_open(_utc_at_th_hour(5), 22, 6))
        self.assertFalse(schedule_gate.is_open(_utc_at_th_hour(6), 22, 6))
        self.assertFalse(schedule_gate.is_open(_utc_at_th_hour(12), 22, 6))

    def test_equal_hours_always_closed(self):
        self.assertFalse(schedule_gate.is_open(_utc_at_th_hour(12), 10, 10))

    def test_naive_datetime_treated_as_utc(self):
        naive = datetime(2026, 10, 29, 5, 0)  # 05:00 UTC = 12:00 TH → open
        self.assertTrue(schedule_gate.is_open(naive, 6, 20))


class NextWindowTest(unittest.TestCase):
    def test_open_state_when_inside(self):
        info = schedule_gate.next_window(_utc_at_th_hour(12), 6, 20)
        self.assertEqual(info["state"], "open")

    def test_closed_state_when_outside(self):
        info = schedule_gate.next_window(_utc_at_th_hour(22), 6, 20)
        self.assertEqual(info["state"], "closed")

    def test_seconds_until_change_positive(self):
        info = schedule_gate.next_window(_utc_at_th_hour(12), 6, 20)
        self.assertGreater(info["seconds_until_change"], 0)

    def test_from_noon_closes_at_20_same_day(self):
        info = schedule_gate.next_window(_utc_at_th_hour(12), 6, 20)
        self.assertIn("state", info)
        # 20:00 - 12:00 = 8 hours = 28800 seconds
        self.assertEqual(info["seconds_until_change"], 8 * 3600)

    def test_from_22_opens_at_6_next_day(self):
        info = schedule_gate.next_window(_utc_at_th_hour(22), 6, 20)
        # 22:00 → 06:00 next day = 8 hours
        self.assertEqual(info["seconds_until_change"], 8 * 3600)

    def test_includes_open_close_hours(self):
        info = schedule_gate.next_window(_utc_at_th_hour(12), 7, 19)
        self.assertEqual(info["open_hour"], 7)
        self.assertEqual(info["close_hour"], 19)


class ClampHourTest(unittest.TestCase):
    def test_valid_int(self):
        self.assertEqual(schedule_gate._clamp_hour(10, 0), 10)

    def test_valid_string(self):
        self.assertEqual(schedule_gate._clamp_hour("15", 0), 15)

    def test_out_of_range_high(self):
        self.assertEqual(schedule_gate._clamp_hour(25, 7), 7)

    def test_out_of_range_low(self):
        self.assertEqual(schedule_gate._clamp_hour(-1, 7), 7)

    def test_non_numeric(self):
        self.assertEqual(schedule_gate._clamp_hour("abc", 7), 7)

    def test_none(self):
        self.assertEqual(schedule_gate._clamp_hour(None, 7), 7)


class ConfigReadTest(unittest.TestCase):
    def setUp(self):
        schedule_gate.invalidate_cache()  # กัน cache ข้ามเทสหลัง optimization

    def test_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(schedule_gate.enabled(Path(tmp)))

    def test_enabled_true_variants(self):
        for truthy in ("true", "1", "yes", "on", "TRUE"):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)
                (p / "config.json").write_text(json.dumps({"SCHEDULE_ENABLED": truthy}),
                                               encoding="utf-8")
                self.assertTrue(schedule_gate.enabled(p),
                                f"'{truthy}' ต้องถือเป็น true")

    def test_enabled_false_variants(self):
        for falsy in ("false", "0", "no", "off", ""):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)
                (p / "config.json").write_text(json.dumps({"SCHEDULE_ENABLED": falsy}),
                                               encoding="utf-8")
                self.assertFalse(schedule_gate.enabled(p),
                                 f"'{falsy}' ต้องถือเป็น false")

    def test_window_hours_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            open_h, close_h = schedule_gate.window_hours(Path(tmp))
            self.assertEqual(open_h, schedule_gate.DEFAULT_OPEN_HOUR)
            self.assertEqual(close_h, schedule_gate.DEFAULT_CLOSE_HOUR)

    def test_window_hours_custom(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config.json").write_text(
                json.dumps({"SCHEDULE_OPEN_HOUR": 8, "SCHEDULE_CLOSE_HOUR": 22}),
                encoding="utf-8")
            open_h, close_h = schedule_gate.window_hours(p)
            self.assertEqual(open_h, 8)
            self.assertEqual(close_h, 22)


class CacheTest(unittest.TestCase):
    """optimization: enabled()/window_hours() ควรใช้ cache ใน hot path"""

    def setUp(self):
        schedule_gate.invalidate_cache()

    def test_cache_hits_second_call(self):
        """second call ภายใน TTL ไม่ควรอ่าน config ใหม่"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config.json").write_text(json.dumps({"SCHEDULE_ENABLED": "true"}),
                                           encoding="utf-8")
            # เรียกครั้งแรก — ตรวจ True
            self.assertTrue(schedule_gate.enabled(p))
            # แก้ config เป็น false — ถ้า cache ทำงานถูก ต้องยังอ่าน True (cached)
            (p / "config.json").write_text(json.dumps({"SCHEDULE_ENABLED": "false"}),
                                           encoding="utf-8")
            self.assertTrue(schedule_gate.enabled(p))  # cache ยังสด → True

    def test_invalidate_cache_refreshes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config.json").write_text(json.dumps({"SCHEDULE_ENABLED": "true"}),
                                           encoding="utf-8")
            self.assertTrue(schedule_gate.enabled(p))
            (p / "config.json").write_text(json.dumps({"SCHEDULE_ENABLED": "false"}),
                                           encoding="utf-8")
            schedule_gate.invalidate_cache()
            self.assertFalse(schedule_gate.enabled(p))

    def test_window_hours_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config.json").write_text(
                json.dumps({"SCHEDULE_OPEN_HOUR": 7, "SCHEDULE_CLOSE_HOUR": 19}),
                encoding="utf-8")
            self.assertEqual(schedule_gate.window_hours(p), (7, 19))
            # แก้ config — ยังควร return cached
            (p / "config.json").write_text(
                json.dumps({"SCHEDULE_OPEN_HOUR": 8, "SCHEDULE_CLOSE_HOUR": 22}),
                encoding="utf-8")
            self.assertEqual(schedule_gate.window_hours(p), (7, 19))


class StatusTest(unittest.TestCase):
    def setUp(self):
        schedule_gate.invalidate_cache()

    def test_status_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = schedule_gate.status(Path(tmp))
            self.assertFalse(info["enabled"])
            self.assertEqual(info["state"], "open")

    def test_status_when_enabled_inside_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config.json").write_text(
                json.dumps({"SCHEDULE_ENABLED": "true"}), encoding="utf-8")
            info = schedule_gate.status(p, now_utc=_utc_at_th_hour(12))
            self.assertTrue(info["enabled"])
            self.assertEqual(info["state"], "open")
            self.assertIn("message", info)

    def test_status_when_enabled_outside_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config.json").write_text(
                json.dumps({"SCHEDULE_ENABLED": "true"}), encoding="utf-8")
            info = schedule_gate.status(p, now_utc=_utc_at_th_hour(22))
            self.assertTrue(info["enabled"])
            self.assertEqual(info["state"], "closed")
            self.assertIn("ปิดตามตารางเวลา", info["message"])


if __name__ == "__main__":
    unittest.main()
