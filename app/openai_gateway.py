"""OpenAI-compatible API ของ LCA: ให้ลูกค้าเรียกโมเดลในเครื่องเจ้าของด้วย client ของ OpenAI ได้เลย

- GET  /v1/models            → โมเดลที่ Ollama ติดตั้งและพร้อมเสิร์ฟ (รูปแบบ OpenAI list)
- POST /v1/chat/completions  → ส่งต่อไป Ollama /v1/chat/completions (stream หรือไม่ stream)

ฟรี: ไม่มี API ภายนอก ใช้ Ollama ที่ 127.0.0.1 เท่านั้น
ความปลอดภัย: รับเฉพาะโมเดลที่ติดตั้งจริง, ส่งต่อเฉพาะฟิลด์ที่อนุญาต, จำกัด max_tokens
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator

from app import model_manager

OLLAMA_BASE = model_manager.OLLAMA_BASE
MAX_TOKENS_CAP = 1024          # ต่อคำขอ — เครื่อง 8 GB ตอบได้ ~10–22 tok/s
DEFAULT_MAX_TOKENS = 256
ALLOWED_FIELDS = ("messages", "temperature", "top_p", "stop", "seed", "presence_penalty",
                  "frequency_penalty")


class GatewayError(Exception):
    """error ที่ตอบกลับลูกค้าได้: status + ข้อความ (รูปแบบ OpenAI error)"""

    def __init__(self, status: int, message: str, code: str = "invalid_request_error"):
        super().__init__(message)
        self.status = status
        self.code = code

    def body(self) -> dict:
        return {"error": {"message": str(self), "type": self.code, "code": self.code}}


def list_models(opener: Callable = urllib.request.urlopen) -> dict:
    """โมเดลที่ติดตั้งใน Ollama ตอนนี้ — Ollama ล่มคืน list ว่าง ไม่ใช่รายการปลอม"""
    _running, installed = model_manager.installed_models(OLLAMA_BASE, opener=opener)
    now = int(time.time())
    return {"object": "list",
            "data": [{"id": m["name"], "object": "model", "created": now, "owned_by": "local"}
                     for m in installed]}


def build_request(body: dict, installed: set) -> dict:
    """ตรวจและย่อ body ของลูกค้าให้เหลือเฉพาะที่ส่งต่อได้"""
    if not isinstance(body, dict):
        raise GatewayError(400, "body ต้องเป็น JSON object")
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise GatewayError(400, "ต้องระบุ model")
    if model not in installed:
        raise GatewayError(404, f"ไม่มีโมเดล '{model}' ในเครื่องนี้ ดูรายการที่ GET /v1/models",
                           "model_not_found")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise GatewayError(400, "ต้องมี messages อย่างน้อย 1 ข้อความ")
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant") \
                or not isinstance(m.get("content"), str):
            raise GatewayError(400, "messages แต่ละตัวต้องมี role (system/user/assistant) และ content เป็นข้อความ")
    out = {k: body[k] for k in ALLOWED_FIELDS if k in body}
    out["model"] = model
    try:
        want = int(body.get("max_tokens") or DEFAULT_MAX_TOKENS)
    except (TypeError, ValueError):
        raise GatewayError(400, "max_tokens ต้องเป็นตัวเลข") from None
    out["max_tokens"] = max(1, min(want, MAX_TOKENS_CAP))
    out["stream"] = bool(body.get("stream"))
    return out


def _open(payload: dict, timeout: float, opener: Callable):
    req = urllib.request.Request(f"{OLLAMA_BASE}/v1/chat/completions",
                                 data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        return opener(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise GatewayError(502, f"Ollama ตอบ HTTP {e.code}", "upstream_error") from e
    except (OSError, urllib.error.URLError) as e:
        raise GatewayError(503, "ติดต่อ Ollama ไม่ได้ — เครื่องปลายทางอาจปิดอยู่", "upstream_unavailable") from e


def complete(payload: dict, timeout: float = 180.0,
             opener: Callable = urllib.request.urlopen) -> dict:
    """ไม่ stream: คืน JSON รูปแบบ OpenAI จาก Ollama"""
    with _open(dict(payload, stream=False), timeout, opener) as resp:
        try:
            return json.loads(resp.read().decode("utf-8"))
        except ValueError as e:
            raise GatewayError(502, "Ollama ตอบรูปแบบไม่ถูกต้อง", "upstream_error") from e


def stream(payload: dict, timeout: float = 180.0,
           opener: Callable = urllib.request.urlopen) -> Iterator[bytes]:
    """stream: ส่งต่อบรรทัด SSE (`data: ...`) จาก Ollama ทีละบรรทัด จนถึง `data: [DONE]`"""
    resp = _open(dict(payload, stream=True), timeout, opener)
    with resp:
        try:
            for raw in resp:
                line = raw.strip()
                if line.startswith(b"data:"):
                    yield line + b"\n\n"
        except (OSError, ValueError) as e:
            raise GatewayError(502, "การเชื่อมต่อกับ Ollama หลุดกลางทาง", "upstream_error") from e
