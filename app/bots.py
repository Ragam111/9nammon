"""bots.py — "Bot" = Skill ที่เอาไปรันกับข้อความเข้า (หน้าต่างให้ automation/n8n เรียก)

โจทย์ (ตามที่ user สั่ง): Skills → AI Agent → Bot. Bot หนึ่งตัวจับ skill หนึ่งตัวมา "ให้บริการ"
ผ่าน endpoint เดียว — n8n/เว็บ/มือถือยิง POST ข้อความเข้ามา แล้ว bot ตอบกลับโดยใช้
system prompt + สมอง (connection) ของ skill นั้น. ต่อยอดจากคิวงาน agent/n8n ที่มีอยู่.

flow การรัน:
  bot.run(input) → หยิบ skill ของ bot → หยิบ connection (สมอง) ของ skill
                 → ประกอบ messages (system=skill prompt, user=input)
                 → connections.chat(...) ได้คำตอบ → นับ run_count → คืนคำตอบ

เก็บ bots.json (gitignored, atomic, lock). stdlib ล้วน.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from app import connections, skills_store, store_schema
from app.agent import core as agent_core

STORE_FILE = "bots.json"
SCHEMA_VERSION = 1       # ยังไม่เคยเปลี่ยน schema — baseline
MIGRATIONS = []
AGENT_WORKSPACE_DIR = "agent_workspace"   # sandbox ของ bot-agent (ไม่ให้เห็น repo/secret)
MAX_RECORDS = 500

_lock = threading.Lock()


class BotError(Exception):
    """input ผิด/ไม่พบ/รันไม่ได้ — ผู้เรียกแปลงเป็น 400/404/502 ได้"""


def _path(project_root) -> Path:
    return Path(project_root) / STORE_FILE


def _load(project_root) -> list:
    recs, upgraded = store_schema.load(_path(project_root), SCHEMA_VERSION, MIGRATIONS)
    if upgraded:
        _save(project_root, recs)
    return recs


def _save(project_root, recs: list) -> None:
    p = _path(project_root)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(store_schema.dumps(recs, SCHEMA_VERSION), encoding="utf-8")
        tmp.replace(p)
    except OSError as e:
        print(f"[bots][error] เขียน {STORE_FILE} ไม่ได้: {e}")


def list_bots(project_root) -> list:
    with _lock:
        return [dict(r) for r in _load(project_root)]


def get(project_root, bot_id: str):
    with _lock:
        for r in _load(project_root):
            if r.get("id") == bot_id:
                return dict(r)
    return None


def add(project_root, name: str, skill_id: str, description: str = "",
        enabled: bool = True) -> dict:
    """เพิ่ม bot — ผูกกับ skill ที่มีอยู่จริง. คืน record. input ผิด → BotError"""
    name = (name or "").strip()
    if not name:
        raise BotError("ต้องระบุชื่อ bot")
    skill_id = (skill_id or "").strip()
    if not skill_id:
        raise BotError("ต้องระบุ skill_id ที่ bot นี้จะใช้")
    if skills_store.get(project_root, skill_id) is None:
        raise BotError("ไม่พบ skill ที่อ้างถึง (skill_id ผิด)")
    rec = {
        "id": "bot-" + uuid.uuid4().hex[:12],
        "name": name,
        "description": (description or "").strip(),
        "skill_id": skill_id,
        "enabled": bool(enabled),
        "run_count": 0,
        "last_run_at": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with _lock:
        recs = _load(project_root)
        if any(r.get("name") == name for r in recs):
            raise BotError(f"มี bot ชื่อ {name!r} อยู่แล้ว")
        recs.append(rec)
        if len(recs) > MAX_RECORDS:
            recs = recs[-MAX_RECORDS:]
        _save(project_root, recs)
    return rec


def update(project_root, bot_id: str, fields: dict) -> dict:
    fields = fields or {}
    with _lock:
        recs = _load(project_root)
        rec = next((r for r in recs if r.get("id") == bot_id), None)
        if rec is None:
            raise BotError("ไม่พบ bot นี้")
        if "name" in fields and str(fields["name"]).strip():
            new_name = str(fields["name"]).strip()
            if any(r.get("name") == new_name and r.get("id") != bot_id for r in recs):
                raise BotError(f"มี bot ชื่อ {new_name!r} อยู่แล้ว")
            rec["name"] = new_name
        if "description" in fields:
            rec["description"] = str(fields["description"]).strip()
        if "skill_id" in fields and str(fields["skill_id"]).strip():
            sid = str(fields["skill_id"]).strip()
            if skills_store.get(project_root, sid) is None:
                raise BotError("ไม่พบ skill ที่อ้างถึง (skill_id ผิด)")
            rec["skill_id"] = sid
        if "enabled" in fields:
            rec["enabled"] = bool(fields["enabled"])
        rec["updated_at"] = time.time()
        _save(project_root, recs)
        return dict(rec)


def remove(project_root, bot_id: str) -> bool:
    with _lock:
        recs = _load(project_root)
        new = [r for r in recs if r.get("id") != bot_id]
        if len(new) == len(recs):
            return False
        _save(project_root, new)
        return True


def _bump_run(project_root, bot_id: str) -> None:
    """นับจำนวนครั้งที่รัน + เวลาล่าสุด (แยก lock สั้น ๆ หลังได้คำตอบแล้ว)"""
    with _lock:
        recs = _load(project_root)
        rec = next((r for r in recs if r.get("id") == bot_id), None)
        if rec is None:
            return
        rec["run_count"] = int(rec.get("run_count", 0)) + 1
        rec["last_run_at"] = time.time()
        _save(project_root, recs)


def _agent_workspace(project_root, workspace: str) -> Path:
    """โฟลเดอร์ sandbox ของ bot-agent — confine ใต้ project_root/agent_workspace เท่านั้น
    (กัน bot ที่ automation ยิงเข้ามา อ่าน repo/config.json ที่มี secret)"""
    base = (Path(project_root) / AGENT_WORKSPACE_DIR).resolve()
    base.mkdir(parents=True, exist_ok=True)
    ws = (base / (workspace or ".")).resolve()
    if ws != base and base not in ws.parents:
        raise BotError("workspace หลุดนอก agent_workspace (ปฏิเสธ)")
    return ws


def run(project_root, bot_id: str, user_input: str, model: str = "",
        workspace: str = ".") -> dict:
    """รัน bot กับข้อความเข้า — คืน {bot, skill, mode, output, ...}. หาย/ปิด/ต่อไม่ได้ → BotError.
    model ว่าง → ใช้ของ skill → ของ connection (ตามลำดับ).
    skill.mode == 'agent' → วิ่ง ReAct (เรียก tools ใน sandbox) แทนตอบแชตตรง."""
    user_input = (user_input or "").strip()
    if not user_input:
        raise BotError("ต้องระบุข้อความเข้า (input)")
    bot = get(project_root, bot_id)
    if bot is None:
        raise BotError("ไม่พบ bot นี้")
    if not bot.get("enabled", True):
        raise BotError(f"bot {bot.get('name')!r} ถูกปิดอยู่")
    skill = skills_store.get(project_root, bot.get("skill_id", ""))
    if skill is None:
        raise BotError("skill ของ bot นี้หายไป (ถูกลบ?) — แก้ไข bot ให้ชี้ skill ใหม่")
    conn_id = skill.get("connection_id", "")
    if not conn_id:
        raise BotError("skill นี้ยังไม่ได้ผูก connection (สมอง) — ตั้งค่า skill ก่อน")
    use_model = (model or "").strip() or skill.get("model", "")

    if skill.get("mode") == skills_store.MODE_AGENT:
        ws = _agent_workspace(project_root, workspace)
        gen = connections.make_generate_fn(project_root, conn_id, model=use_model,
                                           options=skills_store.options_for(skill))
        # tools_write → เปิด tool 'เสนอ' (P6): เขียนไฟล์/รันคำสั่งต้องรอคนอนุมัติที่ /dev
        approvals_root = project_root if skill.get("tools_write") else None
        try:
            res = agent_core.run(
                project_root, user_input, workspace=str(ws),
                model=use_model or agent_core.DEFAULT_MODEL,
                max_steps=int(skill.get("max_steps") or skills_store.DEFAULT_MAX_STEPS),
                approvals_root=approvals_root, generate_fn=gen,
                extra_system=skill.get("system_prompt", ""))
        except connections.ConnectionError as e:
            raise BotError(f"สมองตอบไม่ได้: {e}") from e
        _bump_run(project_root, bot_id)
        return {"bot": bot["name"], "skill": skill["name"], "mode": "agent",
                "output": res.get("final") or "(ไม่จบใน max_steps)",
                "steps": res.get("steps", []), "stopped_reason": res.get("stopped_reason")}

    # chat mode (เดิม): system+user → คำตอบทีเดียว
    messages = skills_store.build_messages(skill, user_input)
    try:
        output = connections.chat(project_root, conn_id, messages, model=use_model,
                                  options=skills_store.options_for(skill))
    except connections.ConnectionError as e:
        raise BotError(f"สมองตอบไม่ได้: {e}") from e
    _bump_run(project_root, bot_id)
    return {"bot": bot["name"], "skill": skill["name"], "mode": "chat", "output": output}


def run_stream(project_root, bot_id: str, user_input: str, model: str = ""):
    """stream คำตอบของ bot โหมด chat (yield chunk ทีละคำ). โหมด agent สตรีมไม่ได้ (ReAct
    ไม่ใช่ token stream) → BotError ให้ใช้ run() ปกติ. validate ก่อนเริ่ม yield."""
    user_input = (user_input or "").strip()
    if not user_input:
        raise BotError("ต้องระบุข้อความเข้า (input)")
    bot = get(project_root, bot_id)
    if bot is None:
        raise BotError("ไม่พบ bot นี้")
    if not bot.get("enabled", True):
        raise BotError(f"bot {bot.get('name')!r} ถูกปิดอยู่")
    skill = skills_store.get(project_root, bot.get("skill_id", ""))
    if skill is None:
        raise BotError("skill ของ bot นี้หายไป (ถูกลบ?) — แก้ไข bot ให้ชี้ skill ใหม่")
    if skill.get("mode") == skills_store.MODE_AGENT:
        raise BotError("bot โหมด agent สตรีมไม่ได้ — ใช้ /api/bots/run (คืน steps)")
    conn_id = skill.get("connection_id", "")
    if not conn_id:
        raise BotError("skill นี้ยังไม่ได้ผูก connection (สมอง) — ตั้งค่า skill ก่อน")
    use_model = (model or "").strip() or skill.get("model", "")
    try:
        gen = connections.chat_stream(
            project_root, conn_id, skills_store.build_messages(skill, user_input),
            model=use_model, options=skills_store.options_for(skill))
    except connections.ConnectionError as e:
        raise BotError(f"สมองตอบไม่ได้: {e}") from e

    def _wrap():
        yield from gen                 # ConnectionError ระหว่างสตรีม (BackendError) ลอยออกไปให้ผู้เรียก
        _bump_run(project_root, bot_id)  # นับหลังสตรีมจบครบ
    return _wrap()
