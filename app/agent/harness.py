"""harness.py — "โครงให้คนเก่งหลายคนทำงานร่วมกัน" ต่อ LLM qwen2.5:0.5b (ผ่าน model_backend)

Harness = ตัวประสานงาน: รับโจทย์ → ให้ persona ที่เลือกคิด → (โหมดสภา) รวมหลายมุมแล้ว
ให้ประธานสังเคราะห์เป็นข้อสรุปเดียว. ไม่ผูกกับ runtime ตัวใด — เรียกผ่าน model_backend
(สลับ Ollama/cloud/cluster ได้ด้วย config เดิม).

ปรัชญาเดิม: stdlib, degrade graceful (LLM ล่ม → โยน BackendError ให้ผู้เรียกจัดการ),
ทำทีละขั้น. โหมดเริ่มต้นคือ "ที่ปรึกษา" (ให้ความเห็น) ยังไม่ลงมือแตะระบบ — tool-use/
ลงมือจริงเป็นขั้นถัดไป (ดู docs/AGENT_TECH_PLAN.md P1-P2) ที่ต้องมี sandbox ก่อน

interface:
    ask(project_root, persona_id, task, model=DEFAULT_MODEL) -> {persona, reply}
    council(project_root, task, personas=None, model=DEFAULT_MODEL, chair=None)
        -> {task, opinions: [{persona, name, reply}], synthesis, chair}
"""

from __future__ import annotations

from app import model_backend
from app.agent import personas

DEFAULT_MODEL = "qwen2.5:0.5b"   # ตัวเล็ก รันไหวบนเครื่องสเปกต่ำ (ต่อได้ตามที่สั่ง)
MAX_TASK_CHARS = 8000


def _messages(persona_id: str, task: str, extra_user: str = "") -> list:
    msgs = [{"role": "system", "content": personas.system_prompt(persona_id)},
            {"role": "user", "content": task}]
    if extra_user:
        msgs.append({"role": "user", "content": extra_user})
    return msgs


def ask(project_root, persona_id: str, task: str, model: str = DEFAULT_MODEL) -> dict:
    """ถาม persona เดียว — คืน {persona, name, reply}. task ว่าง → ValueError"""
    task = (task or "").strip()
    if not task:
        raise ValueError("ต้องระบุ task/โจทย์")
    if len(task) > MAX_TASK_CHARS:
        raise ValueError(f"task ยาวเกิน {MAX_TASK_CHARS} ตัวอักษร")
    p = personas.get(persona_id)   # โยน ValueError ถ้าไม่รู้จัก
    reply = model_backend.generate(project_root, model, _messages(persona_id, task))
    return {"persona": p["id"], "name": p["name"], "reply": reply}


def council(project_root, task: str, personas_ids=None, model: str = DEFAULT_MODEL,
            chair: str | None = None) -> dict:
    """ประชุมสภา: ให้หลาย persona ให้ความเห็นมุมตัวเอง แล้วประธานสังเคราะห์เป็นข้อสรุป

    personas_ids: รายการ id (None = ใช้ชุดเริ่มต้นที่หลากมุม); chair: id ประธาน (None = CHAIR_ID)
    """
    task = (task or "").strip()
    if not task:
        raise ValueError("ต้องระบุ task/โจทย์")
    ids = personas_ids or ["elon", "jobs", "carmack", "9arm"]
    chair_id = chair or personas.CHAIR_ID

    opinions = []
    for pid in ids:
        p = personas.get(pid)
        reply = model_backend.generate(project_root, model, _messages(pid, task))
        opinions.append({"persona": p["id"], "name": p["name"], "reply": reply})

    # ประธานสังเคราะห์: ป้อนทุกความเห็นให้ chair ตัดสินเป็นข้อสรุปเดียว
    board = "\n\n".join(f"[{o['name']}]\n{o['reply']}" for o in opinions)
    synth_task = (f"โจทย์: {task}\n\n"
                  f"ความเห็นจากที่ปรึกษาหลายมุม:\n{board}\n\n"
                  f"สังเคราะห์เป็นข้อสรุปเดียวที่ลงมือได้: ชี้จุดที่เห็นตรงกัน จุดที่ขัดกัน "
                  f"แล้วฟันธงว่าควรทำอะไรก่อน 1-3 ข้อ พร้อมเหตุผลสั้น")
    synthesis = model_backend.generate(
        project_root, model,
        [{"role": "system", "content": personas.system_prompt(chair_id)},
         {"role": "user", "content": synth_task}])

    return {"task": task, "opinions": opinions, "synthesis": synthesis, "chair": chair_id}
