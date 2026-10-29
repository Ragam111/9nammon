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

import json
import threading
import time
import uuid
from pathlib import Path

from app import connections, skills_store

STORE_FILE = "bots.json"
MAX_RECORDS = 500

_lock = threading.Lock()


class BotError(Exception):
    """input ผิด/ไม่พบ/รันไม่ได้ — ผู้เรียกแปลงเป็น 400/404/502 ได้"""


def _path(project_root) -> Path:
    return Path(project_root) / STORE_FILE


def _load(project_root) -> list:
    try:
        data = json.loads(_path(project_root).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(project_root, recs: list) -> None:
    p = _path(project_root)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(recs, ensure_ascii=False), encoding="utf-8")
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


def run(project_root, bot_id: str, user_input: str, model: str = "") -> dict:
    """รัน bot กับข้อความเข้า — คืน {bot, skill, output}. ตัวไหนหาย/ปิด/ต่อไม่ได้ → BotError.
    model ว่าง → ใช้ของ skill → ของ connection (ตามลำดับ)."""
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
    messages = skills_store.build_messages(skill, user_input)
    use_model = (model or "").strip() or skill.get("model", "")
    try:
        output = connections.chat(project_root, conn_id, messages, model=use_model,
                                  options=skills_store.options_for(skill))
    except connections.ConnectionError as e:
        raise BotError(f"สมองตอบไม่ได้: {e}") from e
    _bump_run(project_root, bot_id)
    return {"bot": bot["name"], "skill": skill["name"], "output": output}
