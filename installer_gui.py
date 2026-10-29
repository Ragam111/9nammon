"""installer_gui.py — ตัวติดตั้ง LCA แบบ GUI ไฟล์เดียว (ดับเบิลคลิก → progress bar → Close)

ไอเดีย (ตามที่ user สั่ง): แพ็กไฟล์นี้เป็น TokenLCAlimit.exe ไฟล์เดียว
  ดับเบิลคลิก → GUI → เลือกโฟลเดอร์ติดตั้ง + จะสร้าง icon บน Desktop ไหม →
  กด "ติดตั้ง" → ดาวน์โหลด+แตก+คัดลอก (แถบวิ่งขึ้นจนเขียวเต็มหลอด) → กด Close พร้อมใช้งาน

stdlib ล้วน: tkinter (GUI), urllib (ดาวน์โหลด), zipfile, shutil, threading.
ดาวน์โหลดซอร์สล่าสุดจาก GitHub (main.zip) แล้วติดตั้งลงโฟลเดอร์ที่เลือก.

แพ็กเป็น .exe (บน Windows):
  pip install pyinstaller
  pyinstaller --onefile --windowed --name TokenLCAlimit installer_gui.py
  -> ได้ dist\TokenLCAlimit.exe (ไฟล์เดียว แจกได้เลย)
ดู docs/INSTALLER_EXE.md
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

ZIP_URL = "https://github.com/Ragam111/9nammon/archive/refs/heads/main.zip"
APP_NAME = "Local Code Assistant"
# ของที่ต้องคัดลอกจากซอร์สที่แตกออกมาไปยังโฟลเดอร์ติดตั้ง
COPY_DIRS = ("app", "sysmanager")
COPY_FILES = ("server.py", "local_coder.py", "lca.bat", "lca-web.bat", "start-lca.bat",
              "lca-desktop.bat", "lca-tray.bat", "lca-tray.ps1",
              "install.ps1", "requirements.txt", "README.md")


def default_install_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return str(Path(base) / "LocalCodeAssistant")


def _find_src_root(extract_dir: Path) -> Path:
    """GitHub zip แตกออกมาเป็นโฟลเดอร์ 9nammon-main/ — หาตัวที่มี server.py"""
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
    install_path = Path(install_dir)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zip_path = tmp / "lca.zip"
        progress_cb(10, "กำลังดาวน์โหลดจาก GitHub...")
        urllib.request.urlretrieve(ZIP_URL, zip_path)        # ดาวน์โหลด main.zip
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
