"""test_skills_bots.py — Skills registry + Bots (run ผ่าน skill → connection)

bots.run monkeypatch connections.chat ไม่ต่อสมองจริง — เช็ก logic การประกอบ messages +
นับ run_count + error paths (skill หาย / ไม่ผูก connection / bot ปิด)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import skills_store, bots, connections  # noqa: E402


class SkillsStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_requires_name_and_prompt(self):
        with self.assertRaises(skills_store.SkillError):
            skills_store.add(self.root, "", "prompt")
        with self.assertRaises(skills_store.SkillError):
            skills_store.add(self.root, "name", "")

    def test_add_list_update_remove(self):
        rec = skills_store.add(self.root, "Sum", "สรุปให้หน่อย", connection_id="con-x",
                              model="m", description="d", temperature=0.5)
        self.assertTrue(rec["id"].startswith("skl-"))
        self.assertEqual(rec["temperature"], 0.5)
        self.assertEqual(len(skills_store.list_skills(self.root)), 1)
        up = skills_store.update(self.root, rec["id"], {"model": "m2", "temperature": 9})
        self.assertEqual(up["model"], "m2")
        self.assertEqual(up["temperature"], 2.0)                     # clamp 0..2
        self.assertTrue(skills_store.remove(self.root, rec["id"]))
        self.assertFalse(skills_store.remove(self.root, rec["id"]))

    def test_temperature_non_number_rejected(self):
        with self.assertRaises(skills_store.SkillError):
            skills_store.add(self.root, "S", "p", temperature="hot")

    def test_build_messages_and_options(self):
        skill = skills_store.add(self.root, "S", "คุณคือบอท", temperature=0.3)
        msgs = skills_store.build_messages(skill, "ทำงาน")
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[0]["content"], "คุณคือบอท")
        self.assertEqual(msgs[1]["content"], "ทำงาน")
        self.assertEqual(skills_store.options_for(skill), {"temperature": 0.3})


class BotsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_chat = connections.chat
        self.conn = connections.add(self.root, "Brain", "ollama", model="m")
        self.skill = skills_store.add(self.root, "Greet", "ทักทายสุภาพ",
                                      connection_id=self.conn["id"], model="m")

    def tearDown(self):
        connections.chat = self._orig_chat
        self._tmp.cleanup()

    def test_add_requires_existing_skill(self):
        with self.assertRaises(bots.BotError):
            bots.add(self.root, "B", "skl-nope")

    def test_add_list_remove(self):
        bot = bots.add(self.root, "GreetBot", self.skill["id"], description="d")
        self.assertTrue(bot["id"].startswith("bot-"))
        self.assertEqual(bot["run_count"], 0)
        self.assertEqual(len(bots.list_bots(self.root)), 1)
        self.assertTrue(bots.remove(self.root, bot["id"]))

    def test_run_calls_connection_and_counts(self):
        captured = {}

        def fake_chat(root, conn_id, messages, model="", options=None):
            captured["conn_id"] = conn_id
            captured["messages"] = messages
            captured["model"] = model
            return "สวัสดีค่ะ"
        connections.chat = fake_chat
        bot = bots.add(self.root, "GreetBot", self.skill["id"])
        res = bots.run(self.root, bot["id"], "hi")
        self.assertEqual(res["output"], "สวัสดีค่ะ")
        self.assertEqual(captured["conn_id"], self.conn["id"])
        self.assertEqual(captured["messages"][0]["role"], "system")
        self.assertEqual(captured["messages"][1]["content"], "hi")
        # run_count เพิ่ม
        self.assertEqual(bots.get(self.root, bot["id"])["run_count"], 1)

    def test_run_requires_input(self):
        bot = bots.add(self.root, "B", self.skill["id"])
        with self.assertRaises(bots.BotError):
            bots.run(self.root, bot["id"], "   ")

    def test_run_disabled_bot_errors(self):
        connections.chat = lambda *a, **k: "x"
        bot = bots.add(self.root, "B", self.skill["id"], enabled=False)
        with self.assertRaises(bots.BotError):
            bots.run(self.root, bot["id"], "hi")

    def test_run_skill_without_connection_errors(self):
        connections.chat = lambda *a, **k: "x"
        skill2 = skills_store.add(self.root, "NoConn", "prompt")      # ไม่ผูก connection
        bot = bots.add(self.root, "B2", skill2["id"])
        with self.assertRaises(bots.BotError):
            bots.run(self.root, bot["id"], "hi")

    def test_run_missing_skill_errors(self):
        connections.chat = lambda *a, **k: "x"
        bot = bots.add(self.root, "B3", self.skill["id"])
        skills_store.remove(self.root, self.skill["id"])             # ลบ skill ทิ้ง
        with self.assertRaises(bots.BotError):
            bots.run(self.root, bot["id"], "hi")


if __name__ == "__main__":
    unittest.main()
