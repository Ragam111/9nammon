"""jobs.py — คิวงานของ agent (ให้ n8n / automation ภายนอกป้อนงานเข้ามาได้)

โจทย์ (ตามที่ user สั่ง): เอา n8n มาทำงานกับ agent — n8n เป็นตัว trigger/orchestrate ยิง
webhook มา enqueue งาน แล้ว worker 24/7 (worker.py) หยิบไปทำ, n8n เช็กผลกลับได้

ซื่อตรงเรื่องสเกล: n8n ไม่ได้ทำให้ LLM เร็วขึ้น — มันช่วย "ป้อน/กระจายงานอัตโนมัติ" เข้าคิว.
throughput จริง (เช่น 10,000 งาน/วัน) = จำนวน worker × node × (งาน/วันต่อ worker ที่ stats วัด).
คิวนี้คือจุดรวมงานให้หลาย worker ช่วยกันหยิบ (ยิ่งเพิ่มเครื่อง ยิ่งเสร็จเร็ว)

สถานะงาน: queued → running → done | error
stdlib ล้วน (json/threading/uuid). เก็บ agent_jobs.json (gitignored). ล็อกกันเขียนชนกัน.
สเกลเล็ก-กลางพอ; โตมากค่อยสลับเป็น SQLite ผ่าน interface เดิม (enqueue/claim/complete/get).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

STORE_FILE = "agent_jobs.json"
MAX_JOBS = 5000          # กันไฟล์บวม (เก่าสุดถูกตัดเมื่อเกิน)
QUEUED, RUNNING, DONE, ERROR = "queued", "running", "done", "error"

_lock = threading.Lock()


def _path(project_root) -> Path:
    return Path(project_root) / STORE_FILE


def _load(project_root) -> list:
    try:
        data = json.loads(_path(project_root).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(project_root, jobs: list) -> None:
    p = _path(project_root)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)   # atomic
    except OSError as e:
        print(f"[agent.jobs][error] เขียน {STORE_FILE} ไม่ได้: {e}")


def enqueue(project_root, task: str, workspace: str = ".", source: str = "api") -> dict:
    """เพิ่มงานเข้าคิว — คืน job {id, status:queued, ...}. task ว่าง → ValueError"""
    task = (task or "").strip()
    if not task:
        raise ValueError("ต้องระบุ task")
    job = {"id": "job-" + uuid.uuid4().hex[:12], "task": task, "workspace": workspace or ".",
           "source": source, "status": QUEUED, "created_at": time.time(),
           "result": None}
    with _lock:
        jobs = _load(project_root)
        jobs.append(job)
        if len(jobs) > MAX_JOBS:
            jobs = jobs[-MAX_JOBS:]
        _save(project_root, jobs)
    return job


def claim(project_root) -> "dict | None":
    """worker หยิบงาน queued ที่เก่าสุด → mark running (atomic). ไม่มี → None"""
    with _lock:
        jobs = _load(project_root)
        for j in jobs:
            if j.get("status") == QUEUED:
                j["status"] = RUNNING
                j["started_at"] = time.time()
                _save(project_root, jobs)
                return dict(j)
        return None


def complete(project_root, job_id: str, record: dict) -> bool:
    """บันทึกผลงาน (จาก worker.run_one) → done/error ตาม ok. คืน True ถ้าเจอ job"""
    status = DONE if record.get("ok") else ERROR
    with _lock:
        jobs = _load(project_root)
        for j in jobs:
            if j.get("id") == job_id:
                j["status"] = status
                j["finished_at"] = time.time()
                j["result"] = {"ok": record.get("ok"), "final": record.get("final"),
                               "steps": record.get("steps"), "duration_s": record.get("duration_s"),
                               "stopped_reason": record.get("stopped_reason"),
                               "error": record.get("error")}
                _save(project_root, jobs)
                return True
        return False


def get(project_root, job_id: str) -> "dict | None":
    with _lock:
        for j in _load(project_root):
            if j.get("id") == job_id:
                return dict(j)
    return None


def list_jobs(project_root, limit: int = 50) -> list:
    with _lock:
        jobs = _load(project_root)
    return jobs[-limit:][::-1]   # ใหม่สุดก่อน


def stats(project_root) -> dict:
    """นับงานตามสถานะ (สำหรับมอนิเตอร์/n8n) — queued/running/done/error"""
    with _lock:
        jobs = _load(project_root)
    out = {QUEUED: 0, RUNNING: 0, DONE: 0, ERROR: 0, "total": len(jobs)}
    for j in jobs:
        s = j.get("status")
        if s in out:
            out[s] += 1
    return out
