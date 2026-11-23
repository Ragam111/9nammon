"""Offline demo models: run the whole workflow with no API key and no network.

DemoModel answers each role with a fixed, correct reply, chosen by the role's system prompt.
It is a demonstration of the loop, not a test of model quality: real runs use AnthropicClient.
"""

from __future__ import annotations

import json

from .roles import EXECUTOR_SYSTEM, EXECUTOR_TOOLS_SYSTEM, HARNESS_JUDGE_SYSTEM, PLANNER_SYSTEM

DEMO_GOAL = "เขียนสรุปสั้นเรื่องประโยชน์ของการแบ่งงานให้หลาย agent แล้วสรุปผลจากไฟล์นั้น"
NOTE_PATH = "notes/t1.md"
NOTE_TEXT = (
    "การแบ่งงานให้หลาย agent ช่วยให้แต่ละ agent ทำหน้าที่เดียว "
    "และให้ Harness ตรวจผลก่อนรับทุกครั้ง"
)


class DemoModel:
    """Implements the ModelClient protocol. Routes on the system prompt, so one object serves all roles."""

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        if system == PLANNER_SYSTEM:
            return json.dumps({"tasks": [
                {"id": "t1", "title": "เขียนบันทึกสั้น", "acceptance": f"มีไฟล์ {NOTE_PATH} ที่เขียนเสร็จ",
                 "depends_on": []},
                {"id": "t2", "title": "สรุปจากบันทึก", "acceptance": "สรุปที่ยกประเด็นจากบันทึกอย่างน้อยหนึ่งข้อ",
                 "depends_on": ["t1"]},
            ]}, ensure_ascii=False)
        if system == HARNESS_JUDGE_SYSTEM:
            return json.dumps({"pass": True, "reason": "ผลตรงกับ acceptance"}, ensure_ascii=False)
        if system == EXECUTOR_SYSTEM:
            return json.dumps({"status": "done", "output": NOTE_TEXT}, ensure_ascii=False)
        if system == EXECUTOR_TOOLS_SYSTEM:
            return self._tool_reply(messages)
        raise ValueError("unknown role prompt")

    @staticmethod
    def _tool_reply(messages: list[dict[str, str]]) -> str:
        prompt = messages[0]["content"]
        last = messages[-1]["content"]
        if "ผลจากเครื่องมือ" in last:
            if "งาน t1:" in prompt:
                output = f"เขียนไฟล์ {NOTE_PATH} แล้ว"
            else:
                result = json.loads(last.split("ผลจากเครื่องมือ:", 1)[1])
                output = "สรุป: " + str(result.get("text", ""))[:300]
            return json.dumps({"status": "done", "output": output}, ensure_ascii=False)
        if "งาน t1:" in prompt:
            tool = {"action": "write_file", "path": NOTE_PATH, "content": NOTE_TEXT}
        else:
            tool = {"action": "read_file", "path": NOTE_PATH}
        return json.dumps({"tool": tool}, ensure_ascii=False)
