"""config_versions.py — เวอร์ชัน + ย้อนกลับ (rollback) ของ config.json

ทำไม: config.json คือจุดที่ "พังแล้วลูกค้าเจอทันที" — ตั้ง backend url/model/flag ผิด
ปุ๊บ ระบบเพี้ยนทั้งระบบ. ฟีเจอร์นี้เก็บ snapshot ของ config ไว้เป็นเวอร์ชัน แล้ว
*ย้อนกลับได้เร็ว* เมื่อปล่อยของพลาด/เจอ incident — ลดเวลาที่ลูกค้าเจอของเสีย

หลักความปลอดภัย:
- snapshot เก็บ config เต็ม (มี secret) → ไฟล์เวอร์ชันต้องอยู่ใน .gitignore เสมอ (Rule 23)
- list_versions คืน *metadata เท่านั้น* (id/เวลา/label/จำนวน key) ไม่เผยค่า secret
- rollback จะ snapshot ของปัจจุบันก่อนเสมอ → ย้อนของ rollback ได้อีก (ไม่มีทางข้อมูลหาย)

stdlib ล้วน. เก็บเวอร์ชันล่าสุด MAX_VERSIONS อัน (วนทับของเก่าสุด)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app import config_manager

VERSIONS_FILE = "config_versions.json"
MAX_VERSIONS = 20


def _versions_path(project_root) -> Path:
    return Path(project_root) / VERSIONS_FILE


def _load(project_root) -> list:
    path = _versions_path(project_root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(project_root, versions: list) -> None:
    _versions_path(project_root).write_text(
        json.dumps(versions, ensure_ascii=False, indent=2), encoding="utf-8")


def _meta(v: dict) -> dict:
    """metadata ปลอดภัย (ไม่เผย config เต็ม/ไม่เผย secret)"""
    return {"id": v.get("id"), "ts": v.get("ts"), "label": v.get("label", ""),
            "keys": len(v.get("config", {}))}


def snapshot(project_root, label: str = "") -> dict:
    """เก็บ snapshot ของ config.json ปัจจุบันเป็นเวอร์ชันใหม่ — คืน metadata"""
    cfg = config_manager._load_config(Path(project_root))
    versions = _load(project_root)
    # id อิงเวลา (ms) + กันชนกันถ้าเรียกถี่ ด้วยการต่อ suffix
    vid = f"v{int(time.time() * 1000)}"
    existing = {v.get("id") for v in versions}
    n = 0
    while vid in existing:
        n += 1
        vid = f"v{int(time.time() * 1000)}-{n}"
    entry = {"id": vid, "ts": int(time.time()), "label": str(label)[:120], "config": cfg}
    versions.append(entry)
    versions = versions[-MAX_VERSIONS:]   # เก็บแค่ล่าสุด N อัน
    _save(project_root, versions)
    return _meta(entry)


def list_versions(project_root) -> list:
    """รายการเวอร์ชัน (ใหม่สุดก่อน) — metadata เท่านั้น ไม่เผย secret"""
    return [_meta(v) for v in reversed(_load(project_root))]


def rollback(project_root, version_id: str) -> dict:
    """ย้อน config.json กลับไปเป็นเวอร์ชันที่ระบุ
    - snapshot ของปัจจุบันก่อนเสมอ (ย้อนได้อีก ไม่มีข้อมูลหาย)
    - เขียน config.json = config ของเวอร์ชันนั้น
    คืน {restored, keys, backup} ; ไม่พบ id → ValueError"""
    versions = _load(project_root)
    target = next((v for v in versions if v.get("id") == version_id), None)
    if target is None:
        raise ValueError(f"ไม่พบเวอร์ชัน: {version_id}")
    backup = snapshot(project_root, label=f"อัตโนมัติ: ก่อน rollback → {version_id}")
    path = config_manager._config_path(Path(project_root))
    path.write_text(json.dumps(target.get("config", {}), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return {"restored": version_id, "keys": len(target.get("config", {})), "backup": backup["id"]}
