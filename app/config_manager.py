"""
config_manager.py — Hot-Swap Config: เก็บ API key ลง config.json ต่อโปรเจกต์
ไม่ต้อง set environment variable เองเสมอไป (แต่ env var ยังใช้ได้ ถ้าไม่มีใน config.json)

ลำดับความสำคัญ: config.json > environment variable

**สำคัญ (Rule ข้อ 23)**: config.json มี secret จริง ห้าม commit เข้า git หรือแนบ
ไปกับไฟล์ที่ส่งให้คนอื่น — ต้องอยู่ใน .gitignore เสมอ ห้าม print ค่า key เต็มๆ

ค่าที่เป็น API key / token / password ถูก seal ผ่าน ``app.secrets`` ก่อนเขียน
(Windows DPAPI CurrentUser, นอก Windows เป็น secrets.bin โหมด 0600 — ดู
secrets.py). อ่านแล้วได้ plaintext เหมือนเดิม. ค่า plaintext เก่าถูก seal
ตอนอ่าน แล้วเขียนกลับ — ถ้า seal ไม่ได้ ค่าเดิมยังอยู่ ไม่ทิ้ง.

Interface ที่ local_coder.py เรียกใช้ตรงๆ:
    get_key(project_root, key_name) -> str | None
    set_key(project_root, key_name, value) -> None
    prompt_for_key(project_root, key_name) -> str | None
"""

import json
import os
from pathlib import Path

try:
    from app import secrets
except ImportError:  # ถูก import เป็น config_manager จาก sys.path ที่ชี้ app/
    import secrets  # type: ignore

CONFIG_FILE_NAME = "config.json"


def _config_path(project_root: Path) -> Path:
    return project_root / CONFIG_FILE_NAME


def _write_config(project_root: Path, config: dict) -> None:
    path = _config_path(project_root)
    text = json.dumps(config, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _seal_plaintext_secrets(project_root: Path, config: dict) -> bool:
    """Move plaintext credentials into the secrets store. Returns True if the
    dict changed. On failure the original string stays in ``config``."""
    changed = False
    for key_name, value in list(config.items()):
        if not secrets.is_secret_name(key_name) or not isinstance(value, str) or value == "":
            continue
        if secrets.ref_name(value) is not None:
            continue
        entry = secrets.config_entry_name(key_name)
        try:
            secrets.store(project_root, entry, value)
        except secrets.SecretError as exc:
            print(
                f"[secrets][warn] เข้ารหัส {key_name} ไม่ได้: {type(exc).__name__} "
                "— คงค่าเดิมไว้"
            )
            continue
        config[key_name] = secrets.make_ref(entry)
        changed = True
    return changed


def _load_config(project_root: Path) -> dict:
    path = _config_path(project_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[config][warn] อ่าน {CONFIG_FILE_NAME} ไม่ได้: {e} — ถือว่าว่างเปล่า")
        return {}
    if not isinstance(data, dict):
        return {}
    if _seal_plaintext_secrets(project_root, data):
        try:
            _write_config(project_root, data)
        except OSError as e:
            # secrets.bin already has the copy. Leave the JSON rewrite for the
            # next read; the in-memory refs still resolve.
            print(f"[config][error] เขียน {CONFIG_FILE_NAME} หลัง seal ไม่ได้: {e}")
    return data


def _resolve(project_root: Path, key_name: str, value):
    """Plaintext for callers. A sealed ref that cannot be opened does not fall
    through to the environment (the value exists, it just cannot be read) and
    is not deleted."""
    name = secrets.ref_name(value)
    if name is None:
        return value
    try:
        plain = secrets.reveal(project_root, name)
    except secrets.SecretError:
        print(f"[secrets][warn] อ่าน {key_name} ไม่ได้ — ไม่เขียนทับไฟล์ลับ")
        return None
    if plain is None:
        print(f"[secrets][warn] ถอด {key_name} ไม่ได้ — ไม่ลบค่าที่เก็บไว้")
        return None
    return plain


def get_key(project_root: Path, key_name: str) -> str | None:
    """หา key: เช็ค config.json ก่อน (ลำดับความสำคัญสูงกว่า) แล้วค่อย fallback env var"""
    config = _load_config(project_root)
    if key_name in config:
        value = _resolve(project_root, key_name, config.get(key_name))
        if secrets.ref_name(config.get(key_name)) is not None:
            return value or None
        if value:
            return value
    return os.environ.get(key_name) or None


def set_key(project_root: Path, key_name: str, value: str) -> None:
    """บันทึก key ลง config.json — ใช้ได้ทันทีรอบถัดไปที่เรียก get_key โดยไม่ต้อง
    restart โปรแกรม (hot-swap). credential ถูก seal; ถ้า seal ไม่ได้ เก็บ plaintext
    ไว้ก่อน เพื่อไม่ให้ค่าที่ผู้ใช้เพิ่งกรอกหาย"""
    config = _load_config(project_root)
    if secrets.is_secret_name(key_name):
        if value:
            entry = secrets.config_entry_name(key_name)
            try:
                secrets.store(project_root, entry, value)
                config[key_name] = secrets.make_ref(entry)
            except secrets.SecretError as exc:
                print(
                    f"[secrets][warn] เข้ารหัส {key_name} ไม่ได้: {type(exc).__name__} "
                    "— เก็บ plaintext ไว้"
                )
                config[key_name] = value
        else:
            try:
                secrets.delete(project_root, secrets.config_entry_name(key_name))
            except secrets.SecretError as exc:
                print(
                    f"[secrets][warn] ลบ {key_name} ที่ seal ไว้ไม่ได้: {type(exc).__name__} "
                    "— ไม่เขียนทับไฟล์ลับ"
                )
            config[key_name] = value
    else:
        config[key_name] = value
    try:
        _write_config(project_root, config)
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
