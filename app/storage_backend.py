"""storage_backend.py — "เต้ารับมาตรฐาน" สำหรับที่เก็บข้อมูลของ LCA

ไอเดีย (9arm): วันนี้ store ทุกตัว (usage_store, support_store, org_store ฯลฯ)
เขียนไฟล์ลงดิสก์ตรง ๆ — ใช้ได้ดีบน netbook เครื่องเดียว แต่พอวันหนึ่งต้องย้าย
ไป object storage (S3 / GCS) หรือหลายเครื่องแชร์กัน เราไม่อยากไล่แก้ทุก store
เราทำ **interface มาตรฐาน** ของ "ที่เก็บ key→ข้อความ" ไว้ แล้วของใหม่เสียบเองได้
เหมือนเต้ารับ — โค้ดที่เรียกใช้ไม่ต้องรู้ว่าเบื้องหลังเป็นดิสก์ หน่วยความจำ หรือคลาวด์

- ยืนบนของที่พิสูจน์แล้ว: filesystem (local, ใช้อยู่วันนี้)
- เผื่ออนาคต: มี interface เดียว → เขียน S3Backend/GCSBackend ทีหลังได้โดยไม่แตะผู้เรียก
- MemoryStorageBackend: ที่เก็บชั่วคราวในแรม — ไว้เทส และงานที่ไม่ต้องคงอยู่

เลือก backend ด้วย config (ไม่ hardcode):
  STORAGE_BACKEND = local | memory     (default local)
  STORAGE_ROOT    = <path>             (เมื่อ local; ไม่ใส่ = <project_root>/data)

stdlib ล้วน — ไม่เพิ่ม dependency
"""

from __future__ import annotations

from pathlib import Path

from app import config_manager


class StorageError(Exception):
    """อ่าน/เขียนที่เก็บไม่สำเร็จ — ผู้เรียกแปลงเป็น error ของตัวเองได้"""


def _safe_key(key: str) -> str:
    """กัน path traversal: key เป็นชื่อเชิงสัมพัทธ์เท่านั้น ห้ามหลุดออกนอก root
    (เช่น '../secret' หรือ '/etc/passwd') — เป็นเรื่อง correctness ก่อน optimize"""
    key = (key or "").strip()
    if not key:
        raise StorageError("key ว่างไม่ได้")
    p = Path(key)
    if p.is_absolute() or ".." in p.parts:
        raise StorageError(f"key ไม่ปลอดภัย: {key!r}")
    return key


class StorageBackend:
    """เต้ารับมาตรฐาน: ทุก backend ต้องทำ 5 อย่างนี้ให้ครบ (key→ข้อความ)"""
    name = "base"

    def read_text(self, key: str) -> str | None:
        raise NotImplementedError

    def write_text(self, key: str, text: str) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError

    def list_keys(self, prefix: str = "") -> list:
        raise NotImplementedError


class LocalStorageBackend(StorageBackend):
    """ของที่พิสูจน์แล้ววันนี้ — เก็บเป็นไฟล์ UTF-8 ใต้ root เดียว"""
    name = "local"

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    def read_text(self, key: str) -> str | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            raise StorageError(f"อ่าน {key} ไม่ได้: {e}") from e

    def write_text(self, key: str, text: str) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            raise StorageError(f"เขียน {key} ไม่ได้: {e}") from e

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError as e:
            raise StorageError(f"ลบ {key} ไม่ได้: {e}") from e

    def list_keys(self, prefix: str = "") -> list:
        if not self.root.exists():
            return []
        keys = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(self.root).as_posix()
                if rel.startswith(prefix):
                    keys.append(rel)
        return keys


class MemoryStorageBackend(StorageBackend):
    """ที่เก็บในแรม — พิสูจน์ว่าขอบเขตสะอาดจริง (impl ที่ 2) + ใช้เทส/งานชั่วคราว"""
    name = "memory"

    def __init__(self):
        self._data: dict[str, str] = {}

    def read_text(self, key: str) -> str | None:
        return self._data.get(_safe_key(key))

    def write_text(self, key: str, text: str) -> None:
        self._data[_safe_key(key)] = text

    def exists(self, key: str) -> bool:
        return _safe_key(key) in self._data

    def delete(self, key: str) -> bool:
        return self._data.pop(_safe_key(key), None) is not None

    def list_keys(self, prefix: str = "") -> list:
        return sorted(k for k in self._data if k.startswith(prefix))


def get_storage(project_root) -> StorageBackend:
    """เลือก backend จาก config (default local) — อ่านจากที่คนตั้งเท่านั้น ไม่สลับเองเงียบ ๆ"""
    project_root = Path(project_root)
    sel = (config_manager.get_key(project_root, "STORAGE_BACKEND") or "local").strip().lower()
    if sel == "memory":
        return MemoryStorageBackend()
    root = config_manager.get_key(project_root, "STORAGE_ROOT")
    return LocalStorageBackend(Path(root) if root else project_root / "data")
