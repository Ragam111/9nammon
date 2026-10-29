"""store_schema.py — เวอร์ชัน + migration ของไฟล์ JSON store (กันพังตอนเปลี่ยน schema)

โจทย์ (ตามที่ user ถาม): ตอน upgrade โค้ด ถ้า schema ของไฟล์เปลี่ยน (เพิ่ม/ตัด/เปลี่ยนชื่อ
field) ไฟล์เก่าที่ผู้ใช้มีอยู่ต้องยัง "อ่านได้" และ "อัปเกรดให้ตรงรูปแบบใหม่" เองโดยไม่ต้องแก้มือ.

วิธี: ห่อ records ไว้ใน envelope ที่มีเลขเวอร์ชัน
    {"schema_version": N, "records": [...]}

- ไฟล์เก่าที่เป็น list เปล่า ๆ (ก่อนมี framework นี้) = baseline version 1
- ตอนโหลด: ตรวจรูป → อ่านเวอร์ชัน → รัน migration ทีละสเต็ปจนถึง current → คืน records
- ถ้าถูกอัปเกรด (changed) ผู้เรียกเขียนกลับ (persist) เพื่อให้ไฟล์เป็นรูปแบบใหม่ถาวร

migrations = list ของฟังก์ชัน(records)->records
    index 0 = v1→v2, index 1 = v2→v3, ...  (เพิ่ม migration = ต่อท้าย list + บวก current_version)

ปรัชญา (เหมือน interface USB/TCP): ของใหม่ต้องอ่านของเก่าได้เสมอ, ไม่ downgrade ไฟล์ที่ถูก
เขียนด้วยโค้ดใหม่กว่า (อันตราย — เสียข้อมูล), เขียนแบบ atomic (ผู้เรียกทำ) กันไฟล์พังครึ่งทาง.

stdlib ล้วน. ไม่ผูกกับ store ตัวไหน — ใช้ซ้ำได้ทุก store (connections/skills/bots/...).
"""

from __future__ import annotations

import json
from pathlib import Path

BASELINE_VERSION = 1   # ไฟล์ list เปล่า (ยังไม่เคยมีเวอร์ชัน) นับเป็นเวอร์ชันนี้


def detect(raw):
    """จากข้อมูลดิบที่ json.loads มา → คืน (version, records).
    รองรับ: list เปล่า (baseline), envelope {schema_version, records}, อย่างอื่น = ว่าง (degrade)"""
    if isinstance(raw, list):
        return BASELINE_VERSION, raw
    if isinstance(raw, dict) and isinstance(raw.get("records"), list):
        v = raw.get("schema_version")
        if not isinstance(v, int) or v < 1:
            v = BASELINE_VERSION
        return v, raw["records"]
    return BASELINE_VERSION, []   # รูปแบบพัง → ถือว่าว่าง ไม่ crash


def migrate(records, from_version, current_version, migrations):
    """รัน migration ทีละสเต็ป from_version → current_version. คืน (records, changed).
    from_version > current_version (ไฟล์ใหม่กว่าโปรแกรม) → ไม่แตะ ไม่ downgrade (กันข้อมูลหาย)."""
    if from_version >= current_version:
        return records, False
    v = from_version
    while v < current_version:
        idx = v - 1                      # v=1 → migrations[0] (v1→v2)
        fn = migrations[idx] if 0 <= idx < len(migrations) else None
        if fn is not None:
            records = fn(records)
        v += 1
    return records, True


def load(path, current_version, migrations):
    """อ่านไฟล์ → detect เวอร์ชัน → migrate → คืน (records, upgraded).
    ไฟล์หาย/พัง → ([], False). upgraded=True แปลว่าควรเขียนกลับให้เป็นรูปแบบใหม่"""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], False
    ver, records = detect(raw)
    return migrate(records, ver, current_version, migrations)


def dumps(records, current_version) -> str:
    """serialize records เป็น envelope มีเวอร์ชัน (string JSON) — ผู้เรียกเขียนแบบ atomic เอง"""
    return json.dumps({"schema_version": current_version, "records": records},
                      ensure_ascii=False)
