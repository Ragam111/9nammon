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
from pathlib import Path

TODOS_FILE_NAME = "todos.json"


def _todos_path(project_root: Path) -> Path:
    return project_root / TODOS_FILE_NAME


def load_todos(project_root: Path) -> list:
    """อ่าน todos.json — ถ้าไม่มีไฟล์คืน list ว่าง, ถ้าไฟล์เสีย (JSON พัง) เตือนแล้วคืน list ว่าง"""
    path = _todos_path(project_root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            print(f"[todo][warn] {TODOS_FILE_NAME} รูปแบบผิด (ไม่ใช่ list) — ถือว่าว่างเปล่า")
            return []
        return data
    except (OSError, json.JSONDecodeError) as e:
        print(f"[todo][warn] อ่าน {TODOS_FILE_NAME} ไม่ได้: {e} — ถือว่าว่างเปล่า")
        return []


def _save_todos(project_root: Path, todos: list) -> None:
    path = _todos_path(project_root)
    try:
        path.write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[todo][error] เขียน {TODOS_FILE_NAME} ไม่ได้: {e}")


def add_todo(project_root: Path, text: str) -> dict:
    """เพิ่ม todo ใหม่ — id เป็นเลขถัดจาก id สูงสุดที่มีอยู่ (กัน id ซ้ำแม้เคยลบตัวกลางไปแล้ว)"""
    todos = load_todos(project_root)
    next_id = max((t.get("id", 0) for t in todos), default=0) + 1
    item = {"id": next_id, "text": text, "done": False}
    todos.append(item)
    _save_todos(project_root, todos)
    return item


def toggle_todo(project_root: Path, todo_id: int) -> bool:
    """สลับสถานะ done ↔ ไม่ done — คืน True ถ้าเจอ id, False ถ้าไม่เจอ"""
    todos = load_todos(project_root)
    for t in todos:
        if t.get("id") == todo_id:
            t["done"] = not t.get("done", False)
            _save_todos(project_root, todos)
            return True
    return False


def delete_todo(project_root: Path, todo_id: int) -> bool:
    """ลบ todo ตาม id — คืน True ถ้าเจอและลบสำเร็จ, False ถ้าไม่เจอ"""
    todos = load_todos(project_root)
    filtered = [t for t in todos if t.get("id") != todo_id]
    if len(filtered) == len(todos):
        return False
    _save_todos(project_root, filtered)
    return True
