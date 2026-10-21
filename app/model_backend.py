"""model_backend.py — "เต้ารับมาตรฐาน" สำหรับ model serving backend ของ LCA

ไอเดีย (9arm): เราไม่ทำนายว่าปี 2026-2050 จะใช้ runtime อะไร — เราทำ **interface
มาตรฐาน** ไว้ แล้วของใหม่เสียบเองได้ เหมือน USB/TCP ที่อยู่ยาวเพราะเป็นขอบเขตที่สะอาด

- ยืนบนของที่พิสูจน์แล้ว: Ollama (local, ฟรี, ใช้อยู่วันนี้)
- เผื่ออนาคต: OpenAI-compatible API = ภาษาเดียวที่ vLLM / llama.cpp server / LM Studio /
  cloud provider เกือบทุกตัวพูดเหมือนกัน → adapter ตัวเดียวรองรับ runtime ใหม่ได้โดยไม่แก้แอป

สลับ backend ด้วย config (ไม่ hardcode):
  MODEL_BACKEND = ollama | openai        (default ollama)
  OPENAI_BASE_URL = http://host:port/v1  (เมื่อใช้ openai)
  OPENAI_API_KEY  = <key หรือว่าง>

stdlib ล้วน (urllib/socket/json) — ไม่เพิ่ม dependency
"""

from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# ให้ import local_coder (repo root) ได้ ไม่ว่าถูกเรียกจากไหน
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from local_coder import call_ollama  # noqa: E402
from app import config_manager  # noqa: E402

DEFAULT_OPENAI_BASE = "http://127.0.0.1:8000/v1"


class BackendError(Exception):
    """เรียก backend ไม่สำเร็จ (ต่อไม่ได้ / response พัง) — ผู้เรียกแปลงเป็น 502 ได้"""


class Backend:
    """เต้ารับมาตรฐาน: ทุก backend ต้องทำ 3 อย่างนี้ให้ครบ"""
    name = "base"

    def is_available(self) -> bool:
        raise NotImplementedError

    def generate(self, model: str, messages: list, num_ctx: int = 8192,
                 options: Optional[dict] = None) -> str:
        raise NotImplementedError


class OllamaBackend(Backend):
    """ของที่พิสูจน์แล้ววันนี้ — ห่อ call_ollama เดิม (local 127.0.0.1:11434)"""
    name = "ollama"

    def __init__(self, host: str = "127.0.0.1", port: int = 11434):
        self.host = host
        self.port = port

    def is_available(self, timeout: float = 0.3) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout):
                return True
        except OSError:
            return False

    def generate(self, model, messages, num_ctx=8192, options=None) -> str:
        try:
            return call_ollama(model, messages, num_ctx, options=options)
        except SystemExit as e:
            # call_ollama ออกแบบมา exit ตอน error (CLI) — ในฐานะ library ต้องไม่ฆ่าโปรเซส
            raise BackendError("เรียก Ollama ไม่สำเร็จ (ตรวจว่า `ollama serve` รันอยู่ไหม)") from e


