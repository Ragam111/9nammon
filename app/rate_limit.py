"""
rate_limit.py — rate limiter แบบง่าย (in-memory, sliding window) สำหรับ server (stdlib)

ทำไมต้องมี (Item G): server เปิดออกนอก 127.0.0.1 ได้ (มี --host/--token) — ถ้าไม่มี
rate limit ใครยิง request ถล่มก็ทำให้เครื่อง 8GB ล่มได้ (โดยเฉพาะ /api/chat ที่เรียก
โมเดลหนัก). ตัวนี้จำกัดจำนวน request ต่อ client (ต่อ IP) ในกรอบเวลาหนึ่ง

หมายเหตุ: นี่คือ in-memory ต่อ process — พอสำหรับ single-process ThreadingHTTPServer
ของเรา ถ้าสเกลหลาย process/เครื่องต้องย้ายไป shared store (redis ฯลฯ) ภายหลัง

thread-safe: ThreadingHTTPServer เรียกจากหลาย thread จึงต้องมี lock
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """sliding-window limiter: อนุญาตไม่เกิน max_requests ครั้งในทุกช่วง window_seconds

    allow(client_id) -> bool : True ถ้ายังอยู่ในโควตา (และนับ request นี้แล้ว),
                               False ถ้าเกิน (ไม่ควรให้ผ่าน)
    max_requests <= 0 = ปิด rate limit (อนุญาตทุก request) — ใช้ตอน local/ทดสอบ
    """

    def __init__(self, max_requests: int, window_seconds: float = 60.0):
        self.max_requests = int(max_requests)
        self.window = float(window_seconds)
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client_id: str, now: float | None = None) -> bool:
        if self.max_requests <= 0:
            return True  # ปิดการจำกัด
        now = time.monotonic() if now is None else now
        cutoff = now - self.window
        with self._lock:
            q = self._hits[client_id]
            # ตัดรายการที่พ้นหน้าต่างเวลาออก (sliding window)
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.max_requests:
                return False
            q.append(now)
            return True

    def reset(self, client_id: str | None = None) -> None:
        """ล้างสถิติ (ทั้งหมดหรือเฉพาะ client) — มีไว้เผื่อ test/ดูแลระบบ"""
        with self._lock:
            if client_id is None:
                self._hits.clear()
            else:
                self._hits.pop(client_id, None)
