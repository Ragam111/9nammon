"""test_agent_personas.py — persona get/list/system_prompt"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import personas  # noqa: E402


class GetPersonaTest(unittest.TestCase):
    def test_valid_persona(self):
        p = personas.get("ceo")
        self.assertEqual(p["id"], "ceo")
        self.assertEqual(p["name"], "CEO")

    def test_case_insensitive(self):
        p = personas.get("CEO")
        self.assertEqual(p["id"], "ceo")

    def test_whitespace_stripped(self):
        p = personas.get("  elon  ")
        self.assertEqual(p["id"], "elon")

    def test_unknown_persona_raises(self):
        with self.assertRaises(ValueError):
            personas.get("nonexistent")

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            personas.get("")

    def test_all_personas_gettable(self):
        for pid in personas.PERSONAS:
            p = personas.get(pid)
            self.assertEqual(p["id"], pid)
            self.assertIn("name", p)
            self.assertIn("skills", p)


class ListPersonasTest(unittest.TestCase):
    def test_returns_list(self):
        result = personas.list_personas()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_all_personas_included(self):
        result = personas.list_personas()
        ids = {p["id"] for p in result}
        for pid in personas.PERSONAS:
            self.assertIn(pid, ids)

    def test_no_prompt_in_list(self):
        result = personas.list_personas()
        for p in result:
            self.assertNotIn("prompt", p)

    def test_has_required_fields(self):
        result = personas.list_personas()
        for p in result:
            self.assertIn("id", p)
            self.assertIn("name", p)
            self.assertIn("title", p)
            self.assertIn("skills", p)


class SystemPromptTest(unittest.TestCase):
    def test_contains_persona_name(self):
        prompt = personas.system_prompt("ceo")
        self.assertIn("CEO", prompt)

    def test_contains_skills(self):
        prompt = personas.system_prompt("carmack")
        self.assertIn("วัดก่อนเชื่อ", prompt)

    def test_contains_safety_disclaimer(self):
        prompt = personas.system_prompt("elon")
        self.assertIn("เลนส์ความคิด", prompt)
        self.assertIn("ไม่ใช่บุคคลจริง", prompt)

    def test_all_personas_generate_prompt(self):
        for pid in personas.PERSONAS:
            prompt = personas.system_prompt(pid)
            self.assertIsInstance(prompt, str)
            self.assertGreater(len(prompt), 50)


if __name__ == "__main__":
    unittest.main()
