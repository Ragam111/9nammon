"""
config_manager.py — Hot-Swap Config: เก็บ API key ลง config.json ต่อโปรเจกต์
ไม่ต้อง set environment variable เองเสมอไป (แต่ env var ยังใช้ได้ ถ้าไม่มีใน config.json)

ลำดับความสำคัญ: config.json > environment variable

**สำคัญ (Rule ข้อ 23)**: config.json มี secret จริง ห้าม commit เข้า git หรือแนบ
ไปกับไฟล์ที่ส่งให้คนอื่น — ต้องอยู่ใน .gitignore เสมอ ห้าม print ค่า key เต็มๆ

Interface ที่ local_coder.py เรียกใช้ตรงๆ:
    get_key(project_root, key_name) -> str | None
    set_key(project_root, key_name, value) -> None
    prompt_for_key(project_root, key_name) -> str | None
"""

import json
import os
from pathlib import Path

CONFIG_FILE_NAME = "config.json"


def _config_path(project_root: Path) -> Path:
    return project_root / CONFIG_FILE_NAME


def _load_config(project_root: Path) -> dict:
    path = _config_path(project_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[config][warn] อ่าน {CONFIG_FILE_NAME} ไม่ได้: {e} — ถือว่าว่างเปล่า")
        return {}


def get_key(project_root: Path, key_name: str) -> str | None:
    """หา key: เช็ค config.json ก่อน (ลำดับความสำคัญสูงกว่า) แล้วค่อย fallback env var"""
    config = _load_config(project_root)
    value = config.get(key_name)
    if value:
        return value
    return os.environ.get(key_name) or None


def set_key(project_root: Path, key_name: str, value: str) -> None:
    """บันทึก key ลง config.json — ใช้ได้ทันทีรอบถัดไปที่เรียก get_key โดยไม่ต้อง
    restart โปรแกรม (hot-swap)"""
    config = _load_config(project_root)
    config[key_name] = value
    path = _config_path(project_root)
    try:
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[config][error] เขียน {CONFIG_FILE_NAME} ไม่ได้: {e}")


def prompt_for_key(project_root: Path, key_name: str) -> str | None:
    """ถามผู้ใช้กรอก key ตรงๆ ใน CLI (แทนที่จะบังคับไป set env var เอง)
    ถ้ากรอกว่างเปล่าจะไม่บันทึกอะไร คืน None"""
    try:
        value = input(f"[config] ยังไม่มี {key_name} — กรอกค่าตอนนี้เลย (Enter เพื่อข้าม): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not value:
        print(f"[config] ข้าม — จะถามใหม่ครั้งหน้าที่ต้องใช้ {key_name}")
        return None
    set_key(project_root, key_name, value)
    print(f"[config] บันทึก {key_name} แล้ว")
    return value


def list_configured_keys(project_root: Path) -> list:
    """คืนแค่ *ชื่อ* key ที่ตั้งไว้แล้ว ไม่คืนค่าจริง (ตาม Rule ข้อ 23 ห้าม print
    secret เต็มๆ ออกจอ) — ใช้เวลาต้องการโชว์สถานะว่า config อะไรตั้งไว้บ้าง"""
    config = _load_config(project_root)
    return list(config.keys())
