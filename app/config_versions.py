"""config_versions.py — เวอร์ชัน + ย้อนกลับ (rollback) ของ config.json

ทำไม: config.json คือจุดที่ "พังแล้วลูกค้าเจอทันที" — ตั้ง backend url/model/flag ผิด
ปุ๊บ ระบบเพี้ยนทั้งระบบ. ฟีเจอร์นี้เก็บ snapshot ของ config ไว้เป็นเวอร์ชัน แล้ว
*ย้อนกลับได้เร็ว* เมื่อปล่อยของพลาด/เจอ incident — ลดเวลาที่ลูกค้าเจอของเสีย

หลักความปลอดภัย:
- credential ไม่ถูกคัดลอกลงไฟล์เวอร์ชัน — snapshot เก็บ ``$lca_secret_ref``
  ที่ชี้ค่าใน secrets.bin (DPAPI บน Windows / ไฟล์ 0600 นอก Windows)
- ไฟล์เวอร์ชันยังอยู่ใน .gitignore (Rule 23) เพราะเคยมี secret เต็ม และยังมีตัวชี้
- list_versions คืน *metadata เท่านั้น* (id/เวลา/label/จำนวน key) ไม่เผยค่า secret
- rollback จะ snapshot ของปัจจุบันก่อนเสมอ → ย้อนของ rollback ได้อีก
- plaintext เก่าในไฟล์เวอร์ชันถูกย้ายเข้า secrets.bin ตอนอ่าน แล้วแทนที่ด้วย ref
  ถ้าย้ายไม่ได้ ค่าเดิมยังอยู่ในไฟล์ ไม่ถูกทิ้ง

stdlib ล้วน. เก็บเวอร์ชันล่าสุด MAX_VERSIONS อัน (วนทับของเก่าสุด)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app import config_manager

try:
    from app import secrets
except ImportError:  # import ตรงจากโฟลเดอร์ app/
    import secrets  # type: ignore

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
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    changed = False
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            continue
        cfg = entry.get("config")
        if not isinstance(cfg, dict):
            continue
        vid = entry.get("id")
        if not isinstance(vid, str) or not vid:
            vid = f"legacy-{index}"
        if _seal_legacy_snapshot(project_root, vid, cfg):
            changed = True
    if changed:
        try:
            _save(project_root, data)
        except OSError as exc:
            print(
                f"[config][warn] เขียน {VERSIONS_FILE} หลัง seal ไม่ได้: "
                f"{type(exc).__name__} — ค่าเดิมยังอยู่ในไฟล์"
            )
    return data


def _save(project_root, versions: list) -> None:
    path = _versions_path(project_root)
    text = json.dumps(versions, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _copy_secret(project_root, preferred: str, plaintext: str) -> str | None:
    """Copy a secret without overwriting a different existing entry.
    None means the copy failed and the caller must keep the original value."""
    try:
        return secrets.store_keeping_existing(project_root, preferred, plaintext)
    except secrets.SecretError as exc:
        print(
            f"[secrets][warn] คัดลอก {preferred} ไม่ได้: {type(exc).__name__} "
            "— คงค่าเดิมไว้"
        )
        return None


def _seal_legacy_snapshot(project_root, version_id: str, cfg: dict) -> bool:
    """Plaintext credentials already sitting in a snapshot file → refs.
    Does not replace a live ``config:`` entry that already exists."""
    changed = False
    for key_name, value in list(cfg.items()):
        if not secrets.is_secret_name(key_name) or not isinstance(value, str) or value == "":
            continue
        stored = _copy_secret(
            project_root, secrets.snapshot_entry_name(version_id, key_name), value
        )
        if stored is None:
            continue
        cfg[key_name] = secrets.make_ref(stored)
        changed = True
        live = secrets.config_entry_name(key_name)
        try:
            if not secrets.has_entry(project_root, live):
                secrets.store(project_root, live, value)
        except secrets.SecretError as exc:
            print(
                f"[secrets][warn] คัดลอก {key_name} ไปค่าปัจจุบันไม่ได้: "
                f"{type(exc).__name__} — ค่าใน snapshot ยังอยู่"
            )
    return changed


def _freeze_for_snapshot(project_root, version_id: str, cfg: dict) -> dict:
    """Snapshot dict with credentials replaced by refs. Settings stay as-is.
    If a credential cannot be copied, the original value is kept so it is not lost."""
    frozen = {}
    for key_name, value in cfg.items():
        if not secrets.is_secret_name(key_name):
            frozen[key_name] = value
            continue
        plain = None
        if secrets.ref_name(value):
            try:
                plain = secrets.reveal(project_root, secrets.ref_name(value))
            except secrets.SecretError:
                plain = None
        elif isinstance(value, str) and value:
            plain = value
        if not plain:
            frozen[key_name] = value
            continue
        stored = _copy_secret(
            project_root, secrets.snapshot_entry_name(version_id, key_name), plain
        )
        frozen[key_name] = secrets.make_ref(stored) if stored else value
    return frozen


def _meta(v: dict) -> dict:
    """metadata ปลอดภัย (ไม่เผย config เต็ม/ไม่เผย secret)"""
    return {"id": v.get("id"), "ts": v.get("ts"), "label": v.get("label", ""),
            "keys": len(v.get("config", {}))}


def snapshot(project_root, label: str = "") -> dict:
    """เก็บ snapshot ของ config.json ปัจจุบันเป็นเวอร์ชันใหม่ — คืน metadata.
    credential ถูกคัดลอกไปชื่อ snapshot:<id>:<key> แล้วในไฟล์เหลือแต่ ref"""
    cfg = dict(config_manager._load_config(Path(project_root)))
    versions = _load(project_root)
    # id อิงเวลา (ms) + กันชนกันถ้าเรียกถี่ ด้วยการต่อ suffix
    vid = f"v{int(time.time() * 1000)}"
    existing = {v.get("id") for v in versions}
    n = 0
    while vid in existing:
        n += 1
        vid = f"v{int(time.time() * 1000)}-{n}"
    entry = {
        "id": vid,
        "ts": int(time.time()),
        "label": str(label)[:120],
        "config": _freeze_for_snapshot(project_root, vid, cfg),
    }
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
    config_manager._write_config(Path(project_root), target.get("config") or {})
    return {"restored": version_id, "keys": len(target.get("config", {})), "backup": backup["id"]}
