"""test_bots.py — CRUD, validation, workspace confinement, run/stream validation"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bots, skills_store  # noqa: E402
from app.bots import BotError  # noqa: E402


def _add_skill(tmp):
    """Helper: create a skill and return its record."""
    return skills_store.add(tmp, "TestSkill", "You are helpful",
                            connection_id="conn-1", model="gpt-4")


class AddBotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.skill = _add_skill(self.tmp)

    def test_add_returns_record(self):
        rec = bots.add(self.tmp, "MyBot", self.skill["id"])
        self.assertIn("id", rec)
        self.assertEqual(rec["name"], "MyBot")
        self.assertEqual(rec["skill_id"], self.skill["id"])
        self.assertTrue(rec["enabled"])
        self.assertEqual(rec["run_count"], 0)

    def test_add_id_prefix(self):
        rec = bots.add(self.tmp, "B1", self.skill["id"])
        self.assertTrue(rec["id"].startswith("bot-"))

    def test_add_empty_name_rejected(self):
        with self.assertRaises(BotError):
            bots.add(self.tmp, "", self.skill["id"])

    def test_add_empty_skill_id_rejected(self):
        with self.assertRaises(BotError):
            bots.add(self.tmp, "Bot", "")

    def test_add_nonexistent_skill_rejected(self):
        with self.assertRaises(BotError):
            bots.add(self.tmp, "Bot", "skl-nonexistent")

    def test_add_duplicate_name_rejected(self):
        bots.add(self.tmp, "Uniq", self.skill["id"])
        with self.assertRaises(BotError):
            bots.add(self.tmp, "Uniq", self.skill["id"])


class GetBotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.skill = _add_skill(self.tmp)

    def test_get_existing(self):
        rec = bots.add(self.tmp, "B", self.skill["id"])
        found = bots.get(self.tmp, rec["id"])
        self.assertEqual(found["name"], "B")

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(bots.get(self.tmp, "bot-nope"))


class ListBotsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.skill = _add_skill(self.tmp)

    def test_list_empty(self):
        self.assertEqual(bots.list_bots(self.tmp), [])

    def test_list_after_add(self):
        bots.add(self.tmp, "A", self.skill["id"])
        bots.add(self.tmp, "B", self.skill["id"])
        self.assertEqual(len(bots.list_bots(self.tmp)), 2)


class UpdateBotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.skill = _add_skill(self.tmp)
        self.rec = bots.add(self.tmp, "Old", self.skill["id"])

    def test_update_name(self):
        updated = bots.update(self.tmp, self.rec["id"], {"name": "New"})
        self.assertEqual(updated["name"], "New")

    def test_update_enabled(self):
        updated = bots.update(self.tmp, self.rec["id"], {"enabled": False})
        self.assertFalse(updated["enabled"])

    def test_update_nonexistent_raises(self):
        with self.assertRaises(BotError):
            bots.update(self.tmp, "bot-nope", {"name": "X"})

    def test_update_duplicate_name_rejected(self):
        bots.add(self.tmp, "Taken", self.skill["id"])
        with self.assertRaises(BotError):
            bots.update(self.tmp, self.rec["id"], {"name": "Taken"})

    def test_update_skill_id_validates(self):
        with self.assertRaises(BotError):
            bots.update(self.tmp, self.rec["id"], {"skill_id": "skl-nonexistent"})


class RemoveBotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.skill = _add_skill(self.tmp)

    def test_remove_existing(self):
        rec = bots.add(self.tmp, "Del", self.skill["id"])
        self.assertTrue(bots.remove(self.tmp, rec["id"]))
        self.assertIsNone(bots.get(self.tmp, rec["id"]))

    def test_remove_nonexistent_returns_false(self):
        self.assertFalse(bots.remove(self.tmp, "bot-nope"))


class AgentWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_workspace_created_under_agent_workspace(self):
        ws = bots._agent_workspace(self.tmp, ".")
        self.assertTrue(str(ws).startswith(str(self.tmp)))
        self.assertIn("agent_workspace", str(ws))

    def test_workspace_traversal_rejected(self):
        with self.assertRaises(BotError):
            bots._agent_workspace(self.tmp, "../../etc")


class RunValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.skill = _add_skill(self.tmp)
        self.bot = bots.add(self.tmp, "RunBot", self.skill["id"])

    def test_empty_input_rejected(self):
        with self.assertRaises(BotError):
            bots.run(self.tmp, self.bot["id"], "")

    def test_nonexistent_bot_rejected(self):
        with self.assertRaises(BotError):
            bots.run(self.tmp, "bot-nope", "hello")

    def test_disabled_bot_rejected(self):
        bots.update(self.tmp, self.bot["id"], {"enabled": False})
        with self.assertRaises(BotError):
            bots.run(self.tmp, self.bot["id"], "hello")

    def test_missing_skill_rejected(self):
        skills_store.remove(self.tmp, self.skill["id"])
        with self.assertRaises(BotError):
            bots.run(self.tmp, self.bot["id"], "hello")


class RunStreamValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.skill = _add_skill(self.tmp)
        self.bot = bots.add(self.tmp, "StreamBot", self.skill["id"])

    def test_empty_input_rejected(self):
        with self.assertRaises(BotError):
            bots.run_stream(self.tmp, self.bot["id"], "")

    def test_nonexistent_bot_rejected(self):
        with self.assertRaises(BotError):
            bots.run_stream(self.tmp, "bot-nope", "hello")

    def test_disabled_bot_rejected(self):
        bots.update(self.tmp, self.bot["id"], {"enabled": False})
        with self.assertRaises(BotError):
            bots.run_stream(self.tmp, self.bot["id"], "hello")

    def test_agent_mode_rejected(self):
        skills_store.update(self.tmp, self.skill["id"], {"mode": "agent"})
        with self.assertRaises(BotError):
            bots.run_stream(self.tmp, self.bot["id"], "hello")


if __name__ == "__main__":
    unittest.main()
