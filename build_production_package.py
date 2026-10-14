#!/usr/bin/env python3
"""
build_production_package.py — สร้าง Production ZIP ของ LCA v0.0.2

สถานะ: PACKAGING ONLY — ไม่ใช่ Release script
ห้ามตีความว่า ZIP ที่ได้คือ "Verified Release" — ต้องผ่าน Windows UTF-8 verify,
Windows RAM measurement, และ Chat Bug #4 evidence/RCA ก่อนถึงจะปลด RELEASE BLOCKED

ใช้ Python standard library เท่านั้น (zipfile, hashlib, pathlib) — ไม่เพิ่ม dependency
ไม่แก้ไข source code ใดๆ ในโปรเจกต์ — สคริปต์นี้แค่ "อ่านแล้วรวมไฟล์" เท่านั้น

วิธีใช้: python3 build_production_package.py
ผลลัพธ์: LCA-v0.0.2-production.zip + manifest.json ในโฟลเดอร์เดียวกัน
"""

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parent
OUTPUT_ZIP = PACKAGE_ROOT / "LCA-v0.0.2-production.zip"
MANIFEST_PATH = PACKAGE_ROOT / "production_manifest.json"

# ไฟล์/โฟลเดอร์ที่ "คาดว่าจะเป็น production file" — ต้องเช็คว่ามีอยู่จริงก่อน
# ไม่สร้างขึ้นเองถ้าไม่มี (ตามคำสั่ง Manager)
EXPECTED_PRODUCTION_PATHS = [
    "local_coder.py",
    "server.py",
    "app",
    "config",       # คาดว่าจะไม่มีจริง — ต้องรายงาน MISSING
    "README.md",
    "docs",
    "lca.bat",
    "lca-web.bat",
    "install.bat",
    "install.ps1",
    "install.sh",
    "uninstall.ps1",
    "update.ps1",
    "INFO_BEFORE.txt",
    # folder_trust.py / context_manager.py ที่ root: install.ps1 อ่านจากตรงนี้เป็น
    # "installer source" ก่อน Copy-Item ไปวางที่ app/ ปลายทางสำหรับ runtime import
    # (สถาปัตยกรรม root → app/ ยืนยันแล้วว่าถูกต้องจริง ไม่ใช่ mismatch — ดู
    # SOURCE PACKAGE INVESTIGATION REPORT) — เดิมขาดจากรายการนี้ ทำให้ Production
    # ZIP มีแค่สำเนาปลายทางใน app/ แต่ไม่มี source ให้ install.ps1 อ่าน
    "folder_trust.py",
    "context_manager.py",
]

# Pattern ที่ต้อง exclude เสมอ แม้จะอยู่ใต้โฟลเดอร์ที่รวมเข้าไป (เช่น app/, docs/)
EXCLUDE_DIR_NAMES = {"tests", ".git", "__pycache__"}
EXCLUDE_FILE_SUFFIXES = (".pyc", ".log", ".tmp")
EXCLUDE_FILE_NAMES = {".env"}


def _should_exclude(path: Path) -> bool:
    if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
        return True
    if path.suffix in EXCLUDE_FILE_SUFFIXES:
        return True
    if path.name in EXCLUDE_FILE_NAMES:
        return True
    return False


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as e:
        return f"ERROR: อ่านไฟล์ไม่ได้ ({e})"


def inspect_expected_paths() -> tuple:
    """เช็คว่า EXPECTED_PRODUCTION_PATHS แต่ละตัวมีอยู่จริงหรือไม่ — คืน
    (found_paths, missing_paths) โดยไม่สร้างอะไรขึ้นเองถ้าไม่พบ"""
    found, missing = [], []
    for name in EXPECTED_PRODUCTION_PATHS:
        p = PACKAGE_ROOT / name
        if p.exists():
            found.append(name)
        else:
            missing.append(name)
    return found, missing


