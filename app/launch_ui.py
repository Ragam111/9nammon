"""launch_ui.py — เปิดหน้า LCA ในเบราว์เซอร์ หรือเป็นหน้าต่างแอป (Edge/Chrome --app)

ใช้ร่วมกันโดย ``server.py --open browser|app`` (start-lca.bat / lca-desktop.bat)
และ ``lca_app.py``. เปิด *หลัง* เซิร์ฟเวอร์ bind พอร์ตแล้ว จึงไม่ต้องเดา
``timeout /t 3`` แบบเดิม (เครื่อง HDD ช้ากว่า 3 วิได้ → เบราว์เซอร์ขึ้นหน้า error)
และได้พอร์ตจริงเสมอแม้ 8420 ถูกใช้อยู่แล้วเซิร์ฟเวอร์ย้ายพอร์ต. stdlib ล้วน.
"""

from __future__ import annotations

import subprocess
import sys
import webbrowser

MODES = ("none", "browser", "app")


def open_app_window(url: str) -> None:
    """หน้าต่างแอป (ไม่มี address bar) — Edge/Chrome --app; ไม่มีก็เปิดเบราว์เซอร์ปกติ"""
    if sys.platform == "win32":
        # msedge/chrome มักไม่อยู่ใน PATH แต่ `start` หาเจอจาก App Paths ของ Windows
        for exe in ("msedge", "chrome"):
            try:
                res = subprocess.run(["cmd", "/c", "start", "", exe, f"--app={url}"],
                                     capture_output=True, timeout=10)
                if res.returncode == 0:
                    return
            except (OSError, subprocess.SubprocessError):
                continue
    else:
        for exe in ("msedge", "chrome", "chromium", "google-chrome"):
            try:
                subprocess.Popen([exe, f"--app={url}"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue
    open_browser(url)


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # pragma: no cover - เปิดไม่ได้ก็ไม่ควรล้มเซิร์ฟเวอร์
        pass


def open_ui(url: str, mode: str) -> None:
    if mode == "app":
        open_app_window(url)
    elif mode == "browser":
        open_browser(url)
