"""stats.py — วัดผลงานของ agent (ซื่อตรง: วัดก่อนเชื่อ)

เก็บ record ต่องาน แล้วสรุปเป็นตัวเลขที่ตัดสินใจได้: ทำไปกี่งาน สำเร็จกี่ %, เฉลี่ยกี่วิ/กี่ step.
ตัวเลขพวกนี้คือสิ่งที่ docs/AGENT_TECH_PLAN.md P5 ต้องใช้ตอบว่า "ไต่ถึง 3,000 งาน/วันได้ไหม
ต้องกี่ node/cloud" — ต้องมาจากการวัดจริง ไม่ใช่เดา.

stdlib ล้วน, thread-safe (ล็อกตอนเขียน), เก็บในหน่วยความจำ (รอบรันปัจจุบัน) + option ลงไฟล์
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

MAX_RECENT = 500   # เก็บ record ล่าสุดในหน่วยความจำ (กันบวม)


class Stats:
    def __init__(self, path=None):
        self._lock = threading.Lock()
        self._recent: list = []
        self.path = Path(path) if path else None

    def record(self, rec: dict) -> None:
        """บันทึกผล 1 งาน: {task, ok, duration_s, steps, stopped_reason, ...}"""
        with self._lock:
            self._recent.append(rec)
            if len(self._recent) > MAX_RECENT:
                self._recent = self._recent[-MAX_RECENT:]
            if self.path is not None:
                try:
                    with self.path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                except OSError:
                    pass   # วัดผลล้มต้องไม่ล้มงานจริง

    def summary(self) -> dict:
        """สรุปตัวเลขตัดสินใจ: จำนวน, สำเร็จ %, เฉลี่ยเวลา/step, ประมาณ throughput/วัน"""
        with self._lock:
            recs = list(self._recent)
        n = len(recs)
        if n == 0:
            return {"count": 0, "ok": 0, "success_rate": 0.0,
                    "avg_duration_s": 0.0, "avg_steps": 0.0, "est_per_day": 0}
        ok = sum(1 for r in recs if r.get("ok"))
        durations = [float(r.get("duration_s", 0)) for r in recs]
        steps = [int(r.get("steps", 0)) for r in recs]
        avg_dur = sum(durations) / n
        # ประมาณ throughput/วัน ถ้ารันทีละงานต่อเนื่อง (ยังไม่นับขนาน — เป็นพื้นให้คูณ concurrency)
        est = int(86400 / avg_dur) if avg_dur > 0 else 0
        return {
            "count": n,
            "ok": ok,
            "success_rate": round(ok / n, 3),
            "avg_duration_s": round(avg_dur, 3),
            "avg_steps": round(sum(steps) / n, 2),
            "est_per_day": est,   # ต่อ 1 worker; คูณจำนวน worker/node ได้ค่าจริง
        }

    def recent(self, limit: int = 20) -> list:
        with self._lock:
            return list(self._recent[-limit:])
