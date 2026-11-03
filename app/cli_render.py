"""
cli_render.py — แสดงคำตอบแบบสตรีมใน terminal โดย "ไม่ดึงจอ" ตอนผู้ใช้เลื่อนขึ้นอ่าน

ปัญหาเดิม (local_coder.call_ollama_stream):
  - spinner เธรดแยก print "\\r(กำลังคิด...) |" + flush ทุก 0.15 วิ
  - print(content, flush=True) ทุก token (10-30 ครั้ง/วิ)
  ทุกครั้งที่เขียนลง console, conhost ของ Windows (หน้าต่าง cmd/PowerShell แบบเก่า)
  จะเลื่อน viewport กลับไปที่ cursor → ผู้ใช้เลื่อนขึ้นอ่านไม่ได้ จอเด้งกลับล่างตลอด

หลักการแก้ (stdlib ล้วน, Windows/macOS/Linux):
  - append-only: ไม่มี \\r วนซ้ำ, ไม่ clear screen, ไม่ขยับ cursor, ไม่ใช้ alt-screen
  - สถานะ "กำลังคิด..." เขียนครั้งเดียว แล้วลบครั้งเดียวตอน token แรกมา
  - throttle: รวม token แล้ว flush ไม่ถี่กว่า flush_interval (ค่าเริ่มต้น 0.25 วิ)
  - โหมด quiet: ไม่เขียนอะไรลงจอระหว่างโมเดลตอบเลย (แสดงความคืบหน้าที่ title bar
    แทน) แล้วพิมพ์คำตอบเต็มทีเดียวตอนจบ → เลื่อนอ่านของเก่าได้นิ่งสนิท
  - pager ในตัว (หน้าละจอ, Enter ต่อ / q ออก) สำหรับ /last
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from typing import Callable, Optional, TextIO

MODES = ("auto", "live", "quiet")

_THINKING = "(กำลังคิด... กด Ctrl+C เพื่อหยุด)"


def is_legacy_windows_console(env: Optional[dict] = None, os_name: Optional[str] = None) -> bool:
    """เดาว่ารันในหน้าต่าง conhost แบบเก่า (cmd/PowerShell ปกติบน Win10) หรือไม่.
    Windows Terminal ตั้ง WT_SESSION, VS Code/อื่นๆ ตั้ง TERM_PROGRAM, mintty/Git Bash ตั้ง TERM."""
    env = os.environ if env is None else env
    os_name = os.name if os_name is None else os_name
    if os_name != "nt":
        return False
    return not (env.get("WT_SESSION") or env.get("TERM_PROGRAM") or env.get("TERM"))


def resolve_mode(mode: Optional[str], env: Optional[dict] = None, os_name: Optional[str] = None) -> str:
    """auto → quiet บน conhost เก่า (ตัวที่ดึงจอทุกครั้งที่มี output), live ที่อื่น.
    อ่าน env LCA_STREAM_MODE ได้ถ้าไม่ได้ระบุ mode มา"""
    env = os.environ if env is None else env
    mode = (mode or env.get("LCA_STREAM_MODE") or "auto").strip().lower()
    if mode not in MODES:
        mode = "auto"
    if mode == "auto":
        return "quiet" if is_legacy_windows_console(env, os_name) else "live"
    return mode


def set_title(text: str, out: Optional[TextIO] = None) -> None:
    """ตั้งชื่อหน้าต่าง terminal — ใช้แสดงความคืบหน้าโดยไม่เขียนลง scrollback.
    Windows ใช้ SetConsoleTitleW (ไม่แตะ buffer = ไม่ดึงจอ); ที่อื่นใช้ OSC 0 เฉพาะเมื่อเป็น tty"""
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(str(text))  # type: ignore[attr-defined]
            return
        out = out or sys.stdout
        if out.isatty():
            out.write(f"\033]0;{text}\007")
            out.flush()
    except Exception:  # title เป็นของแถม ห้ามทำให้แชทพัง
        pass


class StreamRenderer:
    """รับ chunk จากโมเดลแล้วแสดงผลแบบไม่ดึงจอ.

    ใช้: r = StreamRenderer(mode="live"); r.start(); r.feed(chunk)...; text = r.finish()
    """

    def __init__(self, mode: str = "live", out: Optional[TextIO] = None,
                 flush_interval: float = 0.25, color: str = "", reset: str = "",
                 clock: Callable[[], float] = time.monotonic,
                 title: Callable[[str], None] = set_title):
        self.mode = mode if mode in ("live", "quiet") else "live"
        self.out = out or sys.stdout
        self.flush_interval = flush_interval
        self.color = color
        self.reset = reset
        self._clock = clock
        self._title = title
        self._parts: list[str] = []
        self._pending: list[str] = []
        self._status_shown = False
        self._started_output = False
        self._last_flush = 0.0
        self._last_title = 0.0
        self._chars = 0
        self.interrupted = False

    # ---- helpers ----
    def _isatty(self) -> bool:
        try:
            return bool(self.out.isatty())
        except Exception:
            return False

    def _write(self, s: str, flush: bool = True) -> None:
        self.out.write(s)
        if flush:
            self.out.flush()

    # ---- lifecycle ----
    def start(self) -> None:
        """เขียนสถานะ "กำลังคิด" ครั้งเดียว (ไม่มีแอนิเมชัน = ไม่มีการเขียนซ้ำทุก 0.15 วิ)"""
        self._last_flush = self._clock()
        if self.mode == "quiet":
            self._write(f"{_THINKING} — โหมดเงียบ: คำตอบจะขึ้นทีเดียวตอนเสร็จ เลื่อนอ่านได้ตามสบาย\n")
            self._title("LCA — กำลังตอบ...")
        elif self._isatty():
            self._write(_THINKING)
            self._status_shown = True

    def _clear_status_once(self) -> None:
        if self._status_shown:
            # ลบบรรทัดสถานะครั้งเดียว: \r + เว้นวรรคทับ + \r (ไม่ใช้ ANSI ขยับ cursor)
            width = len(_THINKING) + 2
            self._write("\r" + " " * width + "\r", flush=False)
            self._status_shown = False

    def feed(self, chunk: str) -> None:
        if not chunk:
            return
        self._parts.append(chunk)
        self._chars += len(chunk)
        now = self._clock()
        if self.mode == "quiet":
            if now - self._last_title >= 1.0:  # อัปเดต title ไม่เกินวินาทีละครั้ง
                self._title(f"LCA — กำลังตอบ... {self._chars:,} ตัวอักษร")
                self._last_title = now
            return
        if not self._started_output:
            self._clear_status_once()
            self._write(self.color, flush=False)
            self._started_output = True
        self._pending.append(chunk)
        if now - self._last_flush >= self.flush_interval:
            self._flush_pending(now)

    def _flush_pending(self, now: Optional[float] = None) -> None:
        if self._pending:
            self._write("".join(self._pending))
            self._pending.clear()
        self._last_flush = self._clock() if now is None else now

    def finish(self, interrupted: bool = False) -> str:
        """ปิดสตรีม: เทข้อความที่ค้าง/พิมพ์คำตอบเต็ม (quiet) แล้วคืนข้อความทั้งหมด"""
        self.interrupted = interrupted
        text = "".join(self._parts)
        note = "\n[หยุดแล้ว — คำตอบไม่ครบ แต่บันทึกส่วนที่ได้ไว้แล้ว]" if interrupted else ""
        if self.mode == "quiet":
            if text:
                self._write(f"{self.color}{text}{self.reset}{note}\n\n")
            elif note:
                self._write(note.lstrip("\n") + "\n")
            self._title("LCA — พร้อม")
        else:
            self._clear_status_once()
            self._flush_pending()
            if self._started_output:
                self._write(f"{self.reset}{note}\n\n")
            elif note:
                self._write(note.lstrip("\n") + "\n")
        return text


def page_text(text: str, out: Optional[TextIO] = None,
              read_key: Callable[[str], str] = input, rows: Optional[int] = None) -> None:
    """pager ในตัว (ไม่พึ่ง more/less ที่มีปัญหา encoding ไทยบน Windows):
    พิมพ์ทีละหน้าจอ แล้วรอ Enter = หน้าถัดไป, q = ออก. ระหว่างรอไม่มี output = จอนิ่ง"""
    out = out or sys.stdout
    if rows is None:
        rows = shutil.get_terminal_size(fallback=(80, 24)).lines
    page = max(5, rows - 2)
    lines = text.splitlines() or [""]
    for i in range(0, len(lines), page):
        out.write("\n".join(lines[i:i + page]) + "\n")
        out.flush()
        if i + page >= len(lines):
            break
        try:
            ans = read_key(f"-- {min(i + page, len(lines))}/{len(lines)} บรรทัด · Enter ต่อ · q ออก -- ")
        except (EOFError, KeyboardInterrupt):
            out.write("\n")
            break
        if ans.strip().lower() == "q":
            break
