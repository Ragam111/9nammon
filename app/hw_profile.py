"""hw_profile.py — "สมอง" ที่ทำให้ LCA รู้จักเครื่องตัวเอง แล้วแนะนำ config (ขั้น 1 สู่ HPC)

ไอเดีย (9arm / HPC): แก่นของ HPC คือ "จับงานให้เข้ากับความสามารถของเครื่อง" — ก่อนจะทำ
แบบนั้นข้ามหลายเครื่องได้ เครื่องต้อง *รู้จักตัวเอง* ก่อน. โมดูลนี้รวมของที่วัดจริง
(sysinfo spec + mem_hierarchy ความเร็ว I/O + resource_budget งบ RAM) แล้ว:
  1. จัดระดับเครื่อง (tier): netbook / workstation / server
  2. แนะนำ config ที่เหมาะ (โมเดล, backend, ngl)
  3. ชี้ "อัปเกรดคุ้มสุดถัดไป" จากของที่วัด (ตาม HPC_SERVER_ARCHITECTURE.md:
     บนเครื่องสเปกต่ำ SSD คุ้มกว่า GPU เก่าเสมอ เพราะคอขวดคือ data movement)

โค้ดเดียวรันได้ทั้ง netbook วันนี้และ server วันหน้า — ต่างกันแค่ "คำแนะนำ" ที่ออกมา
นี่คือก้าวแรกของบันได HPC: self-aware → self-tuning → multi-node → scheduler

stdlib + ของในโปรเจกต์เท่านั้น (ไม่เพิ่ม dependency). วัด disk จริงได้ (ช้า) หรือ
ฉีด mem_result เข้ามา (เทส/เร็ว) ก็ได้
"""

from __future__ import annotations

from typing import Optional

from app import mem_hierarchy, resource_budget

GB = 1024 ** 3

# เกณฑ์จัดระดับ — จูนจากของจริงที่วัดทั้ง session (ไม่ได้เดา):
#   netbook เป้าหมาย = i3-6006U 2C/4T, 8GB, HDD (disk write ~50-100 MB/s)
#   SSD เริ่มที่ ~300 MB/s ขึ้นไป (เส้นแบ่ง HDD/SSD ที่วัดได้จริงชัด)
HDD_WRITE_CEILING_MBPS = 250.0   # เขียนช้ากว่านี้ = HDD (คอขวด I/O)
SERVER_MIN_CORES = 16
SERVER_MIN_RAM_GB = 64
WORKSTATION_MIN_CORES = 4
WORKSTATION_MIN_RAM_GB = 16


def _ram_gb(total_bytes: int) -> float:
    return round(total_bytes / GB, 1)


def classify_tier(physical_cores: int, total_ram_bytes: int,
                  disk_write_mbps: Optional[float],
                  has_compute_gpu: bool) -> dict:
    """จัดระดับเครื่องจากของจริง คืน {tier, reasons[], is_hdd, ram_gb}

    tier:
      - server      : แรงพอรับงานหลายคน/โมเดลใหญ่ หรือมี compute GPU จริง
      - workstation : รันโมเดลกลางได้สบาย I/O เป็น SSD
      - netbook     : เครื่องบาง คอขวด I/O/RAM — ต้องประหยัดทุกอย่าง
    """
    ram_gb = _ram_gb(total_ram_bytes)
    cores = physical_cores or 0
    is_hdd = disk_write_mbps is not None and disk_write_mbps < HDD_WRITE_CEILING_MBPS
    reasons = []

    if (cores >= SERVER_MIN_CORES or ram_gb >= SERVER_MIN_RAM_GB or has_compute_gpu):
        tier = "server"
        if has_compute_gpu:
            reasons.append("มี compute GPU (NVIDIA/AMD discrete) — offload โมเดลใหญ่ได้")
        if cores >= SERVER_MIN_CORES:
            reasons.append(f"CPU {cores} core (>= {SERVER_MIN_CORES}) รับงานขนานได้มาก")
        if ram_gb >= SERVER_MIN_RAM_GB:
            reasons.append(f"RAM {ram_gb}GB (>= {SERVER_MIN_RAM_GB}) จุโมเดลใหญ่")
    elif (cores >= WORKSTATION_MIN_CORES and ram_gb >= WORKSTATION_MIN_RAM_GB and not is_hdd):
        tier = "workstation"
        reasons.append(f"CPU {cores} core + RAM {ram_gb}GB + SSD — รันโมเดลกลางได้สบาย")
    else:
        tier = "netbook"
        if cores < WORKSTATION_MIN_CORES:
            reasons.append(f"CPU {cores} core (< {WORKSTATION_MIN_CORES}) — compute จำกัด")
        if ram_gb < WORKSTATION_MIN_RAM_GB:
            reasons.append(f"RAM {ram_gb}GB (< {WORKSTATION_MIN_RAM_GB}) — คอขวด RAM")
        if is_hdd:
            reasons.append(f"ดิสก์เป็น HDD (เขียน {disk_write_mbps:.0f} MB/s) — คอขวด I/O ชัด")

    return {"tier": tier, "reasons": reasons, "is_hdd": is_hdd, "ram_gb": ram_gb}


