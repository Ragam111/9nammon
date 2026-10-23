"""mem_hierarchy.py — วัด "การเดินทางของข้อมูลจริง" ข้ามชั้นหน่วยความจำของเครื่อง

แก่นที่พิสูจน์มาทั้ง session: บนเครื่องสเปกต่ำ คอขวดคือ *การขนส่งข้อมูล* (data movement)
ไม่ใช่ compute. GPU K600 แพ้ CPU เพราะต้องวิ่งข้าม PCIe ด้วย VRAM 1GB ที่เล็กเกินไป —
ไม่ใช่เพราะ core ช้า. เครื่องมือนี้วัดแต่ละชั้นด้วยเลขจริง แล้วชี้ว่า "คอขวดอยู่ตรงไหน"

ลำดับชั้น (เร็ว→ช้า ตามทฤษฎี):
    CPU cache  >  RAM  >  VRAM ข้าม PCIe  >  SSD  >  HDD  >  Network

วัดได้ด้วย stdlib (ไม่เพิ่ม dependency):
    - RAM      : คัด bytearray ในหน่วยความจำ (memcpy) → GB/s
    - Disk     : เขียนไฟล์จริง + fsync (ไม่โกงด้วย cache) แล้วอ่านกลับ → MB/s
    - Network  : ส่งผ่าน socket loopback (127.0.0.1) → MB/s (เป็น "เพดานบน" ของ network
                 จริงที่ต้องข้ามสาย/Wi-Fi จะช้ากว่านี้)

VRAM/PCIe วัดตรงๆ ด้วย stdlib ไม่ได้ (ต้องมี CUDA/Vulkan toolkit) — วัดแยกผ่าน llama-cli
(ngl 0 vs 99) อย่างที่ทำไปแล้ว; ค่าที่วัดได้ใส่เป็น reference ผ่าน config ได้

ออกแบบให้ปลอดภัย: เขียนไฟล์ชั่วคราวใน dir ที่กำหนด แล้วลบทิ้งเสมอ (ไม่ทิ้งขยะ)
"""

from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

MB = 1024 * 1024
GB = 1024 * MB


def _now() -> float:
    # perf_counter: นาฬิกาความละเอียดสูง ไม่กระโดดเวลา NTP ปรับ (เหมาะวัด duration)
    return time.perf_counter()


def _mbps(nbytes: int, seconds: float) -> float:
    """throughput เป็น MB/s — seconds<=0 (เร็วจนวัดไม่ติด) คืน 0.0 กันหารศูนย์"""
    if seconds <= 0:
        return 0.0
    return (nbytes / MB) / seconds


