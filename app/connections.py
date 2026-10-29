"""connections.py — ทะเบียน "ต่อสมอง AI ภายนอก" (external model/app servers)

โจทย์ (ตามที่ user สั่ง): อยากให้ LCA เป็นคอนโซลแบบ TokenMe ที่ "ต่อแอป/เซิร์ฟเวอร์ AI
อื่น ๆ ได้หลายตัว" — สมอง (AGI brain) หนึ่งตัว = หนึ่ง connection. เลือกใช้ใน Skills/Bot ได้.

ยืนบนของที่มีอยู่แล้ว: model_backend มี OpenAICompatBackend (คุยภาษา OpenAI /v1 ที่
TokenMe / vLLM / llama.cpp server / LM Studio / cloud เกือบทุกตัวพูดเหมือนกัน) และ
OllamaBackend (local). connection หนึ่งตัวจึงแค่ "จำค่าที่ต้องใช้ต่อ backend ตัวนั้น".

ชนิด (kind):
  openai  — OpenAI-compatible endpoint (base_url ลงท้าย /v1 + api_key)  → ต่อ TokenMe/cloud/vLLM
  ollama  — Ollama ในเครื่อง (ฟรี ใช้วันนี้)                           → base_url ไม่จำเป็น

ความปลอดภัย (Rule 23): api_key เป็นความลับ — เก็บใน connections.json (gitignored) แต่
**ไม่เคยคืนค่าเต็มออก API** (คืนแค่ api_key_set: true/false). atomic write + lock.

stdlib ล้วน.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from app import model_backend

STORE_FILE = "connections.json"
MAX_RECORDS = 500
KIND_OPENAI = "openai"
KIND_OLLAMA = "ollama"
VALID_KINDS = (KIND_OPENAI, KIND_OLLAMA)

_lock = threading.Lock()


class ConnectionError(Exception):
    """ต่อ/เรียก connection ไม่สำเร็จ หรือ input ผิด — ผู้เรียกแปลงเป็น 400/502 ได้"""


def _path(project_root) -> Path:
    return Path(project_root) / STORE_FILE


def _load(project_root) -> list:
    try:
        data = json.loads(_path(project_root).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(project_root, recs: list) -> None:
    p = _path(project_root)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(recs, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError as e:
        print(f"[connections][error] เขียน {STORE_FILE} ไม่ได้: {e}")


def _validate_base_url(kind: str, base_url: str) -> str:
    """openai ต้องมี base_url ที่เป็น http(s)://host...  — ollama ปล่อยว่างได้"""
    base_url = (base_url or "").strip().rstrip("/")
    if kind == KIND_OPENAI:
        if not base_url:
            raise ConnectionError("kind=openai ต้องระบุ base_url (เช่น https://api.tokenme.limited/api/v1)")
        p = urllib.parse.urlparse(base_url)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ConnectionError(f"base_url ไม่ถูกต้อง: {base_url!r} (ต้องเป็น http(s)://host.../v1)")
    return base_url


def _public(rec: dict) -> dict:
    """ตัดความลับออกก่อนคืนออก API — ไม่เผย api_key เต็ม (Rule 23)"""
    return {
        "id": rec.get("id"),
        "name": rec.get("name"),
        "kind": rec.get("kind"),
        "base_url": rec.get("base_url", ""),
        "model": rec.get("model", ""),
        "enabled": bool(rec.get("enabled", True)),
        "api_key_set": bool(rec.get("api_key")),
        "created_at": rec.get("created_at"),
        "updated_at": rec.get("updated_at"),
    }


def list_connections(project_root) -> list:
    """คืนทุก connection (redacted — ไม่มี api_key เต็ม)"""
    with _lock:
        return [_public(r) for r in _load(project_root)]


def get(project_root, conn_id: str, *, raw: bool = False):
    """คืน connection ตัวเดียว. raw=True คืน record เต็ม (มี api_key) — ใช้ภายในเท่านั้น"""
    with _lock:
        for r in _load(project_root):
            if r.get("id") == conn_id:
                return dict(r) if raw else _public(r)
    return None