def next_upgrade(tier_info: dict, has_compute_gpu: bool) -> str:
    """อัปเกรดคุ้มสุดถัดไป — อิงของที่วัด ไม่ขายฝัน
    หลัก HPC_SERVER_ARCHITECTURE.md: คอขวด = data movement → SSD คุ้มกว่า GPU เก่า"""
    if tier_info["is_hdd"]:
        return ("เปลี่ยน HDD → SSD: คุ้มสุด. คอขวดคือ disk write (วัดแล้ว) ทำให้โหลดโมเดลช้า "
                "— SSD แก้ตรงจุด ถูกกว่าและได้ผลกว่าซื้อ GPU เก่า")
    if tier_info["ram_gb"] < WORKSTATION_MIN_RAM_GB:
        return ("เพิ่ม RAM: โมเดลใหญ่ขึ้น/ctx ยาวขึ้นต้องการ RAM. คุ้มรองจาก SSD")
    if not has_compute_gpu:
        return ("เพิ่ม compute GPU (VRAM >= 8GB เช่น RTX 3060 ขึ้นไป) หรือเช่า cloud GPU "
                "ผ่าน adapter — ก้าวเข้าสู่ heterogeneous compute จริง")
    return "ฮาร์ดแวร์พอแล้ว — ก้าวต่อไปคือเพิ่ม node (scale out) ผ่าน cluster"


def recommend_config(tier_info: dict, project_root=None) -> dict:
    """แนะนำ config ตาม tier — คืน dict คีย์ config + ค่า (ไม่เขียนเอง แค่แนะนำ)
    netbook: โมเดลเล็ก/CPU/ngl0; workstation: โมเดลกลาง; server: ใหญ่สุด/เปิด GPU ถ้ามี"""
    tier = tier_info["tier"]
    # ใช้ resource_budget เลือกโมเดลตาม RAM ว่างจริง (ไม่ hardcode เกินจำเป็น)
    pick = resource_budget.pick_model(project_root=project_root)
    rec = {
        "PREFERRED_MODEL": pick["model"],
        "COMPUTE_BACKEND": "cpu",
        "COMPUTE_NGL": "0",
        "_model_reason": pick["reason"],
    }
    if tier == "server":
        # เครื่องแรง: ถ้ามี compute GPU ค่อยเปิด ngl (คนตั้งยืนยันเองหลัง benchmark)
        rec["COMPUTE_NGL"] = "auto"
        rec["_note"] = "เครื่องแรง: เปิด GPU offload ได้ถ้ามี compute GPU (ยืนยันด้วย benchmark ก่อน)"
    elif tier == "workstation":
        rec["_note"] = "SSD + RAM พอ: รันโมเดลกลางบน CPU ได้ลื่น"
    else:  # netbook
        # ไม่ fix ขนาดโมเดลใน note — PREFERRED_MODEL ข้างบนมาจาก RAM จริงแล้ว
        # (เครื่องบางแต่ RAM เยอะก็อาจได้โมเดลกลาง); note บอก "กลยุทธ์" ไม่ใช่ตัวเลข
        rec["_note"] = ("เครื่องบาง: รันบน CPU, ngl 0 (iGPU แพ้ CPU — วัดแล้ว), "
                        "เปิด streaming ลด latency ที่รู้สึก. โมเดลเลือกตาม RAM จริงให้แล้ว")
    return rec


