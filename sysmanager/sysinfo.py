"""
sysinfo.py — ข้อมูลพื้นฐานของเครื่อง (CPU / RAM / Storage / GPU) แบบ static

ต่างจาก monitor/collector.py ที่วัด "ตอนนี้ใช้ไปเท่าไร" (rate/utilisation)
ไฟล์นี้ตอบ "เครื่องนี้มีอะไรบ้าง" — spec คงที่ ไว้โชว์ในระบบจัดการทรัพยากร /
dev view เพื่อให้รู้ว่ากำลังรันบน hardware แบบไหน (เช่น RAM 8GB + Intel iGPU)

ยึด convention เดิม: psutil สำหรับ CPU/RAM/disk (cross-platform), ส่วน GPU ไม่มี
ใน psutil จึง detect แบบ best-effort ผ่านคำสั่งของ OS — ถ้าไม่เจอคืน [] ไม่ crash

ความจริงที่ต้องรู้ (intellectual honesty): GPU detection เป็น best-effort และ
**ยังไม่ได้ทดสอบบน Windows จริง** (แซนด์บ็อกซ์เป็น Linux ไม่มี GPU) — ชื่อ GPU ที่ได้
ใช้บอก "มีการ์ดอะไร" ได้ แต่ไม่ได้แปลว่าใช้ compute/train ได้ (เช่น Intel HD 520
เป็น integrated graphics ไม่มี CUDA/ROCm — มอนิเตอร์ได้ แต่เทรนไม่ได้)
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import psutil
except ImportError as exc:  # pragma: no cover
    raise ImportError("psutil is required for sysinfo. Install: pip install psutil") from exc


@dataclass
class CpuInfo:
    model: str
    physical_cores: Optional[int]
    logical_cores: int
    max_freq_mhz: Optional[float]
    arch: str


@dataclass
class MemoryInfo:
    total: int
    total_human: str


@dataclass
class StorageInfo:
    mountpoint: str
    device: str
    fstype: str
    total: int
    total_human: str


@dataclass
class GpuInfo:
    name: str
    source: str          # วิธีที่ตรวจเจอ เช่น "lspci", "wmic"
    compute_capable: bool  # best-guess ว่าเป็น discrete/compute GPU ไหม (ไม่ใช่ iGPU)


@dataclass
class SystemInfo:
    hostname: str
    platform: str
    os: str
    python: str
    cpu: CpuInfo
    memory: MemoryInfo
    storage: list[StorageInfo] = field(default_factory=list)
    gpus: list[GpuInfo] = field(default_factory=list)
    gpu_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _human_bytes(n: float) -> str:
    step = 1024.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < step:
            return f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} PiB"


def _cpu_model() -> str:
    """ชื่อรุ่น CPU — platform.processor() มักว่างบน Linux จึงอ่าน /proc/cpuinfo สำรอง"""
    model = platform.processor()
    if model:
        return model
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.machine() or "unknown"


# คีย์เวิร์ดบ่งชี้ GPU แบบ integrated (ไม่ใช่ compute GPU) — ใช้เดา compute_capable
_IGPU_HINTS = ("intel", "uhd", "hd graphics", "iris", "radeon graphics", "vega 3", "vega 8")
# คีย์เวิร์ดบ่งชี้ discrete/compute GPU
_DGPU_HINTS = ("nvidia", "geforce", "rtx", "gtx", "tesla", "a100", "h100",
               "radeon rx", "radeon pro", "instinct", "mi250", "mi300", "quadro")


def _guess_compute_capable(name: str) -> bool:
    low = name.lower()
    if any(h in low for h in _DGPU_HINTS):
        return True
    if any(h in low for h in _IGPU_HINTS):
        return False
    return False  # ไม่รู้จัก → เดาแบบปลอดภัยว่าไม่ใช่ compute GPU


def _run(cmd: list[str], timeout: float = 4.0) -> str:
    """รันคำสั่ง OS อย่างปลอดภัย คืน stdout (ว่างถ้าล้มเหลว) — ไม่ให้ error ลาม"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_gpus() -> list[GpuInfo]:
    """best-effort GPU detection ข้าม OS — ไม่เจอคืน [] (ไม่เคย raise)"""
    system = platform.system()
    gpus: list[GpuInfo] = []

    if system == "Linux" and shutil.which("lspci"):
        for line in _run(["lspci"]).splitlines():
            low = line.lower()
            if any(k in low for k in (" vga ", "vga compatible", "3d controller", "display controller")):
                name = line.split(":", 2)[-1].strip() if ":" in line else line.strip()
                if name:
                    gpus.append(GpuInfo(name, "lspci", _guess_compute_capable(name)))

    elif system == "Windows":
        # PowerShell ก่อน (wmic ถูก deprecate), fallback wmic
        out = _run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | "
                    "Select-Object -ExpandProperty Name"])
        if not out and shutil.which("wmic"):
            out = _run(["wmic", "path", "win32_VideoController", "get", "name"])
            lines = out.splitlines()[1:]  # ตัดหัว "Name"
        else:
            lines = out.splitlines()
        for line in lines:
            name = line.strip()
            if name:
                gpus.append(GpuInfo(name, "windows", _guess_compute_capable(name)))

    elif system == "Darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"])
        for line in out.splitlines():
            s = line.strip()
            if s.lower().startswith("chipset model:"):
                name = s.split(":", 1)[1].strip()
                if name:
                    gpus.append(GpuInfo(name, "system_profiler", _guess_compute_capable(name)))

    return gpus


def get_system_info() -> SystemInfo:
    """รวบรวม spec เครื่องทั้งหมด (static) — ปลอดภัยเรียกจาก server/CLI"""
    vm = psutil.virtual_memory()
    cpu = CpuInfo(
        model=_cpu_model(),
        physical_cores=psutil.cpu_count(logical=False),
        logical_cores=psutil.cpu_count(logical=True) or 0,
        max_freq_mhz=_max_freq(),
        arch=platform.machine(),
    )
    storage: list[StorageInfo] = []
    seen: set[str] = set()
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen or "ro" in (part.opts or "").split(","):
            continue
        seen.add(part.mountpoint)
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        storage.append(StorageInfo(
            mountpoint=part.mountpoint, device=part.device, fstype=part.fstype,
            total=usage.total, total_human=_human_bytes(usage.total),
        ))

    gpus = detect_gpus()
    if not gpus:
        note = "ตรวจไม่พบ GPU (หรือ detect ไม่ได้บน OS นี้) — เป็น best-effort"
    elif not any(g.compute_capable for g in gpus):
        note = ("พบเฉพาะ integrated GPU — มอนิเตอร์/แสดงผลได้ แต่ใช้ train/vLLM ไม่ได้ "
                "(ไม่มี CUDA/ROCm)")
    else:
        note = "พบ discrete GPU ที่น่าจะรองรับ compute — ตรวจ driver/CUDA/ROCm อีกชั้นก่อนใช้จริง"

    return SystemInfo(
        hostname=platform.node(),
        platform=platform.platform(),
        os=platform.system(),
        python=platform.python_version(),
        cpu=cpu,
        memory=MemoryInfo(total=vm.total, total_human=_human_bytes(vm.total)),
        storage=storage,
        gpus=gpus,
        gpu_note=note,
    )


def _max_freq() -> Optional[float]:
    try:
        freq = psutil.cpu_freq()
        if freq is not None and freq.max:
            return round(freq.max, 0)
    except (NotImplementedError, OSError, AttributeError):
        pass
    return None