def add(project_root, name: str, kind: str, base_url: str = "",
        model: str = "", api_key: str = "", enabled: bool = True) -> dict:
    """เพิ่ม connection ใหม่ — คืน record (redacted). input ผิด → ConnectionError"""
    name = (name or "").strip()
    if not name:
        raise ConnectionError("ต้องระบุชื่อ connection")
    kind = (kind or "").strip().lower()
    if kind not in VALID_KINDS:
        raise ConnectionError(f"kind ต้องเป็น {list(VALID_KINDS)} (ได้ {kind!r})")
    base_url = _validate_base_url(kind, base_url)
    rec = {
        "id": "con-" + uuid.uuid4().hex[:12],
        "name": name,
        "kind": kind,
        "base_url": base_url,
        "model": (model or "").strip(),
        "api_key": (api_key or "").strip(),
        "enabled": bool(enabled),
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with _lock:
        recs = _load(project_root)
        if any(r.get("name") == name for r in recs):
            raise ConnectionError(f"มี connection ชื่อ {name!r} อยู่แล้ว")
        recs.append(rec)
        if len(recs) > MAX_RECORDS:
            recs = recs[-MAX_RECORDS:]
        _save(project_root, recs)
    return _public(rec)


def update(project_root, conn_id: str, fields: dict) -> dict:
    """แก้ connection — เฉพาะคีย์ที่รู้จัก. api_key ส่งมาเฉพาะตอนจะเปลี่ยน (ว่าง=ไม่ทับ).
    คืน record (redacted). ไม่พบ/ผิด → ConnectionError"""
    fields = fields or {}
    with _lock:
        recs = _load(project_root)
        rec = next((r for r in recs if r.get("id") == conn_id), None)
        if rec is None:
            raise ConnectionError("ไม่พบ connection นี้")
        if "name" in fields and str(fields["name"]).strip():
            new_name = str(fields["name"]).strip()
            if any(r.get("name") == new_name and r.get("id") != conn_id for r in recs):
                raise ConnectionError(f"มี connection ชื่อ {new_name!r} อยู่แล้ว")
            rec["name"] = new_name
        if "kind" in fields and str(fields["kind"]).strip():
            kind = str(fields["kind"]).strip().lower()
            if kind not in VALID_KINDS:
                raise ConnectionError(f"kind ต้องเป็น {list(VALID_KINDS)} (ได้ {kind!r})")
            rec["kind"] = kind
        if "base_url" in fields:
            rec["base_url"] = _validate_base_url(rec["kind"], str(fields["base_url"]))
        if "model" in fields:
            rec["model"] = str(fields["model"]).strip()
        if "enabled" in fields:
            rec["enabled"] = bool(fields["enabled"])
        if fields.get("api_key"):           # ส่งมาเฉพาะตอนจะเปลี่ยน
            rec["api_key"] = str(fields["api_key"]).strip()
        rec["updated_at"] = time.time()
        _save(project_root, recs)
        return _public(rec)


def remove(project_root, conn_id: str) -> bool:
    with _lock:
        recs = _load(project_root)
        new = [r for r in recs if r.get("id") != conn_id]
        if len(new) == len(recs):
            return False
        _save(project_root, new)
        return True


def _backend_for(rec: dict):
    """สร้าง Backend object ให้ connection (reuse model_backend ที่พิสูจน์แล้ว)"""
    kind = rec.get("kind")
    if kind == KIND_OPENAI:
        return model_backend.OpenAICompatBackend(rec.get("base_url", ""), rec.get("api_key") or None)
    if kind == KIND_OLLAMA:
        return model_backend.OllamaBackend()
    raise ConnectionError(f"kind ไม่รองรับ: {kind}")


def test(project_root, conn_id: str) -> dict:
    """เช็กว่า connection "ต่อติดไหม" (reachable) — ไม่ generate จริง (ไม่กิน token)"""
    rec = get(project_root, conn_id, raw=True)
    if rec is None:
        raise ConnectionError("ไม่พบ connection นี้")
    backend = _backend_for(rec)
    try:
        ok = bool(backend.is_available())
    except Exception as e:   # pragma: no cover - is_available ควร degrade อยู่แล้ว
        return {"id": conn_id, "kind": rec.get("kind"), "available": False, "error": e.__class__.__name__}
    return {"id": conn_id, "kind": rec.get("kind"), "available": ok}


def chat(project_root, conn_id: str, messages: list, model: str = "",
         options: dict = None) -> str:
    """ส่งข้อความไปที่ "สมอง" ของ connection นี้แล้วคืนคำตอบ (blocking).
    model ว่าง → ใช้ model ที่ตั้งไว้ใน connection. enabled=False → ConnectionError."""
    rec = get(project_root, conn_id, raw=True)
    if rec is None:
        raise ConnectionError("ไม่พบ connection นี้")
    if not rec.get("enabled", True):
        raise ConnectionError(f"connection {rec.get('name')!r} ถูกปิดอยู่")
    use_model = (model or "").strip() or rec.get("model", "")
    if not use_model:
        raise ConnectionError("ต้องระบุ model (connection นี้ไม่ได้ตั้ง default model ไว้)")
    backend = _backend_for(rec)
    try:
        return backend.generate(use_model, messages, options=options)
    except model_backend.BackendError as e:
        raise ConnectionError(str(e)) from e


def make_generate_fn(project_root, conn_id: str, model: str = "", options: dict = None):
    """คืน callable(messages)->str ที่ยิงไปสมองของ connection นี้ — ให้ agent ReAct (core.run)
    ใช้ connection ที่เลือกเป็น "สมอง" แทน backend กลาง (ไม่ผูก MODEL_BACKEND)"""
    def _gen(messages):
        return chat(project_root, conn_id, messages, model=model, options=options)
    return _gen
