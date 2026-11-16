"""
lan_discovery.py — LAN subnet scanner สำหรับ auto-discover LCA nodes

discover(base_ip, port, timeout) → list[dict]
  สแกน subnet เดียวกับ base_ip (เช่น 192.168.1.x) แล้วลอง GET /api/version
  ที่แต่ละ IP — node ที่ตอบกลับพร้อม {"version": "..."} = LCA node

get_local_ips() → list[str]
  รายการ IP ของเครื่องนี้ (กรอง loopback ออก)

สิ่งที่ทำได้จริง (ไม่ขายฝัน):
- สแกน /24 subnet (256 hosts) ด้วย thread pool — เร็วพอถ้า timeout เล็ก
- ใช้ urllib stdlib เท่านั้น (ไม่มี nmap, scapy, ไม่ต้องเป็น root)
- ไม่สแกน port อื่น — เช็คเฉพาะ /api/version บน port ที่กำหนด

ข้อจำกัด (พูดตรงๆ):
- หาก firewall บนเครื่องปลายทางบล็อก port นี้ → ไม่เจอ node
- ใช้เวลา: 256 hosts × timeout(s) / concurrency_threads
  ค่าเริ่มต้น: 256 × 0.5s / 50 threads ≈ 2.5s — รับได้สำหรับ LAN
- ไม่รองรับ /16 หรือใหญ่กว่า (จะช้าเกิน)

Security: ไม่ส่ง token ในการ scan — เช็คแค่ /api/version ที่ไม่ต้อง auth
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from urllib.error import URLError
from pathlib import Path

VERSION_PATH = "/api/version"
_MAX_SUBNET_SCAN = 256  # /24 เท่านั้น


def get_local_ips() -> list[str]:
    """รายการ IP ของเครื่องนี้ กรอง 127.x ออก"""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            if addr.startswith("127.") or addr == "::1":
                continue
            if ":" in addr:  # IPv6 — ข้ามไปก่อน
                continue
            if addr not in ips:
                ips.append(addr)
    except OSError:
        pass
    # fallback: ลองเชื่อม LAN gateway เพื่อดู interface IP
    if not ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if not ip.startswith("127."):
                    ips.append(ip)
        except OSError:
            pass
    return ips


def _probe(ip: str, port: int, timeout: float) -> dict | None:
    """ลอง GET /api/version ที่ ip:port
    คืน dict พร้อม ip+version ถ้าตอบ, None ถ้าไม่ตอบ/ไม่ใช่ LCA"""
    url = f"http://{ip}:{port}{VERSION_PATH}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LCA-discovery/1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read(4096).decode("utf-8", errors="replace"))
        if isinstance(data, dict) and "version" in data:
            return {"ip": ip, "port": port, "url": f"http://{ip}:{port}",
                    "version": data.get("version", "unknown"),
                    "latency_ms": None}
    except (URLError, OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def discover(base_ip: str | None = None,
             port: int = 8420,
             timeout: float = 0.5,
             max_threads: int = 50) -> dict:
    """สแกน /24 subnet แล้วคืน LCA nodes ที่พบ

    Args:
        base_ip     : IP ในซับเน็ตเดียวกัน (เช่น "192.168.1.5")
                      ถ้า None ใช้ IP แรกของเครื่องนี้
        port        : port LCA server (default 8420)
        timeout     : วินาทีรอต่อ node (default 0.5)
        max_threads : จำนวน thread พร้อมกัน (default 50 สำหรับ LAN)

    Returns:
        {
          "nodes": [{ip, port, url, version, latency_ms}],
          "scanned": int,
          "base_ip": str,
          "elapsed_s": float,
        }
    """
    if base_ip is None:
        local_ips = get_local_ips()
        base_ip = local_ips[0] if local_ips else "127.0.0.1"

    # คำนวณ subnet prefix (เอา 3 octets แรก)
    parts = base_ip.split(".")
    if len(parts) != 4:
        return {"nodes": [], "scanned": 0, "base_ip": base_ip, "elapsed_s": 0.0,
                "error": f"base_ip ไม่ถูกต้อง: {base_ip!r}"}
    prefix = ".".join(parts[:3])  # เช่น "192.168.1"

    candidates = [f"{prefix}.{i}" for i in range(1, _MAX_SUBNET_SCAN)]
    results: list[dict] = []
    lock = threading.Lock()
    t0 = time.monotonic()

    def _worker(ip: str) -> None:
        t_start = time.monotonic()
        node = _probe(ip, port, timeout)
        if node:
            node["latency_ms"] = round((time.monotonic() - t_start) * 1000, 1)
            with lock:
                results.append(node)

    threads: list[threading.Thread] = []
    sem = threading.Semaphore(max_threads)

    def _bounded_worker(ip: str) -> None:
        with sem:
            _worker(ip)

    for ip in candidates:
        t = threading.Thread(target=_bounded_worker, args=(ip,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=timeout + 1.0)

    results.sort(key=lambda x: [int(p) for p in x["ip"].split(".")])
    return {
        "nodes": results,
        "scanned": len(candidates),
        "base_ip": base_ip,
        "elapsed_s": round(time.monotonic() - t0, 2),
    }
