"""resource_budget.py — "ก้านสมอง" จัดการทรัพยากรของ LCA

หน้าที่: ดู RAM ว่างจริง แล้วตัดสินใจว่า "เครื่องนี้ไหวโมเดลขนาดไหน" + "ควรใช้ compute
backend อะไร" — ตัดสินจากข้อมูลจริง ไม่ hardcode (ตาม RESOURCE_MANAGER_DESIGN.md /
HETEROGENEOUS_COMPUTE.md / BENCHMARK_RESULTS.md)

ออกแบบให้เบาและปลอดภัย: *ไม่โหลดโมเดลเอง* แค่ "แนะนำ/ตัดสินใจ" เท่านั้น เทสง่าย
dependency: psutil (ตัวเดียวนอก stdlib ที่โปรเจกต์ใช้อยู่แล้ว) — ถ้าไม่มีก็ degrade ได้
"""

from __future__ import annotations

from typing import Optional

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - psutil ไม่ควรหายบน prod แต่กันพัง
    psutil = None  # type: ignore

from app import config_manager

GB = 1024 ** 3

# กันไว้ให้ OS + เบราว์เซอร์ + web server (อย่ายัดโมเดลจน RAM หมดเกลี้ยง)
HEADROOM = int(1.5 * GB)

# footprint โดยประมาณของโมเดล quantized (bytes) — จูนได้ตามจริง
MODEL_FOOTPRINT = {
    "qwen2.5-coder:0.5b": int(0.6 * GB),
    "qwen2.5-coder:1.5b": int(1.2 * GB),
    "qwen2.5-coder:7b": int(5.0 * GB),
}

# เรียงเล็ก→ใหญ่ สำหรับไล่เลือก (เล็กสุดคือ fallback ที่ปลอดภัยสุด)
MODELS_SMALL_TO_LARGE = ["qwen2.5-coder:0.5b", "qwen2.5-coder:1.5b", "qwen2.5-coder:7b"]


def available_ram() -> int:
    """RAM ว่างจริง (bytes). คืน 0 = ไม่ทราบ (ให้ผู้เรียกเลือกทางปลอดภัย)"""
    if psutil is not None:
        try:
            return int(psutil.virtual_memory().available)
        except Exception:
            pass
    # fallback Linux (บน Windows จะไม่มีไฟล์นี้ → คืน 0)
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def ram_pressure(threshold_percent: float = 85.0) -> bool:
    """RAM ใช้ไปเกิน threshold ไหม (บอกว่า "ตึง") — ไม่ทราบ = False (ไม่ตกใจเกินเหตุ)"""
    if psutil is None:
        return False
    try:
        return float(psutil.virtual_memory().percent) >= threshold_percent
    except Exception:
        return False


def fits(model: str, avail: Optional[int] = None) -> bool:
    """โมเดลนี้ใส่ได้ไหม (footprint + headroom <= RAM ว่าง)"""
    if avail is None:
        avail = available_ram()
    fp = MODEL_FOOTPRINT.get(model)
    if fp is None or avail <= 0:
        return False
    return fp + HEADROOM <= avail


def pick_model(preferred: Optional[str] = None, avail: Optional[int] = None) -> dict:
    """เลือกโมเดลที่เหมาะกับ RAM ว่างตอนนี้
    - preferred ใส่ได้ → ใช้ preferred
    - ไม่งั้นเลือก "ใหญ่สุดที่ยังใส่ได้"
    - ไม่มีตัวไหนใส่ได้ / ไม่ทราบ RAM → เล็กสุด (best effort)
    คืน {model, reason, available_ram, fits}
    """
    if avail is None:
        avail = available_ram()

    smallest = MODELS_SMALL_TO_LARGE[0]

    if avail <= 0:
        return {"model": smallest, "reason": "ไม่ทราบ RAM ว่าง — เลือกเล็กสุดไว้ก่อน",
                "available_ram": avail, "fits": True}

    if preferred and preferred in MODEL_FOOTPRINT and fits(preferred, avail):
        return {"model": preferred, "reason": "ใช้ตามที่ขอ (RAM รับไหว)",
                "available_ram": avail, "fits": True}

    for m in reversed(MODELS_SMALL_TO_LARGE):
        if fits(m, avail):
            return {"model": m, "reason": "ใหญ่สุดที่ RAM ว่างรับไหว",
                    "available_ram": avail, "fits": True}

    return {"model": smallest, "reason": "RAM ตึง — เลือกเล็กสุด (อาจช้า)",
            "available_ram": avail, "fits": False}


def pick_backend(project_root) -> dict:
    """เลือก compute backend จากผลวัดที่เก็บไว้ (config COMPUTE_*)
    default = cpu / ngl 0 — ตาม BENCHMARK_RESULTS.md (CPU ชนะ iGPU บนเครื่องสเปกต่ำ)
    ไม่สลับ backend เองเงียบๆ — อ่านจาก config ที่คนตั้งจากผล benchmark เท่านั้น
    คืน {backend, device, ngl, source}
    """
    measured = config_manager.get_key(project_root, "COMPUTE_BACKEND")
    backend = measured or "cpu"
    device = config_manager.get_key(project_root, "COMPUTE_DEVICE")
    ngl = config_manager.get_key(project_root, "COMPUTE_NGL") or "0"
    return {
        "backend": backend,
        "device": device,
        "ngl": ngl,
        "source": "measured" if measured else "default",
    }


def budget_report(project_root) -> dict:
    """ภาพรวมงบ RAM + โมเดลที่แนะนำ + backend — เอาไปโชว์หน้า /dev ได้"""
    avail = available_ram()
    models = [
        {"model": m, "footprint": MODEL_FOOTPRINT[m], "fits": fits(m, avail)}
        for m in MODELS_SMALL_TO_LARGE
    ]
    rec = pick_model(avail=avail)
    return {
        "available_ram": avail,
        "headroom": HEADROOM,
        "ram_pressure": ram_pressure(),
        "models": models,
        "recommended_model": rec["model"],
        "recommend_reason": rec["reason"],
        "backend": pick_backend(project_root),
    }
