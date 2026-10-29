"""test_agent_harness.py — ask/council validation + mocked LLM calls"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import harness  # noqa: E402


class AskValidationTest(unittest.TestCase):
    def test_empty_task_raises(self):
        with self.assertRaises(ValueError):
            harness.ask("/tmp", "ceo", "")

    def test_whitespace_task_raises(self):
        with self.assertRaises(ValueError):
            harness.ask("/tmp", "ceo", "   ")

    def test_too_long_task_raises(self):
        with self.assertRaises(ValueError):
            harness.ask("/tmp", "ceo", "x" * (harness.MAX_TASK_CHARS + 1))

    def test_invalid_persona_raises(self):
        with self.assertRaises(ValueError):
            harness.ask("/tmp", "nonexistent", "task")


class AskWithMockTest(unittest.TestCase):
    @patch("app.model_backend.generate", return_value="mocked reply")
    def test_ask_returns_reply(self, mock_gen):
        result = harness.ask("/tmp", "ceo", "What should we do?")
        self.assertEqual(result["reply"], "mocked reply")
        self.assertEqual(result["persona"], "ceo")
        self.assertIn("name", result)
        mock_gen.assert_called_once()

    @patch("app.model_backend.generate", return_value="reply")
    def test_ask_uses_default_model(self, mock_gen):
        harness.ask("/tmp", "elon", "task")
        args = mock_gen.call_args
        self.assertEqual(args[0][1], harness.DEFAULT_MODEL)

    @patch("app.model_backend.generate", return_value="reply")
    def test_ask_custom_model(self, mock_gen):
        harness.ask("/tmp", "jobs", "task", model="custom-model")
        args = mock_gen.call_args
        self.assertEqual(args[0][1], "custom-model")


class CouncilValidationTest(unittest.TestCase):
    def test_empty_task_raises(self):
        with self.assertRaises(ValueError):
            harness.council("/tmp", "")


class CouncilWithMockTest(unittest.TestCase):
    @patch("app.model_backend.generate", return_value="opinion")
    def test_council_returns_structure(self, mock_gen):
        result = harness.council("/tmp", "How to scale?")
        self.assertIn("task", result)
        self.assertIn("opinions", result)
        self.assertIn("synthesis", result)
        self.assertIn("chair", result)
        self.assertEqual(result["task"], "How to scale?")

    @patch("app.model_backend.generate", return_value="opinion")
    def test_council_default_personas(self, mock_gen):
        result = harness.council("/tmp", "task")
        persona_ids = [o["persona"] for o in result["opinions"]]
        self.assertIn("elon", persona_ids)
        self.assertIn("jobs", persona_ids)
        self.assertIn("carmack", persona_ids)
        self.assertIn("9arm", persona_ids)

    @patch("app.model_backend.generate", return_value="opinion")
    def test_council_custom_personas(self, mock_gen):
        result = harness.council("/tmp", "task", personas_ids=["ceo", "elon"])
        self.assertEqual(len(result["opinions"]), 2)

    @patch("app.model_backend.generate", return_value="synthesis")
    def test_council_calls_generate_n_plus_1(self, mock_gen):
        ids = ["elon", "jobs"]
        harness.council("/tmp", "task", personas_ids=ids)
        self.assertEqual(mock_gen.call_count, len(ids) + 1)


class MessagesTest(unittest.TestCase):
    def test_messages_structure(self):
        msgs = harness._messages("ceo", "do something")
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")
        self.assertEqual(msgs[1]["content"], "do something")

    def test_extra_user_appended(self):
        msgs = harness._messages("ceo", "task", extra_user="extra context")
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[2]["role"], "user")
        self.assertEqual(msgs[2]["content"], "extra context")

    def test_no_extra_user_when_empty(self):
        msgs = harness._messages("ceo", "task", extra_user="")
        self.assertEqual(len(msgs), 2)


if __name__ == "__main__":
    unittest.main()
