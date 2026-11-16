"""lca_context.py — ต่อยอด analyzer ให้ "รู้จักบริบท LCA" โดยเฉพาะ Ollama

เครื่องเป้าหมายของ LCA มี RAM จำกัด (8GB) — ตัวกินแรมหลักคือ Ollama ตอนโหลดโมเดล.
โมดูลนี้ส่องหา process ollama จาก snapshot แล้ว correlate ว่า RAM/swap ที่พุ่งขึ้น
"น่าจะมาจากการโหลดโมเดลใหญ่" หรือไม่ เพื่อให้คำแนะนำเฉพาะ LCA (เช่น ใช้โมเดล
quantized ตัวเล็กลง / ปิดโมเดลที่ไม่ใช้)

ทำไมแยกจาก analyzer generic: analyzer ต้อง reusable กับเครื่อง/งานอื่น ไม่ควรผูกกับ
Ollama โดยตรง — ความรู้เฉพาะ LCA จึงอยู่ไฟล์นี้แทน (รับ Report ที่ analyzer ผลิตมา)
"""

from __future__ import annotations

from .analyzer import Report, Severity
from .snapshot import Snapshot

# ชื่อ process ที่ถือว่าเป็น Ollama (เทียบแบบ substring ตัวพิมพ์เล็ก)
OLLAMA_NAME_HINTS = ("ollama",)


def detect_ollama(snapshot: Snapshot) -> list:
    """คืนรายการ process ที่น่าจะเป็น Ollama (ดูจากชื่อใน top_by_memory/top_by_cpu)
    dedupe ด้วย pid — process เดียวอาจโผล่ทั้งสองลิสต์"""
    seen: dict[int, dict] = {}
    for p in list(snapshot.top_by_memory) + list(snapshot.top_by_cpu):
        name = (p.name or "").lower()
        if any(h in name for h in OLLAMA_NAME_HINTS):
            seen[p.pid] = {
                "pid": p.pid,
                "name": p.name,
                "cpu_percent": p.cpu_percent,
                "memory_percent": p.memory_percent,
                "memory_rss": p.memory_rss,
            }
    return list(seen.values())


def _fmt_bytes(n: float) -> str:
    step = 1024.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < step:
            return f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} PiB"


def correlate(report: Report) -> dict:
    """วิเคราะห์บริบท LCA จาก Report (ที่ analyzer ผลิต)

    คืน dict:
        ollama_running      : พบ process ollama ไหม
        ollama_processes    : รายการ process ollama (pid/ชื่อ/แรม)
        ollama_rss          : ผลรวม RSS ของ ollama (bytes)
        ollama_mem_percent  : ผลรวม %RAM ของ ollama
        memory_pressure     : RAM/swap อยู่ในภาวะกดดัน (>= WARNING) ไหม
        note                : คำอธิบาย/คำแนะนำเฉพาะ LCA (ภาษาไทย)
    """
    snap = report.snapshot
    procs = detect_ollama(snap)
    running = len(procs) > 0
    rss = sum(p["memory_rss"] for p in procs)
    mem_pct = round(sum(p["memory_percent"] for p in procs), 1)

    pressure_findings = [
        f for f in report.findings
        if f.resource in ("MEMORY", "SWAP") and f.severity >= Severity.WARNING
    ]
    pressure = len(pressure_findings) > 0

    if pressure and running:
        note = (
            f"RAM/swap กำลังกดดัน และพบ Ollama ใช้ ~{mem_pct:.0f}% ({_fmt_bytes(rss)}) — "
            f"น่าจะมาจากการโหลดโมเดลใหญ่เกินเครื่อง. ลองใช้โมเดล quantized ตัวเล็กลง "
            f"(เช่น :0.5b/:1.5b) หรือ `ollama stop` โมเดลที่ไม่ได้ใช้ เพื่อคืน RAM"
        )
    elif pressure and not running:
        note = (
            "RAM/swap กำลังกดดัน แต่ไม่พบ Ollama — ตัวกินแรมเป็น process อื่น "
            "(ดู top_by_memory ใน snapshot) ไม่ใช่การโหลดโมเดล"
        )
    elif running:
        note = (
            f"Ollama ทำงานอยู่ ใช้ ~{mem_pct:.0f}% ({_fmt_bytes(rss)}) — "
            "ยังไม่กดดัน RAM/swap ถือว่าปลอดภัย"
        )
    else:
        note = "ไม่พบ process Ollama และ RAM/swap ปกติ"

    return {
        "ollama_running": running,
        "ollama_processes": procs,
        "ollama_rss": rss,
        "ollama_mem_percent": mem_pct,
        "memory_pressure": pressure,
        "note": note,
    }
