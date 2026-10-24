"""worker.py — agent ทำงานเอง 24/7: ดึงงานจากคิว → รัน → วัดผล → วนไปเรื่อย

ภาพที่ user ต้องการ: agent ทำงานอัตโนมัติตลอด 24 ชม. ส่วนคน (พี่) ทำงานปกติบนเครื่องคู่กัน.
ตัวนี้คือ "คนงาน" ที่หยิบงานจากคิวมาทำทีละชิ้นด้วย agent loop (core.run) แล้วบันทึกสถิติ.

ปลอดภัย (สำคัญ): รันในโหมด sandbox อ่าน/ตรวจ (tools ปัจจุบันไม่มีเขียน/ลบ/เน็ต) — agent 24/7
จึง "วิเคราะห์/ตรวจ/สรุป" ได้เอง แต่ยังไม่แก้ไฟล์จนกว่าจะทำ P6 (approval gate). ปลอดภัยที่จะ
เปิดทิ้งไว้. ออกแบบเทสง่าย: claim_fn/done_fn ฉีดเข้ามา (ต่อคิวจริงหรือ mock ก็ได้), clock ฉีดได้.

ลำดับขั้น HPC: นี่คือ P4 (worker) — ขนานหลายตัวได้ด้วย admission gate; 24/7 ด้วย thread loop
แบบเดียวกับ watchdog. อนาคต (data center) = เพิ่มจำนวน worker/node ตามตัวเลขที่ stats วัดได้.

stdlib ล้วน (threading/time).
"""

from __future__ import annotations

import threading
import time

from app.agent import core, stats as stats_mod


def run_one(project_root, task: str, workspace, model: str = core.DEFAULT_MODEL,
            max_steps: int = core.DEFAULT_MAX_STEPS, clock=time.monotonic) -> dict:
    """รัน agent 1 งาน + วัดเวลา — คืน record {task, ok, final, steps, stopped_reason, duration_s}
    ไม่ raise: งานพัง (LLM ล่ม ฯลฯ) คืน ok=False พร้อม error (worker 24/7 ต้องไม่ตายเพราะงานเดียว)"""
    t0 = clock()
    try:
        res = core.run(project_root, task, workspace=workspace, model=model, max_steps=max_steps)
        ok = res.get("stopped_reason") == "final" and bool(res.get("final"))
        rec = {"task": task, "ok": ok, "final": res.get("final"),
               "steps": len(res.get("steps", [])), "stopped_reason": res.get("stopped_reason")}
    except Exception as e:   # กันทุกชนิด — worker ต้องอยู่ต่อ
        rec = {"task": task, "ok": False, "final": None, "steps": 0,
               "stopped_reason": "error", "error": f"{e.__class__.__name__}: {e}"}
    rec["duration_s"] = round(clock() - t0, 3)
    return rec


class Worker:
    """ดึงงานทีละชิ้นด้วย claim_fn() → รัน run_one → แจ้งผลด้วย done_fn(rec) + เก็บ stats

    claim_fn() -> {task, workspace} | None   (None = ไม่มีงาน รอรอบถัดไป)
    done_fn(rec)                              (เช่น อัปเดตคิว/แจ้งเตือน; optional)
    """

    def __init__(self, claim_fn, done_fn=None, project_root=".", model: str = core.DEFAULT_MODEL,
                 stats: "stats_mod.Stats | None" = None, interval: float = 5.0,
                 clock=time.monotonic):
        self.claim_fn = claim_fn
        self.done_fn = done_fn
        self.project_root = project_root
        self.model = model
        self.stats = stats or stats_mod.Stats()
        self.interval = float(interval)
        self._clock = clock
        self._stop = threading.Event()
        self._thread = None

    def tick(self) -> "dict | None":
        """ทำ 1 งานถ้ามี — คืน record หรือ None (ไม่มีงาน). เรียกเองในเทสได้"""
        job = self.claim_fn()
        if not job:
            return None
        rec = run_one(self.project_root, job.get("task", ""), job.get("workspace", "."),
                      model=self.model, clock=self._clock)
        self.stats.record(rec)
        if self.done_fn:
            try:
                self.done_fn(rec)
            except Exception:   # แจ้งผลล้มต้องไม่ล้ม worker
                pass
        return rec

    def _loop(self):
        while not self._stop.is_set():
            try:
                did = self.tick()
            except Exception:   # รอบเดียวพังต้องไม่หยุด worker 24/7
                did = None
            # มีงานก็รีบวนต่อ (ไม่รอ); ว่างค่อยพักตาม interval กัน busy-loop
            self._stop.wait(0 if did else self.interval)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="lca-agent-worker")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
