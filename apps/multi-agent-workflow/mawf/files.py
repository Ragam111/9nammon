"""File tools for the Executor, confined to one sandbox folder chosen by the operator.

Only three actions exist: read a text file, write a text file (create or overwrite), and list a folder.
There is no delete, no rename, no shell and no execution. Every path must resolve inside the sandbox,
so `..`, absolute paths and symlinks that point out are refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 200_000
MAX_READ_CHARS = 20_000
ACTIONS = frozenset({"read_file", "write_file", "list_dir"})


class SandboxError(ValueError):
    """A file request was outside the sandbox or not allowed."""


class FileSandbox:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, rel: str) -> Path:
        """Turn a relative path into a real path inside the sandbox, or raise SandboxError."""
        if not rel or rel.strip() != rel or "\x00" in rel:
            raise SandboxError("path ไม่ถูกต้อง")
        candidate = Path(rel)
        if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
            raise SandboxError("ใช้ได้เฉพาะ path สัมพัทธ์ที่อยู่ในโฟลเดอร์งาน ห้ามมี ..")
        target = (self.root / candidate).resolve()
        if not target.is_relative_to(self.root):
            raise SandboxError("path อยู่นอกโฟลเดอร์งาน")
        return target

    def run(self, call: dict[str, Any]) -> dict[str, Any]:
        """Run one allowlisted action. Failures come back as {"ok": false, ...}."""
        action = str(call.get("action", ""))
        if action not in ACTIONS:
            return {"ok": False, "error": f"คำสั่ง {action!r} ไม่ได้รับอนุญาต"}
        try:
            if action == "read_file":
                return self._read(str(call.get("path", "")))
            if action == "write_file":
                return self._write(str(call.get("path", "")), str(call.get("content", "")))
            return self._list(str(call.get("path", ".")))
        except SandboxError as exc:
            return {"ok": False, "error": str(exc)}
        except OSError as exc:
            return {"ok": False, "error": f"อ่าน/เขียนไฟล์ไม่ได้: {exc.strerror or exc}"}

    def _read(self, rel: str) -> dict[str, Any]:
        path = self.resolve(rel)
        if not path.is_file():
            raise SandboxError("ไม่พบไฟล์นี้")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise SandboxError("ไฟล์ใหญ่เกินไป")
        text = path.read_text(encoding="utf-8", errors="strict")
        return {"ok": True, "path": rel, "text": text[:MAX_READ_CHARS], "truncated": len(text) > MAX_READ_CHARS}

    def _write(self, rel: str, content: str) -> dict[str, Any]:
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise SandboxError("เนื้อหาใหญ่เกิน 200 KB")
        path = self.resolve(rel)
        if path.is_dir():
            raise SandboxError("path นี้เป็นโฟลเดอร์")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"ok": True, "path": rel, "bytes": len(content.encode("utf-8"))}

    def _list(self, rel: str) -> dict[str, Any]:
        path = self.resolve(rel)
        if not path.is_dir():
            raise SandboxError("ไม่ใช่โฟลเดอร์")
        names = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        return {"ok": True, "path": rel, "entries": names[:200]}


def result_text(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
