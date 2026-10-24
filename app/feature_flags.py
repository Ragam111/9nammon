"""feature_flags.py — ศูนย์กลางเปิด/ปิดฟีเจอร์ของ server (สวิตช์ + มอนิเตอร์)

โจทย์ (ตามที่ user สั่ง): อยากเปิด/ปิดฟีเจอร์ของ "cloud server" ได้จากที่เดียว + เห็นสถานะ
แทนที่จะจำว่าแต่ละฟีเจอร์ใช้ config key อะไร — รวมมาไว้ทะเบียนเดียว ให้ /dev toggle ได้

ปรัชญาเดิม: อ่าน/เขียนผ่าน config_manager (config.json ที่ gitignored), ค่าเริ่มต้นปลอดภัย
(ฟีเจอร์เสี่ยง/กินแรงปิดไว้ก่อน), ไม่ผูก UI — เป็น logic ล้วน เทสง่าย

flag ค่าหนึ่ง = config key หนึ่ง (เก็บ "1"/"" ) — โมดูลฟีเจอร์เดิม (cluster_forward/watchdog)
อ่าน key เดียวกันอยู่แล้ว ตัวนี้แค่รวมศูนย์ให้ toggle + มอนิเตอร์ที่เดียว
"""

from __future__ import annotations

from app import config_manager

# ทะเบียนฟีเจอร์ที่เปิด/ปิดได้ — key (ใช้ใน API), config_key, ชื่อ, คำอธิบาย, ค่าเริ่มต้น
FEATURES = [
    {"key": "cluster_forward", "config_key": "CLUSTER_FORWARD_ENABLED",
     "name": "Cluster Forward", "desc": "ส่งงาน chat ไปทำที่ node อื่นที่พร้อม", "default": False},
    {"key": "watchdog", "config_key": "WATCHDOG_ENABLED",
     "name": "Watchdog 24/7", "desc": "เฝ้าระบบ + เตือนเมื่อผิดปกติ (สังเกต/เตือนเท่านั้น)", "default": False},
    {"key": "agent", "config_key": "AGENT_ENABLED",
     "name": "AI Agent สายเทค", "desc": "เปิดให้ใช้ agent (council/run) ผ่าน API", "default": False},
    {"key": "collect_training_data", "config_key": "COLLECT_TRAINING_DATA",
     "name": "เก็บข้อมูลเทรน", "desc": "เก็บคู่สนทนาไว้ทำ dataset (ความเป็นส่วนตัว — ปิดไว้)", "default": False},
]

_TRUE = ("1", "true", "yes", "on")
_BY_KEY = {f["key"]: f for f in FEATURES}


def is_on(project_root, key: str) -> bool:
    """ฟีเจอร์นี้เปิดอยู่ไหม — คืน default ถ้า key ไม่รู้จัก/ยังไม่ตั้ง"""
    f = _BY_KEY.get(key)
    if f is None:
        return False
    raw = config_manager.get_key(project_root, f["config_key"])
    if raw is None or str(raw).strip() == "":
        return bool(f["default"])
    return str(raw).strip().lower() in _TRUE


def status(project_root) -> list:
    """สถานะทุกฟีเจอร์ (สำหรับมอนิเตอร์/หน้า /dev) — ไม่เผยค่า config ดิบ"""
    return [{"key": f["key"], "name": f["name"], "desc": f["desc"],
             "enabled": is_on(project_root, f["key"])} for f in FEATURES]


def set_flag(project_root, key: str, enabled: bool) -> dict:
    """เปิด/ปิดฟีเจอร์ — เขียน config key. key ไม่รู้จัก → ValueError (ให้ผู้เรียกแปลงเป็น 400)"""
    f = _BY_KEY.get(key)
    if f is None:
        raise ValueError(f"ไม่รู้จักฟีเจอร์: {key!r} (มี: {', '.join(_BY_KEY)})")
    config_manager.set_key(project_root, f["config_key"], "1" if enabled else "")
    return {"key": key, "name": f["name"], "enabled": bool(enabled)}
