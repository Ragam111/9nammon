"""watchdog.py — เฝ้าระบบ 24/7 (self-monitor) + เตือนเมื่อผิดปกติ

โจทย์: ระบบเปิดทิ้งไว้ตลอด ต้อง "รู้ตัว" เมื่อมีอะไรผิด (RAM ตึง / Ollama ล่ม / node หาย)
แล้วเตือนทันที ไม่ต้องรอคนมานั่งเฝ้า.

ปรัชญาความปลอดภัย (สำคัญ): watchdog นี้ *สังเกต + เตือน* เท่านั้น — ไม่เปลี่ยน state เอง
(ไม่ rollback/restart/kill อัตโนมัติ) เพราะการกระทำอัตโนมัติที่ผิดจังหวะอันตรายกว่าปัญหาเดิม.
คนเป็นผู้ตัดสินใจลงมือ (เช่น กด rollback เองจาก /dev). auto = เฝ้า+แจ้ง ไม่ใช่ auto-ซ่อม.

ออกแบบให้เทสง่าย:
  - evaluate(...)  : pure — รับสถานะ คืนรายการ finding (ไม่ยิงเน็ต ไม่ใช้เวลา)
  - Watchdog.tick(): 1 รอบ (เรียกเองในเทสได้) — เช็ก + เตือน (มี debounce กันสแปม)
  - Watchdog.start()/stop(): thread วน tick ทุก interval (ของจริงตอนรัน)

stdlib ล้วน (threading/time)
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

# ระดับความรุนแรง
CRITICAL = "critical"
WARNING = "warning"


def evaluate(ollama_up: bool, ram_pressure: bool, cluster_down: int = 0) -> list:
    """รับสถานะระบบ คืนรายการ finding = [{key, level, msg}] (ว่าง = ปกติ)"""
    findings = []
    if not ollama_up:
        findings.append({"key": "ollama", "level": CRITICAL,
                         "msg": "Ollama ล่ม — ตอบแชตไม่ได้ (ตรวจว่า `ollama serve` รันอยู่ไหม)"})
    if ram_pressure:
        findings.append({"key": "ram", "level": WARNING,
                         "msg": "RAM ตึง — เสี่ยง swap ลง HDD แล้วช้า/ค้าง (ปิดโปรแกรมที่ไม่ใช้)"})
    if cluster_down > 0:
        findings.append({"key": "cluster", "level": WARNING,
                         "msg": f"มี node ในคลัสเตอร์ล่ม {cluster_down} ตัว (ดู /dev cluster monitor)"})
    return findings


class Watchdog:
    """เฝ้าระบบเป็นระยะ: เรียก check_fn() → ได้ findings → เตือนผ่าน notify_fn (debounce)

    check_fn()  -> list[finding]   (ผู้เรียกประกอบเอง เช่น จาก resource_budget + evaluate)
    notify_fn(level, msg)          (เช่น ห่อ notifier.send); ไม่ส่งถ้า key เดิมเพิ่งเตือนไป
    """

    def __init__(self, check_fn: Callable[[], list], notify_fn: Callable[[str, str], None],
                 interval: float = 60.0, min_notify_gap: float = 300.0,
                 clock: Callable[[], float] = time.monotonic):
        self.check_fn = check_fn
        self.notify_fn = notify_fn
        self.interval = float(interval)
        self.min_notify_gap = float(min_notify_gap)
        self._clock = clock
        self._last_notify: dict = {}     # key -> เวลาเตือนล่าสุด
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_findings: list = []

    def tick(self) -> list:
        """เช็ก 1 รอบ — เตือนเฉพาะ finding ที่ยังไม่เตือน (หรือเกิน min_notify_gap). คืน findings"""
        findings = self.check_fn() or []
        self.last_findings = findings
        now = self._clock()
        for f in findings:
            key = f.get("key", "?")
            last = self._last_notify.get(key)
            if last is None or (now - last) >= self.min_notify_gap:
                try:
                    self.notify_fn(f.get("level", WARNING), f.get("msg", ""))
                except Exception:   # pragma: no cover - การเตือนล้มต้องไม่ล้ม watchdog
                    pass
                self._last_notify[key] = now
        return findings

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:       # pragma: no cover - รอบเดียวพังต้องไม่หยุดทั้ง watchdog
                pass
            self._stop.wait(self.interval)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="lca-watchdog")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def is_enabled(project_root) -> bool:
    """เปิด watchdog ไหม (config WATCHDOG_ENABLED = 1/true/yes) — ปิดเป็นค่าเริ่มต้น"""
    from app import config_manager
    val = str(config_manager.get_key(project_root, "WATCHDOG_ENABLED") or "").strip().lower()
    return val in ("1", "true", "yes", "on")
