"""core.py — agent loop ขั้นสูง: คิด → เรียก tool → เห็นผล → วนจนจบ (ReAct-style)

ต่างจาก harness (ที่ปรึกษา ให้ความเห็นอย่างเดียว) — ตัวนี้ "ลงมือ" ผ่าน tools ใน sandbox.

โปรโตคอล (ให้ LLM ตอบ JSON บรรทัดเดียวต่อรอบ):
  {"thought": "...", "tool": "read_file", "args": {"path": "server.py"}}   # เรียก tool
  {"thought": "...", "final": "คำตอบสุดท้าย"}                               # จบงาน
loop ป้อนผล tool กลับเป็น observation แล้ววนจน final หรือครบ max_steps.

ปลอดภัย: ทุก tool วิ่งผ่าน sandbox (confine path + allowlist). log ทุก step ไว้ตรวจย้อนได้.
degrade: LLM ตอบไม่เป็น JSON → ป้อน error กลับให้แก้ (ไม่ crash). ครบ max_steps → คืนผลเท่าที่มี.

stdlib ล้วน. ต่อ LLM ผ่าน model_backend (default qwen2.5:0.5b).
"""

from __future__ import annotations

import json

from app import model_backend
from app.agent import tools as tools_mod

DEFAULT_MODEL = "qwen2.5:0.5b"
DEFAULT_MAX_STEPS = 8


def _system_prompt(tool_schemas: list) -> str:
    lines = [f"- {t['name']}({', '.join(t['args'])}): {t['desc']}" for t in tool_schemas]
    tools_txt = "\n".join(lines)
    return (
        "คุณคือ AI agent สายเทคที่ลงมือทำงานเป็นขั้น ๆ ด้วยเครื่องมือที่มี.\n"
        f"เครื่องมือที่ใช้ได้:\n{tools_txt}\n\n"
        "กติกาการตอบ: ตอบเป็น JSON บรรทัดเดียวเท่านั้น ไม่มีข้อความอื่นนอก JSON:\n"
        '  เรียกเครื่องมือ: {"thought":"เหตุผลสั้น","tool":"ชื่อ","args":{...}}\n'
        '  จบงาน:         {"thought":"สรุปสั้น","final":"คำตอบสุดท้ายให้ผู้ใช้"}\n'
        "ทำทีละขั้น: อ่าน/ตรวจก่อนสรุป. อย่าเดาเนื้อไฟล์ — ใช้ read_file ดูจริง. "
        "เมื่อมั่นใจแล้วค่อยตอบ final."
    )


def _parse(reply: str) -> dict:
    """ดึง JSON ก้อนแรกจากคำตอบ LLM (เผื่อมีข้อความห่อ) — คืน dict หรือโยน ValueError"""
    s = reply.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("ไม่พบ JSON ในคำตอบ")
    return json.loads(s[start:end + 1])


def run(project_root, task: str, workspace, model: str = DEFAULT_MODEL,
        max_steps: int = DEFAULT_MAX_STEPS, allowed_commands=None) -> dict:
    """รัน agent 1 งาน — คืน {final, steps:[...], stopped_reason}
    - workspace: โฟลเดอร์ที่ agent ทำงานได้ (sandbox confine ไว้)
    - steps: log ทุกขั้น (thought/tool/args/observation หรือ final) ไว้ตรวจย้อน
    """
    task = (task or "").strip()
    if not task:
        raise ValueError("ต้องระบุ task")
    sb = tools_mod.Sandbox(workspace, allowed_commands or tools_mod.DEFAULT_ALLOWED_COMMANDS)
    registry = tools_mod.build_registry(sb)

    messages = [
        {"role": "system", "content": _system_prompt(tools_mod.TOOL_SCHEMAS)},
        {"role": "user", "content": f"งาน: {task}"},
    ]
    steps = []
    for _ in range(max_steps):
        reply = model_backend.generate(project_root, model, messages)
        try:
            action = _parse(reply)
        except ValueError:
            # LLM ตอบไม่เป็น JSON — ป้อน error กลับให้แก้ (ไม่ทิ้งงาน)
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": "ตอบเป็น JSON ตามรูปแบบที่กำหนดเท่านั้น"})
            steps.append({"error": "parse", "raw": reply[:500]})
            continue

        if "final" in action:
            steps.append({"thought": action.get("thought", ""), "final": action["final"]})
            return {"final": action["final"], "steps": steps, "stopped_reason": "final"}

        tool_name = action.get("tool", "")
        args = action.get("args", {}) or {}
        fn = registry.get(tool_name)
        if fn is None:
            obs = f"ไม่รู้จักเครื่องมือ '{tool_name}' (มี: {', '.join(registry)})"
        else:
            try:
                obs = fn(args)
            except tools_mod.ToolError as e:
                obs = f"[tool error] {e}"
        steps.append({"thought": action.get("thought", ""), "tool": tool_name,
                      "args": args, "observation": obs})
        # ป้อนผลกลับให้ agent คิดต่อ
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": f"ผลจาก {tool_name}:\n{obs}"})

    return {"final": None, "steps": steps, "stopped_reason": "max_steps"}
