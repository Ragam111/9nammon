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
        self.assertIn("ไม่ใช่บุคคลจริง", sp)   # กันการปลอมเป็นตัวจริง

    def test_each_persona_has_skills(self):
        for p in personas.list_personas():
            self.assertTrue(p["skills"], f"{p['id']} ต้องมี skills")


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.root = Path("/tmp")
        self.calls = []

        def fake_generate(root, model, messages, num_ctx=8192, options=None):
            # จำ model + system prompt ของแต่ละ call ไว้ตรวจ แล้วตอบตามชื่อเลนส์
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
        self.assertEqual(self.calls[0]["model"], "qwen2.5:0.5b")   # ต่อ qwen2.5:0.5b ตามที่สั่ง

    def test_ask_empty_task_raises(self):
        with self.assertRaises(ValueError):
            harness.ask(self.root, "elon", "   ")

    def test_ask_unknown_persona_raises(self):
        with self.assertRaises(ValueError):
            harness.ask(self.root, "nobody", "task")

    def test_council_asks_each_then_synthesizes(self):
        res = harness.council(self.root, "ควรทำ X ไหม", personas_ids=["elon", "jobs"])
        # 2 ความเห็น + 1 สังเคราะห์ = 3 call
        self.assertEqual(len(res["opinions"]), 2)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(res["chair"], personas.CHAIR_ID)
        self.assertTrue(res["synthesis"])
        # call สุดท้าย (สังเคราะห์) ต้องเป็น system ของประธาน
        self.assertIn("CEO", self.calls[-1]["system"])

    def test_council_default_personas(self):
        res = harness.council(self.root, "โจทย์")
        self.assertGreaterEqual(len(res["opinions"]), 3)   # ชุดเริ่มต้นหลายมุม

    def test_council_custom_chair(self):
        res = harness.council(self.root, "โจทย์", personas_ids=["elon"], chair="carmack")
        self.assertEqual(res["chair"], "carmack")
        self.assertIn("Carmack-lens", self.calls[-1]["system"])


if __name__ == "__main__":
    unittest.main()