class OpenAICompatBackend(Backend):
    """เผื่ออนาคต — คุยภาษา OpenAI /chat/completions (vLLM, llama.cpp server, cloud ฯลฯ)"""
    name = "openai_compat"

    def __init__(self, base_url: str = DEFAULT_OPENAI_BASE, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or None

    def is_available(self, timeout: float = 0.3) -> bool:
        try:
            p = urllib.parse.urlparse(self.base_url)
            host = p.hostname or "127.0.0.1"
            port = p.port or (443 if p.scheme == "https" else 80)
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def generate(self, model, messages, num_ctx=8192, options=None) -> str:
        payload = {"model": model, "messages": messages}
        # num_ctx เป็นแนวคิดของ local runtime — ฝั่ง OpenAI คุมที่ server เอง จึงไม่ส่ง
        if options:
            for k in ("temperature", "top_p", "seed", "max_tokens"):
                if k in options:
                    payload[k] = options[k]
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as e:
            raise BackendError(f"ต่อ OpenAI-compatible backend ไม่ได้: {e}") from e
        try:
            return json.loads(raw)["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise BackendError(f"response จาก backend ผิดรูปแบบ: {e}") from e


def get_backend(project_root) -> Backend:
    """เลือก backend จาก config (default ollama) — ไม่สลับเองเงียบๆ อ่านจากที่คนตั้งเท่านั้น"""
    sel = (config_manager.get_key(project_root, "MODEL_BACKEND") or "ollama").strip().lower()
    if sel in ("openai", "openai_compat", "openai-compat"):
        base = config_manager.get_key(project_root, "OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE
        key = config_manager.get_key(project_root, "OPENAI_API_KEY") or None
        return OpenAICompatBackend(base, key)
    return OllamaBackend()


def generate(project_root, model, messages, num_ctx: int = 8192,
             options: Optional[dict] = None) -> str:
    """สะดวก: เลือก backend ตาม config แล้ว generate — แอปเรียกตัวนี้ตัวเดียวจบ"""
    return get_backend(project_root).generate(model, messages, num_ctx, options)


# ---------- Settings: ตั้งค่า/เสียบ cloud GPU ผ่าน OpenAI-compatible adapter ----------
# ทำให้ "เสียบคลาวด์ GPU" ทำได้จากหน้า /dev ไม่ต้องแก้ config.json มือ
#   MODEL_BACKEND   : ollama | openai   (default ollama)
#   OPENAI_BASE_URL : http://host:port/v1 (vLLM / llama.cpp server / RunPod / cloud)
#   OPENAI_API_KEY  : key ของ endpoint (ไม่ print เต็ม — แค่บอกว่าตั้งไว้ไหม, Rule 23)
SETTINGS_KEYS = ("MODEL_BACKEND", "OPENAI_BASE_URL", "OPENAI_API_KEY")
_VALID_BACKENDS = ("ollama", "openai")


def get_backend_settings(project_root) -> dict:
    """อ่านการตั้งค่า backend — ไม่คืน OPENAI_API_KEY เต็ม (แค่ bool ว่าตั้งไว้ไหม)"""
    sel = (config_manager.get_key(project_root, "MODEL_BACKEND") or "ollama").strip().lower()
    if sel in ("openai_compat", "openai-compat"):
        sel = "openai"
    return {
        "MODEL_BACKEND": sel if sel in _VALID_BACKENDS else "ollama",
        "OPENAI_BASE_URL": config_manager.get_key(project_root, "OPENAI_BASE_URL") or "",
        "openai_api_key_set": bool(config_manager.get_key(project_root, "OPENAI_API_KEY")),
    }


def set_backend_settings(project_root, values: dict) -> dict:
    """ตั้งค่า backend — validate ค่า, เขียนเฉพาะคีย์ที่รู้จัก. คืน get_backend_settings ใหม่
    OPENAI_API_KEY ส่งมาเฉพาะตอนจะเปลี่ยน (ไม่ส่ง = ไม่ทับของเดิม)"""
    if "MODEL_BACKEND" in values and values["MODEL_BACKEND"]:
        sel = str(values["MODEL_BACKEND"]).strip().lower()
        if sel in ("openai_compat", "openai-compat"):
            sel = "openai"
        if sel not in _VALID_BACKENDS:
            raise ValueError(f"MODEL_BACKEND ต้องเป็น {list(_VALID_BACKENDS)} (ได้ {sel!r})")
        config_manager.set_key(project_root, "MODEL_BACKEND", sel)
    if values.get("OPENAI_BASE_URL"):
        base = str(values["OPENAI_BASE_URL"]).strip().rstrip("/")
        p = urllib.parse.urlparse(base)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ValueError(f"OPENAI_BASE_URL ไม่ถูกต้อง: {base!r} (ต้องเป็น http(s)://host:port/v1)")
        config_manager.set_key(project_root, "OPENAI_BASE_URL", base)
    if values.get("OPENAI_API_KEY"):
        config_manager.set_key(project_root, "OPENAI_API_KEY", str(values["OPENAI_API_KEY"]).strip())
    return get_backend_settings(project_root)


def probe_backend(project_root) -> dict:
    """เช็กว่า backend ที่ตั้งไว้ "ต่อติดไหม" (is_available) — ไว้กดทดสอบจากหน้า /dev
    ไม่ generate จริง (ไม่กิน token/ไม่เสียเงิน) แค่เช็ก endpoint reachable"""
    backend = get_backend(project_root)
    try:
        ok = backend.is_available()
    except Exception as e:  # pragma: no cover - is_available ควร degrade อยู่แล้ว
        return {"backend": backend.name, "available": False, "error": e.__class__.__name__}
    return {"backend": backend.name, "available": bool(ok)}