def bench_ram(size_mb: int = 64, repeat: int = 3) -> float:
    """คัดลอกบล็อกใน RAM ซ้ำ ๆ (bytearray slice = memcpy) แล้ววัด bandwidth
    คืนค่า "ดีสุด" ของหลายรอบ (min เวลา) — ลด noise จาก OS scheduler สะดุด"""
    n = size_mb * MB
    src = bytearray(os.urandom(min(n, 4 * MB)))  # seed 4MB แล้วขยาย (ไม่ต้อง urandom ทั้งก้อน)
    src = (src * (n // len(src) + 1))[:n]
    dst = bytearray(n)
    best = float("inf")
    for _ in range(max(1, repeat)):
        t0 = _now()
        dst[:] = src                 # memcpy ทั้งบล็อก
        best = min(best, _now() - t0)
    return _mbps(n, best)


def bench_disk(target_dir, size_mb: int = 64) -> dict:
    """เขียนไฟล์จริงขนาด size_mb + fsync (บังคับลงดิสก์จริง ไม่ค้างใน cache) แล้วอ่านกลับ
    คืน {write_mbps, read_mbps} — ลบไฟล์ทิ้งเสมอแม้ error (ไม่ทิ้งขยะบนดิสก์ผู้ใช้)

    หมายเหตุ: read อาจได้ประโยชน์จาก OS page cache (เร็วเกินจริง) — การ drop cache ต้องสิทธิ์
    root/แพลตฟอร์มเฉพาะ จึงไม่ทำ; ตัวเลข write (fsync แล้ว) คือค่าที่สะท้อนดิสก์จริงที่สุด"""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    n = size_mb * MB
    chunk = bytes(os.urandom(min(MB, n)))  # เขียนทีละ 1MB (ไม่ถือก้อนใหญ่ค้าง RAM)
    fd, path = tempfile.mkstemp(dir=str(target_dir), prefix=".memh_", suffix=".tmp")
    try:
        # ---- write + fsync ----
        t0 = _now()
        written = 0
        while written < n:
            w = os.write(fd, chunk if n - written >= len(chunk) else chunk[: n - written])
            written += w
        os.fsync(fd)             # รอจนข้อมูลถึงดิสก์จริง → เวลารวม disk latency จริง
        write_s = _now() - t0
        os.close(fd)
        fd = -1
        # ---- read ----
        t0 = _now()
        read_total = 0
        with open(path, "rb") as f:
            while True:
                b = f.read(MB)
                if not b:
                    break
                read_total += len(b)
        read_s = _now() - t0
        return {"write_mbps": _mbps(written, write_s), "read_mbps": _mbps(read_total, read_s)}
    finally:
        if fd != -1:
            os.close(fd)
        try:
            os.unlink(path)
        except OSError:
            pass


def bench_network_loopback(size_mb: int = 32) -> float:
    """ส่งข้อมูลผ่าน TCP socket บน 127.0.0.1 (loopback) แล้ววัด throughput ฝั่งรับ
    loopback ไม่ออกสายจริง = "เพดานบน" ของ network (จริงที่ข้าม Wi-Fi/สายจะช้ากว่า);
    ใช้เทียบลำดับชั้นให้เห็นว่า network stack เองก็มี overhead เทียบ RAM ตรง ๆ"""
    n = size_mb * MB
    payload = bytes(min(MB, n))
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host, port = srv.getsockname()
    received = {"n": 0, "secs": 0.0, "err": None}

    def _receiver():
        try:
            conn, _ = srv.accept()
            with conn:
                t0 = _now()
                got = 0
                while got < n:
                    b = conn.recv(256 * 1024)
                    if not b:
                        break
                    got += len(b)
                received["secs"] = _now() - t0
                received["n"] = got
        except OSError as e:  # pragma: no cover - loopback ไม่ควรล้ม แต่กันไว้
            received["err"] = e

    t = threading.Thread(target=_receiver, daemon=True)
    t.start()
    cli = socket.create_connection((host, port), timeout=10)
    try:
        sent = 0
        while sent < n:
            remain = n - sent
            cli.sendall(payload if remain >= len(payload) else payload[:remain])
            sent += min(len(payload), remain)
    finally:
        cli.close()
    t.join(timeout=10)
    srv.close()
    if received["err"] is not None:
        raise received["err"]
    return _mbps(received["n"], received["secs"])


def measure_all(target_dir: Optional[str] = None, size_mb: int = 64) -> dict:
    """วัดครบทุกชั้นที่ stdlib ทำได้ แล้วชี้คอขวด (ชั้นที่ throughput ต่ำสุด)
    คืน dict: ram_mbps, disk_write_mbps, disk_read_mbps, net_loopback_mbps, bottleneck

    target_dir: ที่เขียนไฟล์ทดสอบดิสก์ (default = cwd; อยากวัด HDD เทียบ SSD ส่ง path
    บนไดรฟ์นั้น ๆ มา เช่น "D:\\" บน Windows)"""
    target_dir = target_dir or os.getcwd()
    ram = bench_ram(size_mb)
    disk = bench_disk(target_dir, size_mb)
    net = bench_network_loopback(min(size_mb, 32))
    tiers = {
        "RAM (copy)": ram,
        "Disk write": disk["write_mbps"],
        "Disk read": disk["read_mbps"],
        "Network (loopback)": net,
    }
    # คอขวด = ชั้นที่ช้าสุด (ไม่นับ 0.0 ที่แปลว่าวัดไม่ติด/เร็วเกิน)
    real = {k: v for k, v in tiers.items() if v > 0}
    bottleneck = min(real, key=real.get) if real else None
    return {
        "ram_mbps": round(ram, 1),
        "disk_write_mbps": round(disk["write_mbps"], 1),
        "disk_read_mbps": round(disk["read_mbps"], 1),
        "net_loopback_mbps": round(net, 1),
        "bottleneck": bottleneck,
        "size_mb": size_mb,
    }


def format_report(result: dict) -> str:
    """ตารางอ่านง่าย: ชั้นไหนเร็ว/ช้า + ชี้คอขวด (ไว้ print จาก CLI หรือโชว์หน้า /dev)"""
    rows = [
        ("RAM (copy)", result["ram_mbps"]),
        ("Disk write (fsync)", result["disk_write_mbps"]),
        ("Disk read", result["disk_read_mbps"]),
        ("Network (loopback)", result["net_loopback_mbps"]),
    ]
    width = max(len(name) for name, _ in rows)
    lines = [f"วัดการเดินทางของข้อมูล (บล็อก {result['size_mb']}MB):", ""]
    for name, mbps in rows:
        bar = "#" * min(40, int(mbps / 50)) if mbps > 0 else ""
        tag = "  <= คอขวด" if name.startswith(result["bottleneck"] or "\0") else ""
        lines.append(f"  {name.ljust(width)} : {mbps:>9.1f} MB/s {bar}{tag}")
    lines.append("")
    lines.append(f"คอขวด: {result['bottleneck']} — ชั้นนี้ช้าสุด งานที่ติดชั้นนี้จะช้าตาม")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="วัดการเดินทางของข้อมูลข้ามชั้นหน่วยความจำ")
    p.add_argument("--dir", default=os.getcwd(),
                   help="ที่เขียนไฟล์ทดสอบดิสก์ (เช่น D:\\ เพื่อวัด HDD เทียบ C:\\ SSD)")
    p.add_argument("--size-mb", type=int, default=64, help="ขนาดบล็อกที่วัด (MB)")
    args = p.parse_args(argv)
    result = measure_all(args.dir, args.size_mb)
    print(format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
