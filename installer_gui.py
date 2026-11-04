r"""installer_gui.py — ตัวติดตั้ง LCA แบบ GUI ไฟล์เดียว (ดับเบิลคลิก → progress bar → Close)

ไอเดีย (ตามที่ user สั่ง): แพ็กไฟล์นี้เป็น TokenLCAlimit.exe ไฟล์เดียว
  ดับเบิลคลิก → GUI → เลือกโฟลเดอร์ติดตั้ง + จะสร้าง icon บน Desktop ไหม →
  กด "ติดตั้ง" → ดาวน์โหลด+แตก+คัดลอก (แถบวิ่งขึ้นจนเขียวเต็มหลอด) → กด Close พร้อมใช้งาน

stdlib ล้วน: tkinter (GUI), urllib (ดาวน์โหลด), hashlib (SHA-256), zipfile, shutil, threading.
ดาวน์โหลดซอร์สที่ปัก commit ไว้จาก GitHub (ไม่ใช้ main.zip — URL แบบ latest ไม่มี hash คงที่)
แล้วตรวจ SHA-256 ก่อนแตกไฟล์.

แพ็กเป็น .exe (บน Windows):
  pip install pyinstaller
  pyinstaller --onefile --windowed --name TokenLCAlimit installer_gui.py
  -> ได้ dist\TokenLCAlimit.exe (ไฟล์เดียว แจกได้เลย)
ดู docs/INSTALLER_EXE.md
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

# แหล่งซอร์สที่ตัวติดตั้งดึงมา. refs/heads/main.zip เป็น URL แบบ "latest":
# ไบต์เปลี่ยนทุกครั้งที่ main ขยับ และ GitHub ไม่ได้เผยแพร่ไฟล์ .sha256 ของ source archive
# — จึงปัก commit แทนการเดา hash. ถ้าจะขยับพิน ต้องเปลี่ยน PINNED_COMMIT กับ ZIP_SHA256 คู่กัน
# หลังจากดาวน์โหลด URL ใหม่แล้วคำนวณเองเท่านั้น (ห้ามใส่ค่าที่ไม่ได้วัดจากไฟล์จริง).
#
# ZIP_SHA256 มาจากการดาวน์โหลด ZIP_URL จริงเมื่อ 2026-11-03 (curl สองครั้งได้ digest เดียวกัน
# d03326ba…ef8d, ขนาด 518881 ไบต์). ไม่ใช่ checksum ที่ upstream ประกาศ — GitHub ไม่มีให้.
PINNED_COMMIT = "93f1ca8de37543af528b33c8620347cf10865c5c"
ZIP_URL = f"https://github.com/Ragam111/9nammon/archive/{PINNED_COMMIT}.zip"
ZIP_SHA256 = "d03326baa16f1555b1d0089e46884a0f0ddf249e3b2b4976f77854313fe5ef8d"
_HASH_CHUNK = 64 * 1024
APP_NAME = "Local Code Assistant"
# ขนาดดิสก์ขั้นต่ำที่ต้องมีก่อนติดตั้ง (bytes) — zip ~2 MB + extracted ~30 MB + buffer
# ตั้ง 300 MB เผื่อ Python packages ตอนรัน + log + workspace ของ agent (user เจอ 118 errors
# ตอน extract บน Desktop ที่เต็ม — fail-fast ที่นี่แทนให้ user เจอกลางคัน)
MIN_FREE_DISK_BYTES = 300 * 1024 * 1024
# ของที่ต้องคัดลอกจากซอร์สที่แตกออกมาไปยังโฟลเดอร์ติดตั้ง
COPY_DIRS = ("app", "sysmanager")
COPY_FILES = ("server.py", "local_coder.py", "lca.bat", "start-lca.bat",
              "lca-desktop.bat", "lca-tray.bat", "lca-tray.ps1",
              "install.ps1", "requirements.txt", "README.md")


def default_install_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return str(Path(base) / "LocalCodeAssistant")


def _probe_free(path_str: str) -> int:
    """คืนพื้นที่ว่าง (bytes) ของดิสก์ที่ path นี้อยู่ — walk up หา parent ที่มีจริง"""
    p = Path(path_str).resolve()
    probe = p
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(str(probe)).free


def check_free_disk(install_dir: str, min_bytes: int = MIN_FREE_DISK_BYTES) -> tuple:
    """ตรวจพื้นที่ว่างของดิสก์ที่จะติดตั้ง + TEMP (ที่ download/extract) — คืน (ok, free_bytes, message)
    bug fix v0.1.1: ของเดิมเช็คแค่ install_dir ไม่ครอบ TEMP ที่ tempfile ใช้
    (ถ้า install=D: แต่ C: TEMP เต็ม → download ฟังก์ชัน urlretrieve พังตั้งแต่โหลด)"""
    import tempfile
    try:
        install_free = _probe_free(install_dir)
    except OSError as e:
        return False, 0, f"อ่านพื้นที่ว่าง install_dir ไม่ได้ ({e}) — ตรวจ path อีกครั้ง"
    try:
        temp_free = _probe_free(tempfile.gettempdir())
    except OSError:
        temp_free = install_free  # degrade: ถือว่า TEMP = install (same drive)
    # ตรวจทั้งคู่ — รายงาน disk ไหนแคบที่สุด
    tight = min(install_free, temp_free)
    if tight < min_bytes:
        need_mb = min_bytes // (1024 * 1024)
        install_mb = install_free // (1024 * 1024)
        temp_mb = temp_free // (1024 * 1024)
        tight_label = "install_dir" if install_free < temp_free else "TEMP"
        return False, tight, (
            f"พื้นที่ว่างไม่พอ: ต้องมี {need_mb} MB — install_dir {install_mb} MB, "
            f"TEMP {temp_mb} MB (ตึงที่ {tight_label}). "
            f"ลบไฟล์เก่า/ย้าย Downloads หรือเลือกไดร์ฟอื่น")
    return True, tight, ""


class ChecksumMismatch(RuntimeError):
    """SHA-256 ของไฟล์ที่ดาวน์โหลดไม่ตรงกับค่าที่ปักไว้ — ไฟล์ถูกลบแล้ว"""


def _discard(path: Path) -> None:
    """ลบไฟล์ที่โหลดค้างหรือตรวจไม่ผ่าน — เงียบถ้าไฟล์ไม่มีอยู่แล้ว"""
    try:
        path.unlink()
    except OSError:
        pass


def _normalize_sha256(expected_sha256: str) -> str:
    text = (expected_sha256 or "").strip().lower()
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ChecksumMismatch(
            "ค่า SHA-256 ที่ปักไว้ใช้ตรวจไม่ได้ "
            f"(ต้องเป็นตัวอักษร hex 64 ตัว): {expected_sha256!r}"
        )
    return text


def _require_digest(path: Path, digest: str, expected: str) -> str:
    """เทียบ digest ที่คำนวณแล้วกับค่าที่ปักไว้. ไม่ตรง → ลบไฟล์แล้วโยน ChecksumMismatch."""
    if digest != expected:
        _discard(path)
        raise ChecksumMismatch(
            "SHA-256 ไม่ตรง — ลบไฟล์ทิ้งแล้ว ไม่ติดตั้งต่อ\n"
            f"ไฟล์: {path}\n"
            f"ที่คาดไว้: {expected}\n"
            f"ที่ได้จริง: {digest}"
        )
    return digest


def verify_sha256(path: Path, expected_sha256: str, chunk_size: int = _HASH_CHUNK) -> str:
    """อ่าน `path` ทีละ chunk ผ่าน hashlib.sha256 แล้วเทียบกับค่าที่ปักไว้.

    ตรงกัน → คืน digest (hex ตัวเล็ก) และเก็บไฟล์ไว้.
    ไม่ตรง → ลบไฟล์ (รวมไฟล์ที่โหลดมาไม่ครบ) แล้วโยน ChecksumMismatch.
    ค่าที่ปักไว้ผิดรูปแบบ หรืออ่านไฟล์ไม่ได้ → โยน ChecksumMismatch โดยไม่ลบไฟล์.
    """
    expected = _normalize_sha256(expected_sha256)
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError as e:
        raise ChecksumMismatch(f"อ่านไฟล์เพื่อตรวจ SHA-256 ไม่ได้: {path} ({e})") from e
    return _require_digest(path, hasher.hexdigest(), expected)


def _stream_download(url: str, dest: Path, chunk_size: int = _HASH_CHUNK) -> str:
    """ดาวน์โหลด url → dest พร้อมอัปเดต SHA-256 ทุก chunk ที่อ่านจากเน็ต.

    พังกลางทาง → ลบไฟล์ที่เขียนค้าง แล้วโยน exception เดิม. คืน digest (ยังไม่เทียบพิน).
    """
    hasher = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, dest.open("wb") as out:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
                out.write(chunk)
    except Exception:
        _discard(dest)
        raise
    return hasher.hexdigest()


def _download_zip(url: str, dest: Path, expected_sha256: str = ZIP_SHA256) -> str:
    """ดาวน์โหลด zip แล้วตรวจ SHA-256 ก่อนคืน method ("urllib"/"curl").

    bug fix v0.1.2: user เจอ SSL cert verify failed บน Windows ที่ CA bundle ของ
    Python ไม่ update — จึงมี fallback:
    1. urllib (ตรวจ cert ครบ) — hashlib.sha256 ระหว่างสตรีม
    2. curl.exe (Windows 10+ มีมาเอง — ใช้ CA ของระบบ) แล้ว verify_sha256 อ่านไฟล์ทีละ chunk
    hash ไม่ตรงไม่ถือเป็นเหตุให้ลองช่องทางที่สอง: เนื้อหา URL เดียวกัน ลบไฟล์แล้วหยุด.
    ทั้งสองช่องทางล้มเรื่องเครือข่าย → RuntimeError + วิธีแก้ (certifi / ติดตั้ง Python ใหม่).
    """
    expected = _normalize_sha256(expected_sha256)
    try:
        digest = _stream_download(url, dest)
        _require_digest(dest, digest, expected)
        return "urllib"
    except ChecksumMismatch:
        raise
    except Exception as e:
        err_urllib = e
    # 2. curl.exe (Windows 10+) — สตรีมออกไฟล์แล้วค่อยตรวจด้วย verify_sha256
    # (curl อยู่นอกโปรเซส จึง hashing ทีละ chunk จากไฟล์ที่เซฟแล้ว ไม่ใช่จากซ็อกเก็ต)
    curl = shutil.which("curl") or (r"C:\Windows\System32\curl.exe"
                                    if sys.platform == "win32" else None)
    if curl and Path(curl).exists():
        try:
            res = subprocess.run(
                [curl, "-fsSL", "--output", str(dest), url],
                capture_output=True, timeout=120)
            if res.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                verify_sha256(dest, expected)
                return "curl"
        except ChecksumMismatch:
            raise
        except (OSError, subprocess.SubprocessError):
            pass
        _discard(dest)
    raise RuntimeError(
        f"ดาวน์โหลดไม่สำเร็จ: {err_urllib}\n\n"
        f"วิธีแก้: (1) ติดตั้ง Python ใหม่จาก python.org (จะได้ CA bundle ล่าสุด) "
        f"หรือ (2) รัน `pip install --upgrade certifi` ใน PowerShell")


def _find_src_root(extract_dir: Path) -> Path:
    """GitHub zip แตกออกมาเป็นโฟลเดอร์ 9nammon-<ref>/ — หาตัวที่มี server.py"""
    if (extract_dir / "server.py").exists():
        return extract_dir
    for child in extract_dir.iterdir():
        if child.is_dir() and (child / "server.py").exists():
            return child
    raise RuntimeError("ไม่พบ server.py ในไฟล์ที่ดาวน์โหลด")


def do_install(install_dir: str, make_desktop_icon: bool, progress_cb,
               use_tray: bool = False) -> None:
    """ติดตั้งจริง — เรียก progress_cb(percent, ข้อความ) ระหว่างทาง. โยน exception ถ้าพัง
    progress_cb: ฟังก์ชัน(int 0-100, str)
    use_tray=True → ไอคอน Desktop ชี้ไปที่ lca-tray.bat (รันเบื้องหลัง + system tray)"""
    # Pre-check: พื้นที่ดิสก์พอไหม — fail-fast กัน user เจอ error กลางคัน (118 errors
    # จาก WinRAR ตอน extract บน Desktop เต็ม)
    progress_cb(2, "ตรวจพื้นที่ดิสก์...")
    ok, _, msg = check_free_disk(install_dir)
    if not ok:
        raise RuntimeError(msg)
    install_path = Path(install_dir)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zip_path = tmp / "lca.zip"
        progress_cb(10, "กำลังดาวน์โหลดจาก GitHub...")
        # expected hash คือ ZIP_SHA256 (ค่า default) — ไม่ผ่านจะไม่แตกไฟล์
        method = _download_zip(ZIP_URL, zip_path)
        if method != "urllib":
            progress_cb(42, f"ดาวน์โหลดสำเร็จ (ผ่าน {method}) — กำลังแตกไฟล์...")
        progress_cb(45, "แตกไฟล์...")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        src = _find_src_root(tmp)
        progress_cb(65, "คัดลอกไฟล์โปรแกรม...")
        install_path.mkdir(parents=True, exist_ok=True)
        for d in COPY_DIRS:
            s = src / d
            if s.exists():
                shutil.copytree(s, install_path / d, dirs_exist_ok=True)
        for f in COPY_FILES:
            s = src / f
            if s.exists():
                shutil.copy2(s, install_path / f)
        progress_cb(85, "ตั้งค่า launcher...")
        _ensure_start_launcher(install_path)
        if make_desktop_icon:
            progress_cb(92, "สร้าง icon บน Desktop...")
            _make_desktop_icon(install_path, use_tray=use_tray)
    progress_cb(100, "ติดตั้งเสร็จแล้ว — กด Close ได้เลย")


def _ensure_start_launcher(install_path: Path) -> None:
    """ให้แน่ใจว่ามี start-lca.bat (ดับเบิลคลิกเปิด server + เด้งเบราว์เซอร์)"""
    p = install_path / "start-lca.bat"
    if p.exists():
        return
    p.write_text(
        '@echo off\r\nchcp 65001 >nul\r\ntitle Local Code Assistant\r\n'
        'start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8420/"\r\n'
        'python "%~dp0server.py" "%USERPROFILE%" --port 8420\r\npause\r\n',
        encoding="utf-8")


def _make_desktop_icon(install_path: Path, use_tray: bool = False) -> None:
    """สร้างทางลัดบน Desktop — ลำดับความต้องการ:
      use_tray=True + lca-tray.bat → รันเบื้องหลังใน system tray (ไม่มีหน้าต่างค้าง)
      else lca-desktop.bat → เปิดเป็นหน้าต่างแอป
      else start-lca.bat → เปิดเซิร์ฟเวอร์ + เบราว์เซอร์"""
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    if not desktop.exists():
        return
    if use_tray and (install_path / "lca-tray.bat").exists():
        target = install_path / "lca-tray.bat"
    elif (install_path / "lca-desktop.bat").exists():
        target = install_path / "lca-desktop.bat"
    else:
        target = install_path / "start-lca.bat"
    (desktop / "เปิด Local Code Assistant.bat").write_text(
        f'@echo off\r\ncall "{target}"\r\n', encoding="utf-8")


# ---------- GUI ----------

def launch_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title(f"ติดตั้ง {APP_NAME}")
    root.geometry("560x340")
    root.resizable(False, False)

    tk.Label(root, text=APP_NAME, font=("Segoe UI", 15, "bold")).pack(pady=(16, 2))
    tk.Label(root, text="ตัวติดตั้งอัตโนมัติ — เลือกที่ติดตั้งแล้วกดติดตั้ง").pack()

    frm = tk.Frame(root); frm.pack(fill="x", padx=20, pady=(14, 4))
    tk.Label(frm, text="ติดตั้งไปที่:").pack(anchor="w")
    row = tk.Frame(frm); row.pack(fill="x")
    dir_var = tk.StringVar(value=default_install_dir())
    tk.Entry(row, textvariable=dir_var).pack(side="left", fill="x", expand=True)
    def browse():
        d = filedialog.askdirectory(initialdir=dir_var.get() or str(Path.home()))
        if d:
            dir_var.set(str(Path(d) / "LocalCodeAssistant"))
    tk.Button(row, text="เลือก...", command=browse).pack(side="left", padx=(6, 0))

    icon_var = tk.BooleanVar(value=True)
    tk.Checkbutton(root, text="สร้าง icon บน Desktop", variable=icon_var).pack(anchor="w", padx=20)

    tray_var = tk.BooleanVar(value=True)
    tk.Checkbutton(root, text="เริ่มใน system tray (เบื้องหลัง — เหมือน Discord/Steam)",
                   variable=tray_var).pack(anchor="w", padx=20)

    bar = ttk.Progressbar(root, length=470, maximum=100)
    bar.pack(pady=(14, 2), padx=20)
    status = tk.Label(root, text="พร้อมติดตั้ง", fg="#555")
    status.pack()

    btns = tk.Frame(root); btns.pack(pady=12)
    install_btn = tk.Button(btns, text="ติดตั้ง", width=14, bg="#2563eb", fg="white",
                            font=("Segoe UI", 10, "bold"))
    install_btn.pack(side="left", padx=6)
    close_btn = tk.Button(btns, text="Close", width=10, command=root.destroy, state="disabled")
    close_btn.pack(side="left", padx=6)

    # แถบเขียวเมื่อเสร็จ
    style = ttk.Style(root)
    try: style.theme_use("default")
    except Exception: pass
    style.configure("green.Horizontal.TProgressbar", background="#22c55e")

    def set_progress(pct, msg):
        bar["value"] = pct
        status.config(text=msg)
        if pct >= 100:
            bar.config(style="green.Horizontal.TProgressbar")
            status.config(fg="#16a34a")
            close_btn.config(state="normal")
        root.update_idletasks()

    def run_install():
        install_btn.config(state="disabled")
        try:
            do_install(dir_var.get().strip() or default_install_dir(),
                       icon_var.get(), lambda p, m: root.after(0, set_progress, p, m),
                       use_tray=tray_var.get())
        except Exception as e:   # pragma: no cover - GUI path
            root.after(0, lambda: (status.config(text=f"ผิดพลาด: {e}", fg="#dc2626"),
                                   install_btn.config(state="normal")))

    install_btn.config(command=lambda: threading.Thread(target=run_install, daemon=True).start())
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
