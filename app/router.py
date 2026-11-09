"""
router.py — Multi-tier Ollama model selector

recommend(project_root) → dict
  เรียก hw_profile เพื่อรู้ tier จริง แล้วคืนรายการโมเดลที่เหมาะ + เช็คว่า
  Ollama รันอยู่และมีโมเดลไหนติดตั้งแล้วบ้าง (urllib stdlib, ไม่มี subprocess)

GET /api/models/recommend — USER-gated
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from urllib.error import URLError

# ---------------------------------------------------------------------------
# โมเดลแนะนำตาม tier — เรียงจากเหมาะที่สุด → fallback
# ---------------------------------------------------------------------------
_TIER_MODELS: dict[str, list[dict]] = {
    "netbook": [
        {
            "name": "qwen2.5-coder:1.5b",
            "size_gb": 1.0,
            "description": "โมเดลเล็กที่แก้โค้ด SEARCH/REPLACE ได้จริง (benchmark: 11/11) — แนะนำสุด",
            "priority": 1,
        },
        {
            "name": "qwen2.5-coder:0.5b",
            "size_gb": 0.6,
            "description": "เล็กสุด — fallback เมื่อ RAM < 2GB ว่าง",
            "priority": 2,
        },
        {
            "name": "llama3.2:1b",
            "size_gb": 1.3,
            "description": "Meta Llama 3.2 1B — ทางเลือกทั่วไป ไม่เน้น code",
            "priority": 3,
        },
    ],
    "workstation": [
        {
            "name": "qwen2.5-coder:7b",
            "size_gb": 4.7,
            "description": "โมเดลกลาง coding — รันลื่นบน SSD + 16GB+ RAM แนะนำสุด",
            "priority": 1,
        },
        {
            "name": "codellama:7b",
            "size_gb": 3.8,
            "description": "Meta CodeLlama 7B — ทางเลือก coding รุ่นเก่าแต่ stable",
            "priority": 2,
        },
        {
            "name": "llama3.1:8b",
            "size_gb": 4.7,
            "description": "Meta Llama 3.1 8B — general purpose ใช้ได้กับทุกงาน",
            "priority": 3,
        },
        {
            "name": "qwen2.5-coder:1.5b",
            "size_gb": 1.0,
            "description": "fallback สำหรับ workstation ที่ RAM ตึง",
            "priority": 4,
        },
    ],
    "server": [
        {
            "name": "qwen2.5-coder:32b",
            "size_gb": 20.0,
            "description": "Qwen2.5 Coder 32B — coding เกรด server แนะนำสุดถ้ามี VRAM/RAM >=24GB",
            "priority": 1,
        },
        {
            "name": "deepseek-coder-v2:16b",
            "size_gb": 10.0,
            "description": "DeepSeek Coder V2 16B — balance ระหว่างขนาดและคุณภาพ",
            "priority": 2,
        },
        {
            "name": "codellama:34b",
            "size_gb": 19.0,
            "description": "Meta CodeLlama 34B — coding server tier",
            "priority": 3,
        },
        {
            "name": "llama3.1:70b",
            "size_gb": 40.0,
            "description": "Meta Llama 3.1 70B — general purpose ขนาดใหญ่ (ต้องการ RAM >=48GB)",
            "priority": 4,
        },
        {
            "name": "qwen2.5-coder:7b",
            "size_gb": 4.7,
            "description": "fallback สำหรับ server ที่ RAM จำกัด",
            "priority": 5,
        },
    ],
}

# ---------------------------------------------------------------------------
# Cache — ไม่วัด hw_profile ซ้ำทุก request (เบา profile ไม่วัด disk แต่ก็ใช้เวลา)
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: dict[str, object] = {}  # key → (ts, value)
_TTL = 300  # 5 minutes


def _ollama_installed_models(base_url: str = "http://127.0.0.1:11434",
                              timeout: int = 3) -> tuple[bool, list[str]]:
    """ดึงรายการโมเดลที่ติดตั้งใน Ollama (GET /api/tags).
    คืน (ollama_running, [model_names])"""
    try:
        req = urllib.request.Request(
            f"{base_url}/api/tags",
            headers={"User-Agent": "LCA-router/1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in data.get("models", [])]
        return True, [n for n in names if n]
    except (URLError, OSError, json.JSONDecodeError, KeyError):
        return False, []


def recommend(project_root, ollama_base: str = "http://127.0.0.1:11434") -> dict:
    """คืนโมเดลแนะนำตาม tier + สถานะ Ollama

    Returns:
        tier          : "netbook" | "workstation" | "server" | "unknown"
        tier_reasons  : list[str]
        models        : list[{name, size_gb, description, priority, installed}]
        top_pick      : str — โมเดลที่แนะนำสุด (priority 1 หรือ installed priority ต่ำสุด)
        ollama_running: bool
        installed     : list[str] — โมเดลที่ติดตั้งใน Ollama แล้ว
        cached_until  : float (unix timestamp)
    """
    cache_key = f"router:{project_root}:{ollama_base}"
    now = time.time()
    with _cache_lock:
        entry = _cache.get(cache_key)
        if entry and now < entry[0]:  # type: ignore[index]
            return dict(entry[1])  # type: ignore[index]

    # -- tier จาก hw_profile (ไม่วัด disk — เร็ว) --
    try:
        from app import hw_profile as _hwp
        p = _hwp.profile(project_root=project_root, measure_disk=False)
        tier: str = p.get("tier", "unknown")
        tier_reasons: list[str] = p.get("tier_reasons", [])
    except Exception:
        tier = "unknown"
        tier_reasons = []

    # -- รายการโมเดลตาม tier --
    models = list(_TIER_MODELS.get(tier, _TIER_MODELS["netbook"]))

    # -- Ollama: รันอยู่ไหม + มีโมเดลไหนติดตั้งแล้ว --
    ollama_running, installed = _ollama_installed_models(ollama_base)

    installed_set = set(installed)
    for m in models:
        m["installed"] = m["name"] in installed_set

    # top_pick: installed priority ต่ำสุดก่อน ถ้าไม่มี installed ใดเลยใช้ priority 1
    installed_models = [m for m in models if m["installed"]]
    if installed_models:
        top_pick = min(installed_models, key=lambda x: x["priority"])["name"]
    else:
        top_pick = models[0]["name"] if models else ""

    result = {
        "tier": tier,
        "tier_reasons": tier_reasons,
        "models": models,
        "top_pick": top_pick,
        "ollama_running": ollama_running,
        "installed": installed,
        "cached_until": now + _TTL,
    }

    with _cache_lock:
        _cache[cache_key] = (now + _TTL, result)
    return dict(result)
