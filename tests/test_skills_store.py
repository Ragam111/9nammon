"""test_skills_store.py — CRUD, validation, migration, helpers"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import skills_store  # noqa: E402
from app.skills_store import SkillError  # noqa: E402


class AddSkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_add_returns_record(self):
        rec = skills_store.add(self.tmp, "Translate", "Translate Thai to English")
        self.assertIn("id", rec)
        self.assertEqual(rec["name"], "Translate")
        self.assertEqual(rec["system_prompt"], "Translate Thai to English")

    def test_add_id_prefix(self):
        rec = skills_store.add(self.tmp, "S1", "prompt")
        self.assertTrue(rec["id"].startswith("skl-"))

    def test_add_empty_name_rejected(self):
        with self.assertRaises(SkillError):
            skills_store.add(self.tmp, "", "prompt")

    def test_add_empty_prompt_rejected(self):
        with self.assertRaises(SkillError):
            skills_store.add(self.tmp, "Name", "")

    def test_add_duplicate_name_rejected(self):
        skills_store.add(self.tmp, "Uniq", "prompt")
        with self.assertRaises(SkillError):
            skills_store.add(self.tmp, "Uniq", "prompt2")

    def test_add_defaults(self):
        rec = skills_store.add(self.tmp, "D", "p")
        self.assertEqual(rec["mode"], "chat")
        self.assertEqual(rec["max_steps"], skills_store.DEFAULT_MAX_STEPS)
        self.assertFalse(rec["tools_write"])
        self.assertFalse(rec["tools_net"])
        self.assertIsNone(rec["temperature"])

    def test_add_agent_mode(self):
        rec = skills_store.add(self.tmp, "Agent", "p", mode="agent", max_steps=10,
                               tools_write=True, tools_net=True)
        self.assertEqual(rec["mode"], "agent")
        self.assertEqual(rec["max_steps"], 10)
        self.assertTrue(rec["tools_write"])
        self.assertTrue(rec["tools_net"])


class GetSkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_get_existing(self):
        rec = skills_store.add(self.tmp, "X", "p")
        found = skills_store.get(self.tmp, rec["id"])
        self.assertEqual(found["name"], "X")

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(skills_store.get(self.tmp, "skl-nope"))


class ListSkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_list_empty(self):
        self.assertEqual(skills_store.list_skills(self.tmp), [])

    def test_list_after_add(self):
        skills_store.add(self.tmp, "A", "p")
        skills_store.add(self.tmp, "B", "p")
        self.assertEqual(len(skills_store.list_skills(self.tmp)), 2)


class UpdateSkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rec = skills_store.add(self.tmp, "Old", "old prompt")

    def test_update_name(self):
        updated = skills_store.update(self.tmp, self.rec["id"], {"name": "New"})
        self.assertEqual(updated["name"], "New")

    def test_update_prompt(self):
        updated = skills_store.update(self.tmp, self.rec["id"], {"system_prompt": "new prompt"})
        self.assertEqual(updated["system_prompt"], "new prompt")

    def test_update_nonexistent_raises(self):
        with self.assertRaises(SkillError):
            skills_store.update(self.tmp, "skl-nope", {"name": "X"})

    def test_update_duplicate_name_rejected(self):
        skills_store.add(self.tmp, "Taken", "p")
        with self.assertRaises(SkillError):
            skills_store.update(self.tmp, self.rec["id"], {"name": "Taken"})

    def test_update_temperature(self):
        updated = skills_store.update(self.tmp, self.rec["id"], {"temperature": 0.7})
        self.assertEqual(updated["temperature"], 0.7)

    def test_update_mode_to_agent(self):
        updated = skills_store.update(self.tmp, self.rec["id"], {"mode": "agent"})
        self.assertEqual(updated["mode"], "agent")


class RemoveSkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_remove_existing(self):
        rec = skills_store.add(self.tmp, "Del", "p")
        self.assertTrue(skills_store.remove(self.tmp, rec["id"]))
        self.assertIsNone(skills_store.get(self.tmp, rec["id"]))

    def test_remove_nonexistent_returns_false(self):
        self.assertFalse(skills_store.remove(self.tmp, "skl-nope"))


class ClampTempTest(unittest.TestCase):
    def test_none_returns_default(self):
        self.assertIsNone(skills_store._clamp_temp(None))
        self.assertEqual(skills_store._clamp_temp(None, 0.5), 0.5)

    def test_empty_returns_default(self):
        self.assertIsNone(skills_store._clamp_temp(""))

    def test_clamp_low(self):
        self.assertEqual(skills_store._clamp_temp(-1), 0.0)

    def test_clamp_high(self):
        self.assertEqual(skills_store._clamp_temp(5), 2.0)

    def test_valid_value(self):
        self.assertEqual(skills_store._clamp_temp(1.5), 1.5)

    def test_non_numeric_raises(self):
        with self.assertRaises(SkillError):
            skills_store._clamp_temp("abc")


class NormModeTest(unittest.TestCase):
    def test_none_returns_default(self):
        self.assertEqual(skills_store._norm_mode(None), "chat")

    def test_valid_agent(self):
        self.assertEqual(skills_store._norm_mode("AGENT"), "agent")

    def test_invalid_raises(self):
        with self.assertRaises(SkillError):
            skills_store._norm_mode("invalid")


class ClampStepsTest(unittest.TestCase):
    def test_none_returns_default(self):
        self.assertEqual(skills_store._clamp_steps(None), skills_store.DEFAULT_MAX_STEPS)

    def test_clamp_low(self):
        self.assertEqual(skills_store._clamp_steps(0), 1)

    def test_clamp_high(self):
        self.assertEqual(skills_store._clamp_steps(100), skills_store.MAX_STEPS_CAP)

    def test_non_int_raises(self):
        with self.assertRaises(SkillError):
            skills_store._clamp_steps("abc")


class BuildMessagesTest(unittest.TestCase):
    def test_build_messages_structure(self):
        skill = {"system_prompt": "You translate"}
        msgs = skills_store.build_messages(skill, "Hello")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[0]["content"], "You translate")
        self.assertEqual(msgs[1]["role"], "user")
        self.assertEqual(msgs[1]["content"], "Hello")


class OptionsForTest(unittest.TestCase):
    def test_with_temperature(self):
        self.assertEqual(skills_store.options_for({"temperature": 0.8}), {"temperature": 0.8})

    def test_without_temperature(self):
        self.assertEqual(skills_store.options_for({}), {})

    def test_none_temperature(self):
        self.assertEqual(skills_store.options_for({"temperature": None}), {})


class MigrationTest(unittest.TestCase):
    def test_v1_to_v2_adds_mode_fields(self):
        records = [{"id": "skl-1", "name": "A"}]
        result = skills_store._migrate_v1_to_v2(records)
        self.assertEqual(result[0]["mode"], "chat")
        self.assertEqual(result[0]["max_steps"], skills_store.DEFAULT_MAX_STEPS)
        self.assertFalse(result[0]["tools_write"])

    def test_v2_to_v3_adds_tools_net(self):
        records = [{"id": "skl-1", "mode": "chat"}]
        result = skills_store._migrate_v2_to_v3(records)
        self.assertFalse(result[0]["tools_net"])


if __name__ == "__main__":
    unittest.main()
