"""admission.py — "ยาม" คุมจำนวนงานหนักที่รันพร้อมกัน (admission control)

ปัญหาจริงบนเครื่องสเปกต่ำ (i3 2C/4T, RAM 8GB, HDD): ถ้าปล่อยให้ LLM generation
รันพร้อมกันหลายตัว → RAM ไม่พอ → OS swap ลง HDD (ช้ามาก) → ทั้งเครื่องค้าง
(อาการที่เจอจริง: เปิดแอปทิ้งไว้แล้วค้าง). compute ไม่ใช่ตัวปัญหา — การแย่ง RAM คือ

แก้แบบ HPC: *จับงานให้พอดีกับความสามารถเครื่อง* — คุมให้ generation รันพร้อมกัน
ได้ไม่เกิน N (netbook = 1), ที่เหลือเข้าคิวรอ; ถ้าคิวเต็มหรือรอนานเกิน → ปฏิเสธเร็ว
(ตอบ busy) ดีกว่าปล่อยกองจนเครื่องล่ม. นี่คือหลักเดียวกับ job scheduler ของ HPC

stdlib ล้วน (threading). ปรับ N ได้ด้วย config MAX_CONCURRENT_GENERATIONS
(default 1 — ปลอดภัยสุดสำหรับเครื่องบาง; เครื่องแรงตั้งเพิ่มได้)
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Optional

DEFAULT_MAX_CONCURRENT = 1      # netbook: รันทีละงาน (กัน RAM thrash)
DEFAULT_MAX_WAIT = 30.0         # วินาที — รอคิวนานกว่านี้ = ปฏิเสธ
DEFAULT_MAX_QUEUE = 8           # คนรอในคิวพร้อมกันได้สูงสุด (กันกองพะเนิน)


class Busy(Exception):
    """เครื่องเต็ม/คิวยาว — ผู้เรียกแปลงเป็น HTTP 503 (ลองใหม่ภายหลัง)"""


class AdmissionGate:
    """คุมจำนวนงานหนักที่รันพร้อมกัน ด้วย semaphore + คิวจำกัด

    ใช้ผ่าน context manager:
        with gate.slot():
            ... งานหนัก (generation) ...
    - ถ้ามีสล็อตว่าง → เข้าเลย
    - ถ้าเต็มแต่คิวยังไม่ล้น → รอ ไม่เกิน max_wait วินาที
    - ถ้าคิวล้น หรือ รอเกิน max_wait → raise Busy (ปฏิเสธเร็ว ไม่ปล่อยให้เครื่องล่ม)
    """

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT,
                 max_wait: float = DEFAULT_MAX_WAIT,
                 max_queue: int = DEFAULT_MAX_QUEUE):
        self.max_concurrent = max(1, int(max_concurrent))
        self.max_wait = float(max_wait)
        self.max_queue = max(0, int(max_queue))
        self._sem = threading.Semaphore(self.max_concurrent)
        self._lock = threading.Lock()
        self._waiting = 0        # จำนวนที่กำลังรอสล็อต (ไม่ใช่ที่กำลังรัน)

    def stats(self) -> dict:
        """สถานะปัจจุบัน — ไว้โชว์/ดีบัก (ค่าประมาณ ณ ขณะอ่าน)"""
        with self._lock:
            waiting = self._waiting
        return {"max_concurrent": self.max_concurrent, "waiting": waiting,
                "max_queue": self.max_queue}

    @contextmanager
    def slot(self):
        # กันคิวพะเนิน: ถ้าคนรออยู่แล้วเท่ากับเพดานคิว → ปฏิเสธทันที ไม่ต้องไปต่อแถว
        with self._lock:
            if self._waiting >= self.max_queue and self.max_queue > 0:
                raise Busy("เครื่องกำลังยุ่ง (คิวเต็ม) — ลองใหม่อีกครู่")
            self._waiting += 1
        try:
            got = self._sem.acquire(timeout=self.max_wait)
        finally:
            with self._lock:
                self._waiting -= 1
        if not got:
            raise Busy("เครื่องกำลังยุ่ง (รอคิวนานเกินไป) — ลองใหม่อีกครู่")
        try:
            yield
        finally:
            self._sem.release()


def gate_from_config(project_root, config_get=None) -> AdmissionGate:
    """สร้าง gate จาก config MAX_CONCURRENT_GENERATIONS (default 1 ถ้าไม่ตั้ง/ค่าพัง)
    config_get: ฟังก์ชัน (project_root, key)->str|None (ฉีดได้เพื่อเทส; default = config_manager)
    """
    if config_get is None:
        from app import config_manager
        config_get = config_manager.get_key
    raw = config_get(project_root, "MAX_CONCURRENT_GENERATIONS")
    n = DEFAULT_MAX_CONCURRENT
    if raw:
        try:
            n = max(1, int(str(raw).strip()))
        except (TypeError, ValueError):
            n = DEFAULT_MAX_CONCURRENT  # ค่าพัง → ปลอดภัยไว้ก่อน (1)
    return AdmissionGate(max_concurrent=n)
