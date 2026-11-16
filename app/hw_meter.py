"""
hw_meter.py — compact hardware meter: CPU %, RAM, tier (real-time snapshot)

snapshot(project_root) → dict  (เรียกจาก GET /api/metrics/hw)
รวม live collect() + hw_profile tier ใน 1 call เดียว — ไม่วัด disk (เร็ว)
"""

from __future__ import annotations

from pathlib import Path

GB = 1_073_741_824  # 1 GiB


def snapshot(project_root, interval: float = 0.2) -> dict:
    """snapshot สด: CPU %, RAM %, tier จาก hw_profile

    interval  = วินาทีที่ collect() วัด CPU (ค่าน้อย = เร็วแต่อ่านผิดได้นิดหน่อย)
    """
    from sysmanager.monitor import collect as _collect
    from app import hw_profile

    snap = _collect(interval=interval)
    mem = snap.memory
    cpu = snap.cpu

    ram_total_gb = round(mem.total / GB, 2)
    ram_used_gb = round(mem.used / GB, 2)
    ram_pct = round(mem.percent, 1)

    try:
        profile = hw_profile.profile(project_root=Path(project_root), measure_disk=False)
        tier = profile.get("tier", "unknown")
        tier_reasons = profile.get("tier_reasons", [])
        recommended_model = (profile.get("recommended_config") or {}).get("PREFERRED_MODEL", "")
    except Exception:
        tier = "unknown"
        tier_reasons = []
        recommended_model = ""

    return {
        "cpu_pct": round(cpu.percent, 1),
        "cpu_per_core": [round(x, 1) for x in (cpu.per_core or [])],
        "cpu_freq_mhz": round(cpu.freq_mhz, 0) if cpu.freq_mhz else None,
        "logical_cores": cpu.logical_cores,
        "load_avg_1m": round(cpu.load_avg_1m, 2) if cpu.load_avg_1m else None,
        "ram_pct": ram_pct,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "tier": tier,
        "tier_reasons": tier_reasons,
        "recommended_model": recommended_model,
    }