def profile(project_root=None, sysinfo=None, mem_result=None,
            measure_disk: bool = True, size_mb: int = 32) -> dict:
    """โปรไฟล์เครื่องแบบครบ: spec + I/O ที่วัด + งบ RAM + tier + คำแนะนำ
    - sysinfo/mem_result ฉีดเข้ามาได้ (เทส/เร็ว); ไม่ฉีด = วัด/ตรวจจริง
    - measure_disk=False → ข้ามการวัด disk (เร็ว แต่จัด tier โดยไม่รู้ HDD/SSD)
    คืน dict พร้อมโชว์หน้า /dev หรือ print จาก CLI
    """
    if sysinfo is None:
        from sysmanager.sysinfo import get_system_info
        sysinfo = get_system_info().to_dict()

    cpu = sysinfo.get("cpu", {})
    mem = sysinfo.get("memory", {})
    gpus = sysinfo.get("gpus", []) or []
    physical_cores = cpu.get("physical_cores") or 0
    total_ram = mem.get("total") or 0
    has_compute_gpu = any(g.get("compute_capable") for g in gpus)

    if mem_result is None and measure_disk:
        mem_result = mem_hierarchy.measure_all(size_mb=size_mb)
    disk_write = mem_result.get("disk_write_mbps") if mem_result else None

    tier_info = classify_tier(physical_cores, total_ram, disk_write, has_compute_gpu)
    rec = recommend_config(tier_info, project_root=project_root)
    return {
        "tier": tier_info["tier"],
        "tier_reasons": tier_info["reasons"],
        "cpu_model": cpu.get("model", "unknown"),
        "physical_cores": physical_cores,
        "ram_gb": tier_info["ram_gb"],
        "is_hdd": tier_info["is_hdd"],
        "has_compute_gpu": has_compute_gpu,
        "gpus": [g.get("name") for g in gpus],
        "io": mem_result,
        "recommended_config": rec,
        "next_upgrade": next_upgrade(tier_info, has_compute_gpu),
    }


def format_report(p: dict) -> str:
    """รายงานอ่านง่าย — ระดับเครื่อง + คำแนะนำ + อัปเกรดถัดไป"""
    lines = [
        f"=== LCA Hardware Profile — ระดับ: {p['tier'].upper()} ===",
        f"CPU : {p['cpu_model']} ({p['physical_cores']} core)",
        f"RAM : {p['ram_gb']} GB",
        f"ดิสก์: {'HDD (คอขวด I/O)' if p['is_hdd'] else 'SSD/เร็ว'}",
        f"GPU : {', '.join(p['gpus']) or 'ไม่พบ'}"
        + (" [compute ได้]" if p['has_compute_gpu'] else " [แสดงผล/ไม่ใช่ compute]"),
        "",
        "เหตุผลจัดระดับ:",
    ]
    lines += [f"  - {r}" for r in p["tier_reasons"]]
    lines += ["", "แนะนำ config:"]
    for k, v in p["recommended_config"].items():
        if not k.startswith("_"):
            lines.append(f"  {k} = {v}")
    note = p["recommended_config"].get("_note")
    if note:
        lines.append(f"  → {note}")
    lines += ["", f"อัปเกรดคุ้มสุดถัดไป:\n  {p['next_upgrade']}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="โปรไฟล์ฮาร์ดแวร์ LCA + แนะนำ config สู่ HPC")
    ap.add_argument("--no-disk", action="store_true",
                    help="ข้ามการวัด disk (เร็วขึ้น แต่ไม่รู้ HDD/SSD)")
    ap.add_argument("--size-mb", type=int, default=32, help="ขนาดบล็อกวัด I/O (MB)")
    args = ap.parse_args(argv)
    p = profile(measure_disk=not args.no_disk, size_mb=args.size_mb)
    print(format_report(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
