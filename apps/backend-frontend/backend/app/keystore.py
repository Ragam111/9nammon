"""Where the model API key lives. It never leaves the server: callers only ever get the last 4 chars.

Order: MODEL_API_KEY env var first, then a key saved through onboarding in DATA_DIR/model_key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import AppError

_MIN_LEN = 8
_MAX_LEN = 512


@dataclass(frozen=True)
class KeyStatus:
    configured: bool
    last4: str
    source: str  # "env", "stored" or "none"

    def to_dict(self) -> dict[str, object]:
        return {"configured": self.configured, "last4": self.last4, "source": self.source}


class KeyStore:
    def __init__(self, env_key: str, data_dir: Path) -> None:
        self._env_key = env_key.strip()
        self._path = data_dir / "model_key"

    def get(self) -> str:
        """The raw key for the outgoing model request. Never return this from an endpoint."""
        if self._env_key:
            return self._env_key
        try:
            return self._path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def status(self) -> KeyStatus:
        key = self.get()
        if not key:
            return KeyStatus(False, "", "none")
        return KeyStatus(True, key[-4:], "env" if self._env_key else "stored")

    def save(self, key: str) -> KeyStatus:
        """Store a key given during onboarding. Refused when the env var is set (env wins)."""
        key = key.strip()
        if self._env_key:
            raise AppError("validation", "ตั้ง key ผ่าน MODEL_API_KEY ใน environment อยู่แล้ว — แก้ที่ไฟล์ .env แทน")
        if not (_MIN_LEN <= len(key) <= _MAX_LEN) or any(c.isspace() for c in key):
            raise AppError("validation", "รูปแบบ API key ไม่ถูกต้อง")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(key, encoding="utf-8")
        if os.name == "posix":
            os.chmod(self._path, 0o600)
        return self.status()

    def clear(self) -> KeyStatus:
        self._path.unlink(missing_ok=True)
        return self.status()
