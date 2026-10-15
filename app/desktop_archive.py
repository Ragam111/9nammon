"""
desktop_archive.py — sync ข้อมูลโปรเจกต์ไปเก็บถาวรที่ ~/Desktop/LocalCodeAssistant-Data/

**ขอบเขตจริง (ตามที่ระบุใน SKILL.md)**: นี่คือการ "เขียนไฟล์ไปเก็บ" (archive) เฉยๆ
ไม่ใช่การทำให้โมเดล Ollama "จำ" อะไรได้ข้ามเซสชันจริง — เป็นที่เก็บให้ผู้ใช้เปิดอ่านเอง

Interface ที่ local_coder.py เรียกใช้ตรงๆ:
    sync_project(project_root) -> Path | None   (None ถ้า sync ไม่สำเร็จ)
    get_archive_root() -> Path
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

ARCHIVE_DIR_NAME = "LocalCodeAssistant-Data"


def get_archive_root() -> Path:
    """คืน path โฟลเดอร์เก็บข้อมูลถาวรบนเดสก์ท็อป — ไม่รับประกันว่ามีอยู่จริง
    (ให้ sync_project เป็นคนสร้างตอนจำเป็น)"""
    return Path.home() / "Desktop" / ARCHIVE_DIR_NAME


def _update_index(archive_root: Path, project_name: str, project_path: str) -> None:
    """อัปเดต index.json รวมรายชื่อทุกโปรเจกต์ที่เคย sync — ไม่ให้ error ตรงนี้ทำให้
    sync_project ทั้งฟังก์ชันล้ม (archive เป็นฟีเจอร์เสริม ไม่ใช่ core workflow)"""
    index_path = archive_root / "index.json"
    try:
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            index = {}
    except (OSError, json.JSONDecodeError):
        index = {}

    index[project_name] = {
        "path": project_path,
        "last_sync": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[archive][warn] อัปเดต index.json ไม่ได้: {e}")


def sync_project(project_root: Path) -> Path | None:
    """คัดลอก CHANGELOG_local.md และ todos.json (ถ้ามี) ไปที่
    ~/Desktop/LocalCodeAssistant-Data/<ชื่อโปรเจกต์>/ แล้วอัปเดต index.json
    คืน path ปลายทางถ้าสำเร็จ, None ถ้า sync ไม่ได้ (เช่นสร้างโฟลเดอร์ Desktop ไม่ได้)
    — ไม่ crash โปรแกรมหลัก ตาม Rule fail-loudly-but-not-crash สำหรับฟีเจอร์เสริม"""
    archive_root = get_archive_root()
    project_name = project_root.name
    dest_dir = archive_root / project_name

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[archive][warn] สร้างโฟลเดอร์ {dest_dir} ไม่ได้: {e} — ข้าม sync รอบนี้")
        return None

    changelog_src = project_root / "CHANGELOG_local.md"
    todos_src = project_root / "todos.json"

    try:
        if changelog_src.exists():
            shutil.copy(changelog_src, dest_dir / "CHANGELOG_local.md")
        if todos_src.exists():
            shutil.copy(todos_src, dest_dir / "todos.json")
    except OSError as e:
        print(f"[archive][warn] คัดลอกไฟล์ไป {dest_dir} ไม่สำเร็จ: {e}")
        return None

    _update_index(archive_root, project_name, str(project_root))
    return dest_dir
