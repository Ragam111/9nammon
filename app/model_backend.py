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