def collect_files_to_package(found_paths: list) -> list:
    """เดินสแกนไฟล์จริงทั้งหมดใต้ found_paths แล้วกรอง exclude list ออก
    คืน list ของ Path (relative to PACKAGE_ROOT)"""
    collected = []
    for name in found_paths:
        p = PACKAGE_ROOT / name
        if p.is_file():
            if not _should_exclude(p.relative_to(PACKAGE_ROOT)):
                collected.append(p)
        elif p.is_dir():
            for sub in p.rglob("*"):
                if sub.is_file():
                    rel = sub.relative_to(PACKAGE_ROOT)
                    if not _should_exclude(rel):
                        collected.append(sub)
    return sorted(set(collected))


def build_zip(files: list) -> None:
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            arcname = f.relative_to(PACKAGE_ROOT)
            zf.write(f, arcname=str(arcname))


def build_manifest(files: list, missing: list) -> dict:
    entries = []
    for f in files:
        rel = str(f.relative_to(PACKAGE_ROOT))
        entries.append({
            "path": rel,
            "size_bytes": f.stat().st_size,
            "sha256": _sha256_of_file(f),
            "source_status": "FOUND",
        })
    for name in missing:
        entries.append({
            "path": name,
            "size_bytes": None,
            "sha256": None,
            "source_status": "MISSING — ไม่มีในโปรเจกต์จริง ไม่ได้ถูกสร้างขึ้นเอง",
        })
    return {
        "package": OUTPUT_ZIP.name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "PACKAGE PREPARED / UNVERIFIED — NOT A RELEASE",
        "entries": entries,
    }


def verify_exclusions(files: list) -> list:
    """คืน list ของ path ที่หลุดเข้ามาทั้งที่ควรถูก exclude (ถ้าไม่ว่างเปล่า = FAIL)"""
    violations = []
    for f in files:
        rel = f.relative_to(PACKAGE_ROOT)
        if _should_exclude(rel):
            violations.append(str(rel))
    return violations


def verify_zip_integrity() -> tuple:
    """เปิด zip กลับมาอ่านจริง เช็คว่าอ่านรายการไฟล์ได้และไม่มีไฟล์เสีย
    คืน (ok: bool, message: str)"""
    try:
        with zipfile.ZipFile(OUTPUT_ZIP, "r") as zf:
            bad_file = zf.testzip()
            if bad_file is not None:
                return False, f"ไฟล์เสียใน zip: {bad_file}"
            names = zf.namelist()
            return True, f"เปิดอ่านได้ปกติ พบ {len(names)} ไฟล์"
    except (OSError, zipfile.BadZipFile) as e:
        return False, f"เปิด zip ไม่ได้: {e}"


def main():
    print("=== LCA v0.0.2 — Production Packaging (PREPARE ONLY, ไม่ใช่ Release) ===\n")

    found, missing = inspect_expected_paths()
    print(f"[inspect] พบจริง: {found}")
    print(f"[inspect] MISSING (ไม่สร้างขึ้นเอง): {missing}\n")

    files = collect_files_to_package(found)
    print(f"[collect] รวมไฟล์ทั้งหมด {len(files)} ไฟล์เข้า package")

    violations = verify_exclusions(files)
    if violations:
        print(f"[exclusion][FAIL] พบไฟล์ที่ควร exclude หลุดเข้ามา: {violations}")
    else:
        print("[exclusion][PASS] ไม่มีไฟล์ที่ควร exclude หลุดเข้ามา")

    build_zip(files)
    print(f"\n[zip] สร้างแล้ว: {OUTPUT_ZIP.name} ({OUTPUT_ZIP.stat().st_size:,} bytes)")

    ok, msg = verify_zip_integrity()
    print(f"[integrity] {'PASS' if ok else 'FAIL'} — {msg}")

    manifest = build_manifest(files, missing)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[manifest] เขียนแล้ว: {MANIFEST_PATH.name}")

    print("\n=== สถานะ: PACKAGE PREPARED / UNVERIFIED — RELEASE ยังคง BLOCKED ===")


if __name__ == "__main__":
    main()
