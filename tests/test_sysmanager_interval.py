"""test_sysmanager_interval.py — ค่า -i/--interval ต้องเป็นจำนวนจริงบวกและจำกัด

ก่อนแก้: -i 0 / -i -1 ทำให้ ValueError traceback, -i nan ทำให้ JSON มี NaN
หลังแก้: argparse ตอบ usage + ข้อความสั้น exit 2 ไม่มี traceback; collector ก็ปฏิเสธ nan/inf
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sysmanager import cli  # noqa: E402
from sysmanager.monitor import collector  # noqa: E402


class IntervalArgTest(unittest.TestCase):
    def _run_expect_usage_error(self, value):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            # ไม่ควรไปถึง psutil — ต้องตกที่ parse ก่อน
            with mock.patch.object(collector.Collector, "collect",
                                   side_effect=AssertionError("collect must not run")):
                cli.main(["snapshot", "--json", "-i", value])
        self.assertEqual(cm.exception.code, 2)
        text = err.getvalue()
        self.assertIn("interval", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("ValueError", text)

    def test_zero_negative_nan_inf_are_rejected_cleanly(self):
        for bad in ("0", "-1", "-0.5", "nan", "inf", "-inf", "abc"):
            with self.subTest(value=bad):
                self._run_expect_usage_error(bad)

    def test_valid_interval_is_accepted_by_parser(self):
        parser = cli.build_parser()
        args = parser.parse_args(["snapshot", "-i", "0.5"])
        self.assertEqual(args.interval, 0.5)
        args = parser.parse_args(["watch", "--interval", "2"])
        self.assertEqual(args.interval, 2.0)

    def test_default_interval_unchanged(self):
        args = cli.build_parser().parse_args(["snapshot"])
        self.assertEqual(args.interval, 1.0)


class CollectorIntervalTest(unittest.TestCase):
    def test_collect_rejects_non_finite_and_non_positive(self):
        for bad in (0, -1, float("nan"), float("inf")):
            with self.subTest(interval=bad), self.assertRaises(ValueError):
                collector.Collector().collect(interval=bad)


if __name__ == "__main__":
    unittest.main()
