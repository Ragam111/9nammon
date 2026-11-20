"""Tests for agents_team.py: queue claims, PM parsing, forbidden paths, dry-run flow."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agents_team  # noqa: E402


class AgentsTeamTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_base = agents_team.BASE
        agents_team.BASE = Path(self._tmp.name)

    def tearDown(self) -> None:
        agents_team.BASE = self._old_base
        self._tmp.cleanup()

    def test_claim_is_exclusive(self) -> None:
        agents_team.enqueue("dev", "add a note")
        first = agents_team.claim_next()
        second = agents_team.claim_next()
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_unknown_role_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            agents_team.enqueue("root", "do everything")

    def test_parse_subtasks_accepts_valid_list(self) -> None:
        text = 'Plan: [{"role": "dev", "goal": "write x"}, {"role": "qa", "goal": "test x"}]'
        self.assertEqual(
            agents_team.parse_subtasks(text),
            [{"role": "dev", "goal": "write x"}, {"role": "qa", "goal": "test x"}],
        )

    def test_parse_subtasks_rejects_bad_items(self) -> None:
        bad_replies = [
            "no list here",
            '[{"role": "pm", "goal": "x"}]',       # PM cannot hand work to PM
            '[{"role": "dev", "goal": "  "}]',      # empty goal
            '["just a string"]',                    # not an object
            json.dumps([{"role": "dev", "goal": "g"}] * 5),  # over MAX_SUBTASKS
        ]
        for reply in bad_replies:
            with self.subTest(reply=reply[:40]):
                with self.assertRaises(ValueError):
                    agents_team.parse_subtasks(reply)

    def test_forbidden_paths_are_rejected(self) -> None:
        for path in [".env", "config/.env", ".git/config", "keys/app.pem", "secrets.txt", "x/my_key.key"]:
            with self.subTest(path=path):
                with self.assertRaises(PermissionError):
                    agents_team.check_files(f"FILE: {path}\nbody")

    def test_allowed_paths_pass(self) -> None:
        agents_team.check_files("FILE: .env.example\nx\nFILE: main.py\ny")

    def test_dry_run_flow_completes_pm_and_subtasks(self) -> None:
        agents_team.enqueue("pm", "improve the health check")
        stats = agents_team.run(hours=0.01, dry=True)
        self.assertEqual(stats, {"done": 4, "failed": 0})   # pm + dev + qa + ops
        self.assertEqual(agents_team.status(), {"todo": 0, "doing": 0, "done": 4, "failed": 0})

    def test_failed_task_is_recorded_not_lost(self) -> None:
        agents_team.enqueue("qa", "review")
        old_url = agents_team.OLLAMA_URL
        agents_team.OLLAMA_URL = "http://127.0.0.1:9"       # nothing listens here -> URLError (an OSError)
        try:
            agents_team.run(hours=0.01, dry=False)
        finally:
            agents_team.OLLAMA_URL = old_url
        counts = agents_team.status()
        self.assertEqual(counts["failed"] + counts["done"], 1)


if __name__ == "__main__":
    unittest.main()
