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

    def test_mode_defaults_chat(self):
        skill = skills_store.add(self.root, "S", "p")
        self.assertEqual(skill["mode"], "chat")
        self.assertEqual(skill["max_steps"], skills_store.DEFAULT_MAX_STEPS)
        self.assertFalse(skill["tools_write"])

    def test_agent_mode_and_steps_clamp(self):
        skill = skills_store.add(self.root, "A", "p", mode="agent", max_steps=99, tools_write=True)
        self.assertEqual(skill["mode"], "agent")
        self.assertEqual(skill["max_steps"], skills_store.MAX_STEPS_CAP)   # clamp 99→20
        self.assertTrue(skill["tools_write"])

    def test_bad_mode_rejected(self):
        with self.assertRaises(skills_store.SkillError):
            skills_store.add(self.root, "A", "p", mode="telepathy")

    def test_update_mode(self):
        skill = skills_store.add(self.root, "A", "p")
        up = skills_store.update(self.root, skill["id"], {"mode": "agent", "max_steps": 3})
        self.assertEqual(up["mode"], "agent")
        self.assertEqual(up["max_steps"], 3)


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


class _ScriptedBackend:
    """สมองปลอม: ตอบตามสคริปต์ทีละรอบ (ให้ agent loop วิ่งแบบ deterministic)"""
    def __init__(self, replies):
        self.replies = list(replies)

    def is_available(self):
        return True

    def generate(self, model, messages, num_ctx=8192, options=None):
        return self.replies.pop(0) if self.replies else '{"final":"หมดสคริปต์"}'


class BotsAgentModeTest(unittest.TestCase):
    """bot ที่ skill.mode=agent → วิ่ง ReAct เรียก tools ใน sandbox (agent_workspace)"""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_backend_for = connections._backend_for
        self.conn = connections.add(self.root, "Brain", "ollama", model="m")

    def tearDown(self):
        connections._backend_for = self._orig_backend_for
        self._tmp.cleanup()

    def _agent_bot(self, tools_write=False, max_steps=6):
        skill = skills_store.add(self.root, "Agent", "คุณคือ agent", connection_id=self.conn["id"],
                                 model="m", mode="agent", max_steps=max_steps, tools_write=tools_write)
        return bots.add(self.root, "AgentBot", skill["id"])

    def test_agent_runs_tools_and_returns_steps(self):
        backend = _ScriptedBackend([
            '{"thought":"ดูไฟล์","tool":"list_dir","args":{"path":"."}}',
            '{"thought":"เสร็จ","final":"ไม่มีไฟล์ในโฟลเดอร์"}',
        ])
        connections._backend_for = lambda rec: backend
        bot = self._agent_bot()
        res = bots.run(self.root, bot["id"], "สำรวจ workspace")
        self.assertEqual(res["mode"], "agent")
        self.assertEqual(res["output"], "ไม่มีไฟล์ในโฟลเดอร์")
        self.assertEqual(res["stopped_reason"], "final")
        self.assertTrue(len(res["steps"]) >= 1)
        self.assertEqual(res["steps"][0]["tool"], "list_dir")
        # agent_workspace ถูกสร้างใต้ project_root
        self.assertTrue((self.root / bots.AGENT_WORKSPACE_DIR).is_dir())

    def test_agent_workspace_confined_rejects_escape(self):
        connections._backend_for = lambda rec: _ScriptedBackend(['{"final":"ok"}'])
        bot = self._agent_bot()
        with self.assertRaises(bots.BotError):
            bots.run(self.root, bot["id"], "x", workspace="../../etc")

    def test_agent_tools_write_creates_pending_approval(self):
        # P6: skill tools_write → agent เสนอเขียนไฟล์ → เกิดคำขออนุมัติ (ยังไม่เขียนจริง)
        from app.agent import approvals as agent_approvals
        backend = _ScriptedBackend([
            '{"thought":"เขียน","tool":"propose_write_file","args":{"path":"out.txt","content":"hi"}}',
            '{"thought":"เสนอแล้ว","final":"รออนุมัติ"}',
        ])
        connections._backend_for = lambda rec: backend
        bot = self._agent_bot(tools_write=True)
        res = bots.run(self.root, bot["id"], "เขียนไฟล์ out.txt")
        self.assertEqual(res["output"], "รออนุมัติ")
        pending = agent_approvals.list_pending(self.root)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["kind"], agent_approvals.KIND_WRITE)
        # ยังไม่เขียนจริง (ไฟล์ยังไม่เกิดใน agent_workspace)
        self.assertFalse((self.root / bots.AGENT_WORKSPACE_DIR / "out.txt").exists())


if __name__ == "__main__":
    unittest.main()
