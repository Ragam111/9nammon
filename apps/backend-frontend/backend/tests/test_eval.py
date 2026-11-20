"""The eval scorer and the --fake run (which must pass every case with its own reference answer)."""

from __future__ import annotations

import asyncio
import unittest

from scripts.run_eval import load_cases, run_all, score
from tests.helpers import make_settings


class ScoreTest(unittest.TestCase):
    def test_empty_answer_fails(self) -> None:
        self.assertEqual(score("   ", {}), ["empty answer"])

    def test_contains_all_and_any_ignore_case(self) -> None:
        self.assertEqual(score("SELECT COUNT(*) FROM Users", {"contains_all": ["count", "users"]}), [])
        self.assertTrue(score("SELECT 1", {"contains_any": ["count", "sum"]}))

    def test_must_not_contain_and_thai_and_length(self) -> None:
        failures = score("here is sk-123 in English", {"must_not_contain": ["sk-"], "thai": True, "max_chars": 5})
        self.assertEqual(len(failures), 3)

    def test_thai_detected(self) -> None:
        self.assertEqual(score("สวัสดี", {"thai": True}), [])


class FakeRunTest(unittest.TestCase):
    def test_every_reference_passes_its_own_checks(self) -> None:
        cases = load_cases()
        self.assertGreaterEqual(len(cases), 8)
        self.assertEqual(len({c["id"] for c in cases}), len(cases), "case ids must be unique")
        report = asyncio.run(run_all(make_settings(max_output_tokens=512), cases, fake=True))
        failed = [r for r in report["results"] if not r["pass"]]
        self.assertEqual(failed, [])
        self.assertEqual(report["summary"]["pass_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
