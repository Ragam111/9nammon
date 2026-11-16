"""cluster_router.py — "สมองจัดคิวงาน" ของคลัสเตอร์ (HPC ขั้น 3)

ต่อจาก cluster_store (รวม health ของทุก node): เมื่อมีงานเข้ามา ควรส่งไป node ไหน?
หลัก HPC: จับงานให้ node ที่ "พร้อมที่สุด" — ไม่ส่งไป node ที่ล่มหรือตึงจน swap.

สัญญาณจาก /api/health ของแต่ละ node:
  - reachable      : ต่อติดไหม (cluster_store เติมให้)
  - health.ollama  : "up"/"down" — ตัว LLM พร้อมไหม
  - health.ram_pressure : RAM ตึงไหม (ถ้าตึง = ช้า/เสี่ยง swap)

กลยุทธ์:
  - prefer_free (default): เลือก node ที่ "ว่าง" (ram ไม่ตึง) ก่อน, วนเวียน (round-robin)
    ภายในกลุ่มที่ว่าง; ถ้าทุกตัวตึงค่อยเลือกเท่าที่มี
  - round_robin: วนทุก node ที่ใช้ได้เท่า ๆ กัน

ไม่มี node ใช้ได้ → คืน node=None = "ทำที่เครื่องนี้เอง" (degrade ไม่พัง)
เป็น pure function (ไม่ยิงเน็ตเอง — รับ health ที่ cluster_store ดึงมาแล้ว) → เทสง่าย
"""

from __future__ import annotations


def _node_ok(entry: dict) -> bool:
    """node นี้รับงานได้ไหม — ต่อติด + ollama ไม่ down"""
    if not entry.get("reachable"):
        return False
    health = entry.get("health") or {}
    return health.get("ollama") != "down"   # "up" หรือไม่รู้ = ถือว่าพอรับได้


def _node_busy(entry: dict) -> bool:
    """node นี้ตึงไหม (RAM pressure) — ตึง = เลี่ยงถ้ามีตัวว่างกว่า"""
    return bool((entry.get("health") or {}).get("ram_pressure"))


def pick_node(nodes: list, strategy: str = "prefer_free", rr_index: int = 0) -> dict:
    """เลือก node สำหรับ route งานใหม่
    - nodes: รายการ entry จาก cluster_store.cluster_health()['nodes']
    - rr_index: ตัวชี้ round-robin (ผู้เรียกเก็บไว้แล้วส่งกลับมาในรอบถัดไป)
    คืน {node, reason, rr_index(ถัดไป)} ; node=None = ไม่มีตัวใช้ได้ → ทำเองที่เครื่องนี้
    """
    usable = [n for n in nodes if _node_ok(n)]
    if not usable:
        return {"node": None, "reason": "ไม่มี node พร้อมใช้ — ทำที่เครื่องนี้เอง", "rr_index": rr_index}

    if strategy == "round_robin":
        pool = usable
        reason = "round-robin (ทุก node ที่ใช้ได้)"
    else:  # prefer_free (default)
        free = [n for n in usable if not _node_busy(n)]
        if free:
            pool = free
            reason = "เลือก node ที่ว่าง (RAM ไม่ตึง)"
        else:
            pool = usable
            reason = "ทุก node RAM ตึง — เลือกเท่าที่มี (round-robin)"

    idx = rr_index % len(pool)
    chosen = pool[idx]
    return {"node": chosen, "reason": reason, "rr_index": (rr_index + 1) % len(pool)}


def route_preview(cluster_health: dict, strategy: str = "prefer_free", rr_index: int = 0) -> dict:
    """ตัวช่วยสำหรับหน้า /dev: รับผล cluster_health ทั้งก้อน แล้วบอกว่าจะ route ไป node ไหน
    คืน {target, reason, candidates, rr_index} — target = ชื่อ/url ของ node (หรือ None = local)"""
    nodes = (cluster_health or {}).get("nodes", [])
    res = pick_node(nodes, strategy=strategy, rr_index=rr_index)
    node = res["node"]
    return {
        "target": None if node is None else {"name": node.get("name"), "url": node.get("url")},
        "reason": res["reason"],
        "candidates": sum(1 for n in nodes if _node_ok(n)),
        "rr_index": res["rr_index"],
    }
