"""
cli_session.py — บันทึกบทสนทนา CLI ลงดิสก์ทุกข้อความ (กันแชทหายเมื่อปิดหน้าต่าง/Ctrl+C/ไฟดับ)

ที่เก็บ: <data_dir>/cli_sessions/<YYYYmmdd-HHMMSS>.jsonl  (1 บรรทัด = 1 ข้อความ, append-only)
data_dir = $LCA_DATA_DIR หรือ %LOCALAPPDATA%\\LocalCodeAssistant\\data (เหมือน lca_app.data_dir)
หรือ ~/LocalCodeAssistant/data ถ้าไม่มี LOCALAPPDATA. stdlib ล้วน
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


def data_dir() -> Path:
    override = os.environ.get("LCA_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "LocalCodeAssistant" / "data"


def sessions_dir() -> Path:
    return data_dir() / "cli_sessions"


class SessionLog:
    def __init__(self, project_root: Path, path: Optional[Path] = None):
        self.project = str(Path(project_root).resolve())
        if path is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
            path = sessions_dir() / f"{stamp}.jsonl"
        self.path = Path(path)
        self.enabled = True

    def append(self, role: str, content: str, **extra) -> None:
        """เขียนต่อท้ายทันที + flush (ต่อข้อความ ไม่ใช่ต่อ token — ไม่หนัก HDD)"""
        if not self.enabled:
            return
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "project": self.project,
               "role": role, "content": content, **extra}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
        except OSError as e:  # บันทึกไม่ได้ ห้ามทำให้แชทพัง — ปิดการบันทึกแล้วเตือนครั้งเดียว
            self.enabled = False
            print(f"[session][warn] บันทึกประวัติไม่ได้ ({e}) — แชทต่อได้แต่จะไม่ถูกบันทึก")


def load_messages(path: Path) -> list[dict]:
    """อ่าน session เป็น list ของ {"role","content"} (ข้ามบรรทัดเสีย)"""
    msgs = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return msgs
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("role") in ("user", "assistant") and isinstance(rec.get("content"), str):
            msgs.append({"role": rec["role"], "content": rec["content"]})
    return msgs


def latest_session(project_root: Path) -> Optional[Path]:
    """หา session ล่าสุดของโปรเจกต์นี้ (ดูจาก field project ในบรรทัดแรก)"""
    d = sessions_dir()
    if not d.is_dir():
        return None
    want = str(Path(project_root).resolve())
    for p in sorted(d.glob("*.jsonl"), reverse=True):
        try:
            with p.open(encoding="utf-8") as f:
                first = json.loads(f.readline() or "{}")
        except (OSError, json.JSONDecodeError):
            continue
        if first.get("project") == want:
            return p
    return None
