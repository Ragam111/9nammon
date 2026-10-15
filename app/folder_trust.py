"""
folder_trust.py — ยืนยันความน่าเชื่อถือของโปรเจกต์ก่อนให้ Local Code Assistant
เริ่มทำงาน (scan/แก้ไฟล์) ครั้งแรกที่เปิดโฟลเดอร์ใหม่

ป้องกันกรณีเปิดโฟลเดอร์ผิด (เช่น พิมพ์ path พลาด) แล้วเผลอให้ระบบแก้ไฟล์โดยไม่รู้ตัว
ว่ากำลังทำงานกับโฟลเดอร์ไหนอยู่

Marker file: <project_root>/.lca_trust — เก็บ timestamp ตอนยืนยันครั้งแรกเท่านั้น
เปิดโปรเจกต์เดิมซ้ำ (มี marker แล้ว) จะไม่ถามอีก ตามเงื่อนไขผ่านเฟสที่ตั้งไว้
"""

from datetime import datetime
from pathlib import Path

TRUST_MARKER_NAME = ".lca_trust"


def _marker_path(project_root: Path) -> Path:
    return project_root / TRUST_MARKER_NAME


def is_trusted(project_root: Path) -> bool:
    """เช็คว่ามี marker file อยู่แล้วหรือยัง (เคยยืนยันมาก่อน)"""
    return _marker_path(project_root).exists()


def mark_trusted(project_root: Path) -> None:
    """สร้าง marker file — เรียกหลังผู้ใช้ยืนยัน y เท่านั้น"""
    marker = _marker_path(project_root)
    try:
        marker.write_text(
            f"trusted_at={datetime.now().isoformat(timespec='seconds')}\n",
            encoding="utf-8",
        )
    except OSError as e:
        # fail loudly ตาม Rule ข้อ 14 — แต่ไม่ทำให้โปรแกรมพัง แค่แจ้งเตือนว่า
        # ครั้งหน้าจะถามซ้ำอีกเพราะสร้าง marker ไม่สำเร็จ
        print(f"[trust][warn] สร้าง {TRUST_MARKER_NAME} ไม่ได้: {e} (จะถามยืนยันอีกครั้งหน้า)")


def ensure_trusted(project_root: Path) -> bool:
    """เรียกตอนเริ่มโปรแกรม (ก่อน print_banner) — ถ้ายังไม่เคยยืนยัน ให้ถามตรงๆ
    คืนค่า True = ทำงานต่อได้ (ยืนยันแล้วหรือเคยยืนยันมาก่อน)
    คืนค่า False = ผู้ใช้ปฏิเสธ (ผู้เรียกต้องหยุดโปรแกรมเอง ไม่ใช่หน้าที่ฟังก์ชันนี้)"""
    if is_trusted(project_root):
        return True

    print(f"[trust] ยังไม่เคยเปิดโปรเจกต์นี้มาก่อน: {project_root}")
    print("[trust] Local Code Assistant จะอ่าน/แก้ไฟล์ในโฟลเดอร์นี้ได้ตั้งแต่ตอนนี้เป็นต้นไป")
    try:
        answer = input("[trust] ยืนยันว่าเป็นโปรเจกต์ที่ต้องการทำงานด้วยจริง? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if answer != "y":
        print("[trust] ยกเลิก — ไม่ได้ยืนยัน จึงไม่เริ่มทำงานกับโฟลเดอร์นี้")
        return False

    mark_trusted(project_root)
    print(f"[trust] บันทึกแล้ว — เปิดโปรเจกต์นี้ครั้งหน้าจะไม่ถามอีก ({TRUST_MARKER_NAME})")
    return True
