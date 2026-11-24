"""
todo_store.py — เก็บ todo list เป็น JSON ต่อโปรเจกต์ (ไฟล์ todos.json ที่ project_root)

Interface ที่ local_coder.py / server.py เรียกใช้ตรงๆ (ห้ามเปลี่ยน signature):
    load_todos(project_root) -> list[dict]
    add_todo(project_root, text) -> dict
    toggle_todo(project_root, todo_id) -> bool
    delete_todo(project_root, todo_id) -> bool

โครงสร้าง item: {"id": int, "text": str, "done": bool}
"""

import json
import os
import tempfile
import threading
from pathlib import Path

from app.corrupt_file import preserve_corrupt_copy

TODOS_FILE_NAME = "todos.json"

# กัน read-modify-write ชนกันเมื่อหลาย request (ThreadingHTTPServer) เขียนพร้อมกัน
_LOCK = threading.RLock()


def _log(msg: str) -> None:
    """print ที่ไม่พังเมื่อ stdout เป็น encoding แคบ (เช่น cp1252 ตอน pipe บน Windows)"""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def _todos_path(project_root: Path) -> Path:
    return project_root / TODOS_FILE_NAME


def _preserve_corrupt(path: Path, reason: str) -> None:
    """เก็บสำเนาไฟล์ที่เสียไว้ก่อนจะถูกเขียนทับ — ไม่ให้ข้อมูลหายเงียบ ๆ"""
    try:
        dest = preserve_corrupt_copy(path, log=lambda _msg: None)
        _log(f"[todo][warn] {TODOS_FILE_NAME} {reason} — ถือว่าว่างเปล่า (สำเนาเดิม: {dest.name})")
    except OSError as e:
        _log(f"[todo][warn] {TODOS_FILE_NAME} {reason} และคัดลอกสำรองไม่ได้: {e} — ถือว่าว่างเปล่า")


class TodoReadError(OSError):
    """อ่าน todos.json ไม่ได้ (เช่น ถูกล็อก/ไม่มีสิทธิ์/เป็นโฟลเดอร์) — ห้ามถือว่าว่างแล้วเขียนทับ
    ผู้เรียก write path ต้องหยุดและไม่แตะไฟล์"""


def load_todos(project_root: Path) -> list:
    """อ่าน todos.json — ไม่มีไฟล์คืน list ว่าง. ถ้าไฟล์เสีย (JSON พัง / ไม่ใช่ list)
    คัดลอกเก็บเป็น todos.json.corrupt-<timestamp> เตือนแล้วคืน list ว่าง.
    ถ้าอ่านไฟล์ไม่ได้เพราะ OSError → raise TodoReadError (ไม่คืนว่าง เพื่อกันเขียนทับไฟล์จริง)"""
    path = _todos_path(project_root)
    if not path.exists():
        return []
    try:
        raw = path.read_bytes()
    except OSError as e:
        _log(f"[todo][error] อ่าน {TODOS_FILE_NAME} ไม่ได้: {e}")
        raise TodoReadError(f"อ่าน {TODOS_FILE_NAME} ไม่ได้: {e}") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        _preserve_corrupt(path, f"อ่านไม่ได้: {e}")
        return []
    if not isinstance(data, list):
        _preserve_corrupt(path, "รูปแบบผิด (ไม่ใช่ list)")
        return []
    return data


class TodoSaveError(OSError):
    """เขียน todos.json ไม่สำเร็จ — ผู้เรียกต้องรู้ (ห้ามรายงานว่าสำเร็จ)"""


def _save_todos(project_root: Path, todos: list) -> None:
    """เขียนแบบ atomic: เขียนลงไฟล์ชั่วคราวในโฟลเดอร์เดียวกันแล้ว os.replace ทับ
    — ถ้าโปรแกรมดับกลางคัน todos.json เดิมยังอยู่ครบ. ล้มเหลว → raise TodoSaveError"""
    path = _todos_path(project_root)
    data = json.dumps(todos, ensure_ascii=False, indent=2)
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(project_root), prefix=".todos-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_name, path)
        tmp_name = None
    except OSError as e:
        _log(f"[todo][error] เขียน {TODOS_FILE_NAME} ไม่ได้: {e}")
        raise TodoSaveError(f"เขียน {TODOS_FILE_NAME} ไม่ได้: {e}") from e
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def add_todo(project_root: Path, text: str) -> dict:
    """เพิ่ม todo ใหม่ — id เป็นเลขถัดจาก id สูงสุดที่มีอยู่ (กัน id ซ้ำแม้เคยลบตัวกลางไปแล้ว)"""
    with _LOCK:
        todos = load_todos(project_root)
        next_id = max((t.get("id", 0) for t in todos), default=0) + 1
        item = {"id": next_id, "text": text, "done": False}
        todos.append(item)
        _save_todos(project_root, todos)
    return item


def toggle_todo(project_root: Path, todo_id: int) -> bool:
    """สลับสถานะ done ↔ ไม่ done — คืน True ถ้าเจอ id, False ถ้าไม่เจอ"""
    with _LOCK:
        todos = load_todos(project_root)
        for t in todos:
            if t.get("id") == todo_id:
                t["done"] = not t.get("done", False)
                _save_todos(project_root, todos)
                return True
        return False


def delete_todo(project_root: Path, todo_id: int) -> bool:
    """ลบ todo ตาม id — คืน True ถ้าเจอและลบสำเร็จ, False ถ้าไม่เจอ"""
    with _LOCK:
        todos = load_todos(project_root)
        filtered = [t for t in todos if t.get("id") != todo_id]
        if len(filtered) == len(todos):
            return False
        _save_todos(project_root, filtered)
        return True
