"""
corrupt_file.py — เก็บสำเนาของไฟล์ JSON ที่อ่านไม่ได้ก่อนที่จะถูกเขียนทับ

ใช้กับ todo_store / space_store: ถ้า todos.json (หรือไฟล์ข้อมูลอื่น) พัง เราจะไม่ทิ้งมันเงียบ ๆ
แต่คัดลอกไปเป็น <ชื่อไฟล์>.corrupt-<timestamp> แล้วค่อยทำงานต่อจากรายการว่าง
(คัดลอก ไม่ใช่ย้าย — ไฟล์เดิมยังอยู่จนกว่าการเขียนครั้งถัดไปจะ replace แบบ atomic)
"""

import shutil
import time
from pathlib import Path


def preserve_corrupt_copy(path: Path, log=print) -> Path:
    """คัดลอก path เป็น <name>.corrupt-<timestamp> แล้วคืน path ของสำเนา

    ถ้ามีสำเนา .corrupt-* ที่เนื้อหาตรงกันอยู่แล้ว จะไม่สร้างซ้ำ (กัน load ซ้ำ ๆ แล้วไฟล์บานเปล่า)
    """
    raw = path.read_bytes()
    for existing in sorted(path.parent.glob(path.name + ".corrupt-*")):
        try:
            if existing.read_bytes() == raw:
                return existing
        except OSError:
            continue
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
    dest = path.with_name(f"{path.name}.corrupt-{stamp}")
    shutil.copy2(path, dest)
    try:
        log(f"[warn] ไฟล์ {path.name} อ่านไม่ได้ — เก็บสำเนาไว้ที่ {dest.name} แล้ว")
    except Exception:
        pass
    return dest
