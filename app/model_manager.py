"""ตัวจัดการโมเดล local (แผน C ใน docs/LCA_SPEC.md)

- catalog(): รายการโมเดลตระกูล qwen ที่อนุญาต + สถานะ "fit / tight / no" เทียบ RAM ว่าง
  + รายการที่ติดตั้งใน Ollama แล้วทั้งหมด (รวมตัวที่ไม่อยู่ใน catalog)
- pull(): ดึงโมเดลผ่าน Ollama POST /api/pull แบบ stream ทีละบรรทัด รับเฉพาะชื่อใน ALLOWED

stdlib ล้วน (urllib) — Ollama ต้องอยู่ที่ 127.0.0.1 เท่านั้น
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator

OLLAMA_BASE = "http://127.0.0.1:11434"
GB = 1024 ** 3

# ขนาดไฟล์โมเดล quantized โดยประมาณ (GB) จากหน้า library ของ Ollama — ใช้เทียบ RAM เท่านั้น
ALLOWED: dict[str, dict] = {
    "qwen2.5-coder:0.5b": {"size_gb": 0.4, "use": "เขียนโค้ด เร็ว เบา"},
    "qwen2.5-coder:1.5b": {"size_gb": 1.0, "use": "เขียนโค้ด แก้โค้ดได้แม่นกว่า (แนะนำ)"},
    "qwen2.5-coder:3b": {"size_gb": 1.9, "use": "เขียนโค้ด คุณภาพสูงขึ้น ต้องการ RAM มากขึ้น"},
    "qwen2.5-coder:7b": {"size_gb": 4.7, "use": "เขียนโค้ด คุณภาพสูง เหมาะ RAM 16 GB ขึ้นไป"},
    "qwen2.5:1.5b": {"size_gb": 1.0, "use": "คุยทั่วไป ภาษาไทยได้"},
    "qwen2.5:3b": {"size_gb": 1.9, "use": "คุยทั่วไป คุณภาพสูงขึ้น"},
}


class ModelManagerError(Exception):
    """ผิดพลาดที่ส่งต่อให้ผู้ใช้ได้ (ข้อความไทย)"""


def fit_status(size_gb: float, free_gb: float | None) -> str:
    """fit = โหลดได้สบาย, tight = พอโหลดได้แต่อาจช้า/swap, no = RAM ไม่พอ, unknown = วัดไม่ได้

    เกณฑ์: โมเดลกิน RAM ราว 1.3 เท่าของขนาดไฟล์ระหว่างรัน — fit เมื่อมีเผื่ออีก 1.5 เท่า,
    tight เมื่อ RAM ว่างอย่างน้อยเท่าขนาดไฟล์ (วัดจริงบนเครื่อง 8 GB: 1.5b รันได้ตอน RAM ว่าง ~1 GB แต่ช้า)
    """
    if free_gb is None or free_gb <= 0:
        return "unknown"
    if free_gb >= size_gb * 1.3 * 1.5:
        return "fit"
    if free_gb >= size_gb:
        return "tight"
    return "no"


def installed_models(base: str = OLLAMA_BASE, timeout: float = 2.0,
                     opener: Callable = urllib.request.urlopen) -> tuple[bool, list[dict]]:
    """(ollama_running, [{name, size_gb}]) จาก GET /api/tags — ไม่ raise ตอน Ollama ล่ม"""
    try:
        with opener(f"{base}/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False, []
    items = data.get("models") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return False, []
    out = []
    for m in items:
        if isinstance(m, dict) and m.get("name"):
            size = m.get("size")
            out.append({"name": str(m["name"]),
                        "size_gb": round(size / GB, 2) if isinstance(size, (int, float)) else None})
    return True, sorted(out, key=lambda x: x["name"])


def catalog(free_bytes: int, total_bytes: int, base: str = OLLAMA_BASE,
            opener: Callable = urllib.request.urlopen) -> dict:
    """ข้อมูลทั้งหมดที่หน้า "จัดการโมเดล" ต้องใช้"""
    free_gb = round(free_bytes / GB, 2) if free_bytes > 0 else None
    total_gb = round(total_bytes / GB, 2) if total_bytes > 0 else None
    running, installed = installed_models(base, opener=opener)
    names = {m["name"] for m in installed}
    rows = [{"name": name, "size_gb": info["size_gb"], "use": info["use"],
             "fit": fit_status(info["size_gb"], free_gb), "installed": name in names}
            for name, info in ALLOWED.items()]
    return {"ram_free_gb": free_gb, "ram_total_gb": total_gb, "ollama_running": running,
            "installed": installed, "catalog": rows}


def pull(name: str, base: str = OLLAMA_BASE, timeout: float = 30.0,
         opener: Callable = urllib.request.urlopen) -> Iterator[dict]:
    """ดึงโมเดลทีละขั้น: yield dict จาก Ollama (status, completed, total) จนจบ

    ชื่อต้องอยู่ใน ALLOWED เท่านั้น (กันสั่งดึงอะไรก็ได้ผ่าน API)
    """
    if name not in ALLOWED:
        raise ModelManagerError(f"ไม่อนุญาตให้ติดตั้งโมเดล '{name}' — เลือกจากรายการที่แนะนำ")
    body = json.dumps({"model": name, "stream": True}).encode("utf-8")
    req = urllib.request.Request(f"{base}/api/pull", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        resp = opener(req, timeout=timeout)
    except (OSError, urllib.error.URLError) as e:
        raise ModelManagerError("ติดต่อ Ollama ไม่ได้ — ตรวจว่า Ollama ทำงานอยู่") from e
    with resp:
        yield from _read_events(resp)


def _read_events(resp) -> Iterator[dict]:
    """อ่าน NDJSON จาก Ollama — connection หลุดกลางทาง (Ollama crash/restart) → ModelManagerError"""
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("error"):
                raise ModelManagerError(f"Ollama ติดตั้งไม่สำเร็จ: {event['error']}")
            if isinstance(event, dict):
                yield event
    except (OSError, http.client.HTTPException) as e:
        raise ModelManagerError("การเชื่อมต่อกับ Ollama หลุดกลางทาง — ลองติดตั้งใหม่อีกครั้ง") from e
