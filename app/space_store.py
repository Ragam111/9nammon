"""space_store.py — "พื้นที่" ส่วนตัว / ของบริษัท (private vs shared) + ข้อความในพื้นที่

โจทย์: ลูกน้องแต่ละคนมีที่ *ส่วนตัว* (คนอื่นเห็นไม่ได้) และมีที่ *ของบริษัท* (shared)
ที่ทีมคุยงาน/ประชุมร่วมกันได้. คุมการเข้าถึงด้วย RBAC เดิม (org_store.role_at_least)

โมเดล:
  space = {id, name, owner, visibility: private|shared, members[], ts}
  item  = {id, space_id, author, text, ts}   # ข้อความ/โน้ตในพื้นที่

กฎการเข้าถึง (can_access):
  - ADMIN ขึ้นไป  → เข้าได้ทุกพื้นที่ (ดูแลระบบ)
  - shared       → ผู้ใช้ทุกคน (ที่ล็อกอิน) เข้าได้
  - private      → เจ้าของ หรือ สมาชิกที่ถูกเชิญ เท่านั้น

stdlib ล้วน (json). เก็บเป็น spaces.json ต่อโปรเจกต์ (มีเนื้อหาส่วนตัว → อยู่ใน .gitignore)
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from app import org_store
from app.corrupt_file import preserve_corrupt_copy

STORE_FILE = "spaces.json"
VALID_VISIBILITY = ("private", "shared")

# กัน read-modify-write ชนกันเมื่อหลาย request (ThreadingHTTPServer) เขียนพร้อมกัน
# (ถ้าไม่มี lock การสร้างพร้อมกันจะเขียนทับกัน ทำให้พื้นที่หายไป)
_LOCK = threading.RLock()


def _path(project_root) -> Path:
    return Path(project_root) / STORE_FILE


def _empty() -> dict:
    return {"spaces": [], "items": []}


class SpaceReadError(OSError):
    """อ่าน spaces.json ไม่ได้ (OSError) — ห้ามถือว่าว่างแล้วเขียนทับ ผู้เรียก write path ต้องหยุด"""


def _load(project_root) -> dict:
    """อ่าน spaces.json — ไม่มีไฟล์ = ว่าง. ไฟล์เสีย/รูปแบบผิด (JSON พัง) → คัดลอกเก็บเป็น
    spaces.json.corrupt-<timestamp> ก่อน แล้วค่อยทำงานต่อจากรายการว่าง (ไม่ทิ้งข้อมูลเงียบ ๆ).
    อ่านไฟล์ไม่ได้เพราะ OSError → raise SpaceReadError (ไม่คืนว่าง เพื่อกันเขียนทับไฟล์จริง)"""
    p = _path(project_root)
    with _LOCK:
        if not p.exists():
            return _empty()
        try:
            raw = p.read_bytes()
        except OSError as e:
            _log(f"[space][error] อ่าน {STORE_FILE} ไม่ได้: {e}")
            raise SpaceReadError(f"อ่าน {STORE_FILE} ไม่ได้: {e}") from e
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            _preserve_corrupt(p, f"อ่านไม่ได้: {e}")
            return _empty()
        if not isinstance(data, dict):
            _preserve_corrupt(p, "รูปแบบผิด (ไม่ใช่ object)")
            return _empty()
        data.setdefault("spaces", [])
        data.setdefault("items", [])
        return data


def _log(msg: str) -> None:
    """print ที่ไม่พังเมื่อ stdout เป็น encoding แคบ (เช่น cp1252 ตอน pipe บน Windows)"""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def _preserve_corrupt(p: Path, reason: str) -> None:
    try:
        dest = preserve_corrupt_copy(p, log=lambda _msg: None)
        _log(f"[space][warn] {STORE_FILE} {reason} — ถือว่าว่างเปล่า (สำเนาเดิม: {dest.name})")
    except OSError as e:
        _log(f"[space][warn] {STORE_FILE} {reason} และคัดลอกสำรองไม่ได้: {e} — ถือว่าว่างเปล่า")


def _save(project_root, data: dict) -> None:
    """เขียนแบบ atomic: ไฟล์ชั่วคราวในโฟลเดอร์เดียวกัน + os.replace (mirror todo_store)"""
    path = _path(project_root)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    with _LOCK:
        tmp_name = None
        try:
            fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".spaces-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_name, path)
            tmp_name = None
        finally:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}{int(time.time() * 1000)}"


def create_space(project_root, name: str, owner: str, visibility: str = "private") -> dict:
    """สร้างพื้นที่ใหม่ — เจ้าของคือ owner. visibility ต้องเป็น private|shared"""
    name = (name or "").strip()
    if not name:
        raise ValueError("ต้องระบุชื่อพื้นที่")
    visibility = (visibility or "private").strip().lower()
    if visibility not in VALID_VISIBILITY:
        raise ValueError(f"visibility ต้องเป็น {list(VALID_VISIBILITY)} (ได้ {visibility!r})")
    with _LOCK:
        data = _load(project_root)
        sid = _new_id("sp")
        existing = {s["id"] for s in data["spaces"]}
        n = 0
        while sid in existing:
            n += 1
            sid = _new_id("sp") + f"-{n}"
        space = {"id": sid, "name": name, "owner": owner, "visibility": visibility,
                 "members": [], "ts": int(time.time())}
        data["spaces"].append(space)
        _save(project_root, data)
    return space


def get_space(project_root, space_id: str):
    for s in _load(project_root)["spaces"]:
        if s["id"] == space_id:
            return s
    return None


def can_access(space: dict, username: str, role: str) -> bool:
    """ผู้ใช้ (username/role) เข้าถึงพื้นที่นี้ได้ไหม"""
    if space is None:
        return False
    if org_store.role_at_least(role, "ADMIN"):
        return True
    if space.get("visibility") == "shared":
        return True
    # private: เจ้าของ หรือ สมาชิก
    return username == space.get("owner") or username in (space.get("members") or [])


def list_spaces(project_root, username: str, role: str) -> list:
    """คืนเฉพาะพื้นที่ที่ผู้ใช้คนนี้เข้าถึงได้ (ใหม่สุดก่อน)"""
    spaces = _load(project_root)["spaces"]
    visible = [s for s in spaces if can_access(s, username, role)]
    return sorted(visible, key=lambda s: s.get("ts", 0), reverse=True)


def add_member(project_root, space_id: str, member: str) -> dict:
    """เพิ่มสมาชิกเข้าพื้นที่ private (ผู้เรียกต้องเช็คสิทธิ์เจ้าของ/แอดมินก่อนที่ server)"""
    with _LOCK:
        data = _load(project_root)
        space = next((s for s in data["spaces"] if s["id"] == space_id), None)
        if space is None:
            raise ValueError(f"ไม่พบพื้นที่: {space_id}")
        if member and member not in space["members"] and member != space["owner"]:
            space["members"].append(member)
            _save(project_root, data)
        return space


def add_item(project_root, space_id: str, author: str, text: str) -> dict:
    """เพิ่มข้อความ/โน้ตในพื้นที่ — ผู้เรียกต้องเช็ค can_access ก่อนที่ server"""
    text = (text or "").strip()
    if not text:
        raise ValueError("ต้องมีข้อความ")
    with _LOCK:
        data = _load(project_root)
        if not any(s["id"] == space_id for s in data["spaces"]):
            raise ValueError(f"ไม่พบพื้นที่: {space_id}")
        item = {"id": _new_id("it"), "space_id": space_id, "author": author,
                "text": text, "ts": int(time.time())}
        data["items"].append(item)
        _save(project_root, data)
    return item


def list_items(project_root, space_id: str) -> list:
    """ข้อความในพื้นที่ (เก่า→ใหม่) — ผู้เรียกต้องเช็ค can_access ก่อนที่ server"""
    items = [i for i in _load(project_root)["items"] if i["space_id"] == space_id]
    return sorted(items, key=lambda i: i.get("ts", 0))
