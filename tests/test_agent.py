"""test_agent.py — persona registry + harness (ถามเดี่ยว/ประชุมสภา) ด้วย mock LLM

mock model_backend.generate ไม่ให้ยิง Ollama จริง — เทสตรรกะ harness/persona ล้วน
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import model_backend  # noqa: E402
from app.agent import harness, personas  # noqa: E402


class PersonaTest(unittest.TestCase):
    def test_known_personas_present(self):
        ids = {p["id"] for p in personas.list_personas()}
        for want in ("ceo", "elon", "jobs", "bezos", "carmack", "9arm"):
            self.assertIn(want, ids)

    def test_get_unknown_raises(self):
        with self.assertRaises(ValueError):
            personas.get("ไม่มีคนนี้")

    def test_system_prompt_has_name_and_safety_note(self):
        sp = personas.system_prompt("elon")
        self.assertIn("Elon-lens", sp)
        self.assertIn("ไม่ใช่บุคคลจริง", sp)

    def test_each_persona_has_skills(self):
        for p in personas.list_personas():
            self.assertTrue(p["skills"], f"{p['id']} ต้องมี skills")


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.root = Path("/tmp")
        self.calls = []

        def fake_generate(root, model, messages, num_ctx=8192, options=None):
            sysmsg = messages[0]["content"]
            self.calls.append({"model": model, "system": sysmsg})
            return f"ตอบโดย::{sysmsg[:20]}"

        self.p = mock.patch.object(model_backend, "generate", fake_generate)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_ask_uses_default_qwen_model(self):
        res = harness.ask(self.root, "elon", "ควรรีไรต์ไหม")
        self.assertEqual(res["persona"], "elon")
        self.assertEqual(self.calls[0]["model"], "qwen2.5:0.5b")

    def test_ask_empty_task_raises(self):
        with self.assertRaises(ValueError):
            harness.ask(self.root, "elon", "   ")

    def test_ask_unknown_persona_raises(self):
        with self.assertRaises(ValueError):
            harness.ask(self.root, "nobody", "task")

    def test_council_asks_each_then_synthesizes(self):
        res = harness.council(self.root, "ควรทำ X ไหม", personas_ids=["elon", "jobs"])
        self.assertEqual(len(res["opinions"]), 2)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(res["chair"], personas.CHAIR_ID)
        self.assertTrue(res["synthesis"])
        self.assertIn("CEO", self.calls[-1]["system"])

    def test_council_default_personas(self):
        res = harness.council(self.root, "โจทย์")
        self.assertGreaterEqual(len(res["opinions"]), 3)

    def test_council_custom_chair(self):
        res = harness.council(self.root, "โจทย์", personas_ids=["elon"], chair="carmack")
        self.assertEqual(res["chair"], "carmack")
        self.assertIn("Carmack-lens", self.calls[-1]["system"])


class AgentExtraTest(unittest.TestCase):
    def setUp(self):
        self.root = Path("/tmp")
        self.calls = []

        def fake_generate(root, model, messages, num_ctx=8192, options=None):
            sysmsg = messages[0]["content"]
            self.calls.append({"model": model, "system": sysmsg})
            return f"ตอบโดย::{sysmsg[:20]}"

        self.p = mock.patch.object(model_backend, "generate", fake_generate)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_list_personas_returns_list(self):
        result = personas.list_personas()
        self.assertIsInstance(result, list)

    def test_personas_all_have_id_name_skills_keys(self):
        for p in personas.list_personas():
            for key in ("id", "name", "skills"):
                self.assertIn(key, p, f"persona {p.get('id')} missing key {key}")

    def test_council_returns_dict_with_synthesis_key(self):
        result = harness.council(self.root, "โจทย์", personas_ids=["elon", "jobs"])
        self.assertIn("synthesis", result)

    def test_ask_result_has_reply_key(self):
        # harness.ask returns 'reply' key (not 'answer')
        result = harness.ask(self.root, "elon", "ควรทำไหม")
        self.assertIn("reply", result)

    def test_ask_result_has_persona_key(self):
        result = harness.ask(self.root, "elon", "task")
        self.assertIn("persona", result)
        self.assertEqual(result["persona"], "elon")

    def test_council_opinions_count_matches_input(self):
        result = harness.council(self.root, "โจทย์", personas_ids=["elon", "jobs", "bezos"])
        self.assertEqual(len(result["opinions"]), 3)


if __name__ == "__main__":
    unittest.main()
