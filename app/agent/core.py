"""core.py — agent loop ขั้นสูง: คิด → เรียก tool → เห็นผล → วนจนจบ (ReAct-style)

ต่างจาก harness (ที่ปรึกษา ให้ความเห็นอย่างเดียว) — ตัวนี้ "ลงมือ" ผ่าน tools ใน sandbox.

โปรโตคอล (ให้ LLM ตอบ JSON บรรทัดเดียวต่อรอบ):
  {"thought": "...", "tool": "read_file", "args": {"path": "server.py"}}   # เรียก tool
  {"thought": "...", "action": "finish", "final": "คำตอบสุดท้าย"}          # จบงาน (canonical)
  {"thought": "...", "final": "คำตอบสุดท้าย"}                               # alias เดิม (ยังรับได้)
  ทางเลือกอีกรูปแบบ: {"action": "read_file", "input": {...}} ก็รับได้เช่นกัน
loop ป้อนผล tool กลับเป็น observation แล้ววนจน finish หรือครบ max_steps.

ทุก step มีฟิลด์: step (เลข 0-based), action, input, observation, thought
  - step ของ tool: เพิ่ม tool/args ซ้ำไว้เพื่อความเข้ากันได้กับโค้ดเดิม
  - step ของ finish: action="finish", input={"final": ...}, final=...
  - step ของ parse error: action="parse_error", error="parse", raw=...

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
FINISH = "finish"          # action ที่ใช้จบงาน
PARSE_ERROR = "parse_error"  # action ของ step ที่ LLM ตอบไม่เป็น JSON


def _system_prompt(tool_schemas: list) -> str:
    lines = [f"- {t['name']}({', '.join(t['args'])}): {t['desc']}" for t in tool_schemas]
    tools_txt = "\n".join(lines)
    return (
        "คุณคือ AI agent สายเทคที่ลงมือทำงานเป็นขั้น ๆ ด้วยเครื่องมือที่มี.\n"
        f"เครื่องมือที่ใช้ได้:\n{tools_txt}\n\n"
        "กติกาการตอบ: ตอบเป็น JSON บรรทัดเดียวเท่านั้น ไม่มีข้อความอื่นนอก JSON:\n"
        '  เรียกเครื่องมือ: {"thought":"เหตุผลสั้น","tool":"ชื่อ","args":{...}}\n'
        '  จบงาน:         {"thought":"สรุปสั้น","action":"finish","final":"คำตอบสุดท้ายให้ผู้ใช้"}\n'
        "ทำทีละขั้น: อ่าน/ตรวจก่อนสรุป. อย่าเดาเนื้อไฟล์ — ใช้ read_file ดูจริง. "
        "เมื่อมั่นใจแล้วค่อยตอบ finish."
    )


def _parse(reply: str) -> dict:
    """ดึง JSON ก้อนแรกจากคำตอบ LLM (เผื่อมีข้อความห่อ) — คืน dict หรือโยน ValueError"""
    s = reply.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("ไม่พบ JSON ในคำตอบ")
    return json.loads(s[start:end + 1])


def _is_finish(action: dict) -> bool:
    """จบเมื่อ action == "finish" หรือมีคีย์ "final" (alias เดิม คงไว้ให้โค้ด/เทสต์เก่าไม่พัง)"""
    return action.get("action") == FINISH or action.get("tool") == FINISH or "final" in action


def _final_text(action: dict) -> str:
    """ดึงคำตอบสุดท้าย: จากคีย์ final ตรง ๆ หรือจาก input.final"""
    if "final" in action:
        return str(action.get("final") or "")
    inp = action.get("input")
    if isinstance(inp, dict):
        return str(inp.get("final") or "")
    return ""


def _name_args(action: dict) -> tuple:
    """คืน (ชื่อ tool/action, args dict) รองรับทั้ง tool/args และ action/input"""
    name = str(action.get("action") or action.get("tool") or "")
    raw = action.get("input") if "input" in action else action.get("args")
    return name, (raw if isinstance(raw, dict) else {})


def _run_tool(registry: dict, name: str, args: dict) -> str:
    """รัน tool ผ่าน registry — ความผิดพลาดกลายเป็น observation ไม่ crash"""
    fn = registry.get(name)
    if fn is None:
        return f"ไม่รู้จักเครื่องมือ '{name}' (มี: {', '.join(registry)})"
    try:
        return fn(args)
    except tools_mod.ToolError as e:
        return f"[tool error] {e}"


class EchoBackend:
    """สมองปลอม offline: คืนคำตอบ (action) ที่เตรียมไว้ตามลำดับ ไม่เรียกเครือข่ายเลย.

    actions: list ของ dict (แปลงเป็น JSON ให้) หรือ str JSON.
    เมื่อหมดลำดับจะคืน finish อัตโนมัติ กันวนไม่จบ.
    """

    EXHAUSTED_TEXT = "echo: หมดลำดับ action"

    def __init__(self, actions: list) -> None:
        self._queue = [a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)
                       for a in actions]
        self._pos = 0
        self.calls = 0

    def __call__(self, messages: list) -> str:
        self.calls += 1
        if self._pos < len(self._queue):
            reply = self._queue[self._pos]
            self._pos += 1
            return reply
        return json.dumps({"thought": "echo", "action": FINISH,
                           "final": self.EXHAUSTED_TEXT}, ensure_ascii=False)


def run(project_root, task: str, workspace, model: str = DEFAULT_MODEL,
        max_steps: int = DEFAULT_MAX_STEPS, allowed_commands=None, approvals_root=None,
        generate_fn=None, extra_system: str = None, net_ctx=None) -> dict:
    """รัน agent 1 งาน — คืน {final, steps:[...], stopped_reason}
    - workspace: โฟลเดอร์ที่ agent ทำงานได้ (sandbox confine ไว้)
    - approvals_root: ถ้าให้มา → เปิด tool 'เสนอ' (P6) เขียนไฟล์/รันคำสั่งที่ต้องรอคนอนุมัติ
    - generate_fn: ถ้าให้มา → ใช้ "สมอง" นี้แทน backend ตาม config (callable(messages)->str)
      ให้ bot วิ่ง ReAct ผ่าน connection ที่เลือกได้ (ไม่ผูกกับ MODEL_BACKEND กลาง)
      ใช้ EchoBackend(...) เพื่อรันแบบ offline ตามลำดับที่เตรียมไว้
    - extra_system: system prompt เสริม (เช่น persona ของ skill) ต่อท้าย tool-protocol
    - steps: log ทุกขั้น (ดูฟิลด์ใน docstring ของโมดูล) ไว้ตรวจย้อน
    - stopped_reason: "final" (จบด้วย finish) | "max_steps"
    """
    task = (task or "").strip()
    if not task:
        raise ValueError("ต้องระบุ task")
    sb = tools_mod.Sandbox(workspace, allowed_commands or tools_mod.DEFAULT_ALLOWED_COMMANDS)
    registry = tools_mod.build_registry(sb, approvals_root=approvals_root, net_ctx=net_ctx)
    schemas = list(tools_mod.TOOL_SCHEMAS)
    if approvals_root is not None:
        schemas = schemas + tools_mod.PROPOSE_SCHEMAS
    if net_ctx is not None:
        schemas = schemas + tools_mod.NET_SCHEMAS
    # เลือกสมอง: generate_fn ที่ส่งมา (เช่น connection ของ bot) หรือ backend ตาม config (เดิม)
    gen = generate_fn if generate_fn is not None else \
        (lambda msgs: model_backend.generate(project_root, model, msgs))

    messages = [{"role": "system", "content": _system_prompt(schemas)}]
    if extra_system:
        messages.append({"role": "system", "content": extra_system})
    messages.append({"role": "user", "content": f"งาน: {task}"})
    steps: list = []
    for _ in range(max_steps):
        idx = len(steps)
        reply = gen(messages)
        try:
            action = _parse(reply)
        except ValueError:
            # LLM ตอบไม่เป็น JSON — ป้อน error กลับให้แก้ (ไม่ทิ้งงาน)
            hint = "ตอบเป็น JSON ตามรูปแบบที่กำหนดเท่านั้น"
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": hint})
            steps.append({"step": idx, "thought": "", "action": PARSE_ERROR, "input": {},
                          "observation": hint, "error": "parse", "raw": reply[:500]})
            continue

        thought = str(action.get("thought", "") or "")
        if _is_finish(action):
            final = _final_text(action)
            steps.append({"step": idx, "thought": thought, "action": FINISH,
                          "input": {"final": final}, "observation": "", "final": final})
            return {"final": final, "steps": steps, "stopped_reason": "final"}

        name, args = _name_args(action)
        obs = _run_tool(registry, name, args)
        steps.append({"step": idx, "thought": thought, "action": name, "input": args,
                      "observation": obs, "tool": name, "args": args})
        # ป้อนผลกลับให้ agent คิดต่อ
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": f"ผลจาก {name}:\n{obs}"})

    return {"final": None, "steps": steps, "stopped_reason": "max_steps"}
