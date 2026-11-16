"""skills_store.py — ทะเบียน "Skills" (prompt + สมองสำเร็จรูป ใช้ซ้ำได้)

โจทย์ (ตามที่ user สั่ง): เพิ่มฟีเจอร์ Skills / AI Agent / Bot บนคอนโซล.
Skill = ชุดคำสั่งสำเร็จรูป 1 อย่าง = system prompt + ผูกกับ connection (สมอง) + model +
พารามิเตอร์ (temperature...). สร้างครั้งเดียว เอาไปใช้ซ้ำใน Playground/Bot ได้เรื่อย ๆ.

เช่น skill "แปลไทย→อังกฤษ", "สรุปโค้ด", "ตอบลูกค้าสุภาพ" — แต่ละอันจำ prompt + สมองไว้.

เก็บ skills.json (gitignored, atomic, lock). stdlib ล้วน. ไม่เรียก LLM เอง (แค่เก็บนิยาม) —
การรันจริงอยู่ที่ bots.run() / console playground ที่หยิบ skill ไปประกอบ messages.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from app import store_schema

STORE_FILE = "skills.json"
MAX_RECORDS = 500
MODE_CHAT = "chat"
MODE_AGENT = "agent"
VALID_MODES = (MODE_CHAT, MODE_AGENT)
DEFAULT_MAX_STEPS = 6
MAX_STEPS_CAP = 20        # กันลูปยาวเกิน (กิน token/เวลา)

_lock = threading.Lock()


def _migrate_v1_to_v2(records: list) -> list:
    """v1→v2: เติม field โหมด agent (mode/max_steps/tools_write) ให้ record เก่าที่ยังไม่มี —
    เขียนลงไฟล์จริง (ไม่ใช่แค่ .get ตอนอ่าน) เพื่อให้ schema บนดิสก์ตรงรูปแบบใหม่ถาวร"""
    for r in records:
        r.setdefault("mode", MODE_CHAT)
        r.setdefault("max_steps", DEFAULT_MAX_STEPS)
        r.setdefault("tools_write", False)
    return records


def _migrate_v2_to_v3(records: list) -> list:
    """v2→v3: เติม tools_net (เปิด tool เครือข่าย http_get/call_connection) ให้ record เก่า"""
    for r in records:
        r.setdefault("tools_net", False)
    return records


# เวอร์ชัน schema ของ skills.json — เพิ่ม migration = ต่อท้าย MIGRATIONS + บวก SCHEMA_VERSION
SCHEMA_VERSION = 3
MIGRATIONS = [_migrate_v1_to_v2, _migrate_v2_to_v3]   # index 0 = v1→v2, 1 = v2→v3


class SkillError(Exception):
    """input ผิด/ไม่พบ skill — ผู้เรียกแปลงเป็น 400/404 ได้"""


def _path(project_root) -> Path:
    return Path(project_root) / STORE_FILE


def _load(project_root) -> list:
    recs, upgraded = store_schema.load(_path(project_root), SCHEMA_VERSION, MIGRATIONS)
    if upgraded:                      # migrate แล้ว → persist ให้ไฟล์เป็น v ปัจจุบันถาวร
        _save(project_root, recs)
    return recs


def _save(project_root, recs: list) -> None:
    p = _path(project_root)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(store_schema.dumps(recs, SCHEMA_VERSION), encoding="utf-8")
        tmp.replace(p)
    except OSError as e:
        print(f"[skills][error] เขียน {STORE_FILE} ไม่ได้: {e}")


def _clamp_temp(value, default=None):
    """temperature อยู่ช่วง 0..2 — ค่านอกช่วง/ไม่ใช่ตัวเลข → default (ไม่พัง)"""
    if value is None or value == "":
        return default
    try:
        t = float(value)
    except (TypeError, ValueError):
        raise SkillError(f"temperature ต้องเป็นตัวเลข (ได้ {value!r})")
    return max(0.0, min(2.0, t))


def _norm_mode(value, default=MODE_CHAT):
    if value is None or value == "":
        return default
    m = str(value).strip().lower()
    if m not in VALID_MODES:
        raise SkillError(f"mode ต้องเป็น {list(VALID_MODES)} (ได้ {m!r})")
    return m


def _clamp_steps(value, default=DEFAULT_MAX_STEPS):
    """max_steps 1..MAX_STEPS_CAP — ว่าง/ผิด → default/โยน error"""
    if value is None or value == "":
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise SkillError(f"max_steps ต้องเป็นจำนวนเต็ม (ได้ {value!r})")
    return max(1, min(MAX_STEPS_CAP, n))


def list_skills(project_root) -> list:
    with _lock:
        return [dict(r) for r in _load(project_root)]


def get(project_root, skill_id: str):
    with _lock:
        for r in _load(project_root):
            if r.get("id") == skill_id:
                return dict(r)
    return None


def add(project_root, name: str, system_prompt: str, connection_id: str = "",
        model: str = "", description: str = "", temperature=None,
        mode: str = MODE_CHAT, max_steps=None, tools_write: bool = False,
        tools_net: bool = False) -> dict:
    """เพิ่ม skill ใหม่ — คืน record. input ผิด → SkillError.
    mode=agent → skill นี้รันเป็น ReAct (เรียก tools ใน sandbox) แทนตอบแชตตรง.
    tools_write=True → เปิด tool 'เสนอ' (P6) เขียนไฟล์/รันคำสั่ง ต้องรอคนอนุมัติที่ /dev"""
    name = (name or "").strip()
    if not name:
        raise SkillError("ต้องระบุชื่อ skill")
    system_prompt = (system_prompt or "").strip()
    if not system_prompt:
        raise SkillError("ต้องระบุ system_prompt (คำสั่งประจำตัวของ skill)")
    rec = {
        "id": "skl-" + uuid.uuid4().hex[:12],
        "name": name,
        "description": (description or "").strip(),
        "system_prompt": system_prompt,
        "connection_id": (connection_id or "").strip(),
        "model": (model or "").strip(),
        "temperature": _clamp_temp(temperature),
        "mode": _norm_mode(mode),
        "max_steps": _clamp_steps(max_steps),
        "tools_write": bool(tools_write),
        "tools_net": bool(tools_net),
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with _lock:
        recs = _load(project_root)
        if any(r.get("name") == name for r in recs):
            raise SkillError(f"มี skill ชื่อ {name!r} อยู่แล้ว")
        recs.append(rec)
        if len(recs) > MAX_RECORDS:
            recs = recs[-MAX_RECORDS:]
        _save(project_root, recs)
    return rec


def update(project_root, skill_id: str, fields: dict) -> dict:
    """แก้ skill — เฉพาะคีย์ที่รู้จัก. คืน record. ไม่พบ/ผิด → SkillError"""
    fields = fields or {}
    with _lock:
        recs = _load(project_root)
        rec = next((r for r in recs if r.get("id") == skill_id), None)
        if rec is None:
            raise SkillError("ไม่พบ skill นี้")
        if "name" in fields and str(fields["name"]).strip():
            new_name = str(fields["name"]).strip()
            if any(r.get("name") == new_name and r.get("id") != skill_id for r in recs):
                raise SkillError(f"มี skill ชื่อ {new_name!r} อยู่แล้ว")
            rec["name"] = new_name
        if "system_prompt" in fields and str(fields["system_prompt"]).strip():
            rec["system_prompt"] = str(fields["system_prompt"]).strip()
        if "description" in fields:
            rec["description"] = str(fields["description"]).strip()
        if "connection_id" in fields:
            rec["connection_id"] = str(fields["connection_id"]).strip()
        if "model" in fields:
            rec["model"] = str(fields["model"]).strip()
        if "temperature" in fields:
            rec["temperature"] = _clamp_temp(fields["temperature"], rec.get("temperature"))
        if "mode" in fields:
            rec["mode"] = _norm_mode(fields["mode"], rec.get("mode", MODE_CHAT))
        if "max_steps" in fields:
            rec["max_steps"] = _clamp_steps(fields["max_steps"], rec.get("max_steps", DEFAULT_MAX_STEPS))
        if "tools_write" in fields:
            rec["tools_write"] = bool(fields["tools_write"])
        if "tools_net" in fields:
            rec["tools_net"] = bool(fields["tools_net"])
        rec["updated_at"] = time.time()
        _save(project_root, recs)
        return dict(rec)


def remove(project_root, skill_id: str) -> bool:
    with _lock:
        recs = _load(project_root)
        new = [r for r in recs if r.get("id") != skill_id]
        if len(new) == len(recs):
            return False
        _save(project_root, new)
        return True


def build_messages(skill: dict, user_input: str) -> list:
    """ประกอบ messages สำหรับเรียกสมอง: system = คำสั่งของ skill, user = ข้อความเข้า"""
    return [
        {"role": "system", "content": skill.get("system_prompt", "")},
        {"role": "user", "content": user_input or ""},
    ]


def options_for(skill: dict) -> dict:
    """ดึงพารามิเตอร์ของ skill เป็น options ให้ backend (ตอนนี้: temperature)"""
    opts = {}
    t = skill.get("temperature")
    if t is not None:
        opts["temperature"] = t
    return opts
