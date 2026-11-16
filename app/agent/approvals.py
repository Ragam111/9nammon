"""approvals.py — ด่านอนุมัติก่อนทำสิ่งที่ย้อนไม่ได้ (P6)

โจทย์ (ตามที่ user ย้ำเรื่องกัน zero-day): ให้ agent "เสนอ" การเขียนไฟล์/รันคำสั่งที่ย้อนไม่ได้
แต่ **ไม่ลงมือจริงจนกว่าคนจะกดอนุมัติ** (CEO ที่ /dev). agent คิด+เสนอได้เอง 24/7 ปลอดภัย
เพราะของจริงไม่เปลี่ยนจนมีคนเห็นชอบ.

flow:
  agent เรียก tool propose_write_file(path, content) → approvals.request(...) → เก็บเป็น "pending"
  คน (CEO) ดูที่ /dev → กดอนุมัติ → approvals.decide(id, "approve") → ลงมือจริงใน sandbox → "done"
                         → กดปฏิเสธ → "rejected" (ไม่ทำอะไร)

เก็บ agent_approvals.json (gitignored, atomic, lock). stdlib ล้วน.
ความปลอดภัย: ตอนอนุมัติ ลงมือผ่าน Sandbox(workspace) เดิม → ยัง confine path เหมือนเดิม.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from app.agent import tools as tools_mod

STORE_FILE = "agent_approvals.json"
MAX_RECORDS = 2000
PENDING, APPROVED, REJECTED, FAILED = "pending", "approved", "rejected", "failed"
# ชนิดการกระทำที่ต้องอนุมัติ (ย้อนไม่ได้)
KIND_WRITE = "write_file"
KIND_COMMAND = "run_command"
VALID_KINDS = (KIND_WRITE, KIND_COMMAND)

_lock = threading.Lock()


def _path(project_root) -> Path:
    return Path(project_root) / STORE_FILE


def _load(project_root) -> list:
    try:
        data = json.loads(_path(project_root).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(project_root, recs: list) -> None:
    p = _path(project_root)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(recs, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError as e:
        print(f"[approvals][error] เขียน {STORE_FILE} ไม่ได้: {e}")


def request(project_root, kind: str, workspace: str, detail: dict, by: str = "agent") -> dict:
    """agent เสนอการกระทำที่ต้องอนุมัติ — คืน record (status=pending). kind ไม่รู้จัก → ValueError"""
    if kind not in VALID_KINDS:
        raise ValueError(f"ชนิดการอนุมัติไม่รู้จัก: {kind} (มี: {', '.join(VALID_KINDS)})")
    rec = {"id": "apr-" + uuid.uuid4().hex[:12], "kind": kind, "workspace": workspace or ".",
           "detail": detail or {}, "by": by, "status": PENDING, "created_at": time.time(),
           "result": None}
    with _lock:
        recs = _load(project_root)
        recs.append(rec)
        if len(recs) > MAX_RECORDS:
            recs = recs[-MAX_RECORDS:]
        _save(project_root, recs)
    return rec


def list_pending(project_root) -> list:
    with _lock:
        return [r for r in _load(project_root) if r.get("status") == PENDING]


def list_all(project_root, limit: int = 50) -> list:
    with _lock:
        return _load(project_root)[-limit:][::-1]


def get(project_root, approval_id: str):
    with _lock:
        for r in _load(project_root):
            if r.get("id") == approval_id:
                return dict(r)
    return None


def _execute(rec: dict) -> dict:
    """ลงมือจริงตาม kind ผ่าน Sandbox (confine path). คืน {ok, output|error}"""
    sb = tools_mod.Sandbox(rec.get("workspace", "."))
    d = rec.get("detail") or {}
    try:
        if rec["kind"] == KIND_WRITE:
            out = sb.write_file(d.get("path", ""), d.get("content", ""))
        elif rec["kind"] == KIND_COMMAND:
            out = sb.run_command(d.get("command", ""))
        else:
            return {"ok": False, "error": f"ชนิดไม่รองรับ: {rec['kind']}"}
        return {"ok": True, "output": out}
    except tools_mod.ToolError as e:
        return {"ok": False, "error": str(e)}


def decide(project_root, approval_id: str, decision: str, by: str = "human") -> dict:
    """คนตัดสิน: 'approve' → ลงมือจริง, 'reject' → ทิ้ง. คืน record ที่อัปเดต (หรือ error dict)"""
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise ValueError("decision ต้องเป็น 'approve' หรือ 'reject'")
    with _lock:
        recs = _load(project_root)
        target = next((r for r in recs if r.get("id") == approval_id), None)
        if target is None:
            return {"error": "ไม่พบคำขออนุมัตินี้"}
        if target.get("status") != PENDING:
            return {"error": f"คำขอนี้ตัดสินไปแล้ว ({target.get('status')})"}
        if decision == "reject":
            target["status"] = REJECTED
        else:
            res = _execute(target)                 # ลงมือจริงตอนอนุมัติเท่านั้น
            target["status"] = APPROVED if res["ok"] else FAILED
            target["result"] = res
        target["decided_by"] = by
        target["decided_at"] = time.time()
        _save(project_root, recs)
        return dict(target)


def stats(project_root) -> dict:
    with _lock:
        recs = _load(project_root)
    out = {PENDING: 0, APPROVED: 0, REJECTED: 0, FAILED: 0, "total": len(recs)}
    for r in recs:
        s = r.get("status")
        if s in out:
            out[s] += 1
    return out
