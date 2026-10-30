r"""lca_app.py — LCA Desktop: แอปก้อนเดียว (bundle ด้วย pyinstaller) เปิดหน้าต่างแอป + เซิร์ฟเวอร์ในตัว

เป้าหมาย (ตามที่ user สั่ง): ให้เหมือน ChatGPT.exe / Claude.exe / Gemini desktop —
ดับเบิลคลิก .exe → เปิดหน้าต่างแอป → แชตได้เลย โดย:
  - เซิร์ฟเวอร์ LCA ฝังอยู่ในตัว (ไม่ต้องลง Python แยก — pyinstaller แพ็ก runtime มาด้วย)
  - bind 127.0.0.1 เท่านั้น (ข้อมูลไม่หลุดออกเครื่อง) — ข้อมูล/คีย์เก็บใต้
    %LOCALAPPDATA%\LocalCodeAssistant\data (อยู่ในเครื่อง ส่วนตัว)
  - สมอง 2 ทาง: (ก) ต่อ cloud (connection OpenAI-compatible + key) = เหมือน ChatGPT,
    (ข) GPU/CPU ส่วนตัวผ่าน Ollama = ข้อมูลไม่ออกเครื่องเลย (เลือกใน /console)

ซื่อตรง: โหมด cloud ไม่ต้องมี Ollama; โหมด local ต้องมี Ollama (ตัว .exe ไม่ได้ฝัง Ollama/โมเดล).
การรองรับ CPU onboard/GPU เก่า-ใหม่ เป็นเรื่องของ Ollama ไม่ใช่ตัวแอปนี้.

แพ็กเป็น .exe (บน Windows):
  pyinstaller --onefile --windowed --name LCA-Desktop ^
    --add-data "app;app" --add-data "sysmanager;sysmanager" --add-data "local_coder.py;." ^
    lca_app.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402  (ฝังมาด้วยตอน bundle)

DEFAULT_PORT = 8420


def data_dir() -> Path:
    """โฟลเดอร์ข้อมูลผู้ใช้ (local, ส่วนตัว) — config/stores/db อยู่ที่นี่ ไม่หลุดออกเครื่อง"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "LocalCodeAssistant" / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_server(root, preferred_port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
    """สร้าง HTTP server ที่พร้อม serve — คืน (httpd, port). หา port ว่างให้เองถ้าชน.
    แยกออกมาเป็นฟังก์ชันเพื่อเทสได้ (ไม่ต้องเปิดหน้าต่าง/วนลูปจริง)"""
    port = server.find_free_port(preferred_port, host=host)
    handler = server.make_handler(Path(root), None, bind_host=host)  # local = CEO, bind 127.0.0.1
    httpd = ThreadingHTTPServer((host, port), handler)
    return httpd, httpd.server_address[1]


def open_app_window(url: str) -> None:
    """เปิดเป็นหน้าต่างแอป (ไม่มี address bar) — Edge/Chrome --app; fallback เบราว์เซอร์ปกติ"""
    for exe in ("msedge", "chrome", "chromium"):
        try:
            subprocess.Popen([exe, f"--app={url}"])
            return
        except OSError:
            continue
    try:
        webbrowser.open(url)
    except Exception:   # pragma: no cover - เปิดเบราว์เซอร์ไม่ได้ก็ไม่ควร crash
        pass


def _is_first_run(root) -> bool:
    """v0.1.2+: first-run = ยังไม่มี connections.json หรือมีแต่ว่าง →
    เปิดหน้า /console ให้ตั้งสมองก่อน (เหมือน Claude Desktop ขอ API key ครั้งแรก)"""
    conn_file = Path(root) / "connections.json"
    if not conn_file.exists():
        return True
    try:
        import json
        data = json.loads(conn_file.read_text(encoding="utf-8"))
        records = data.get("records", []) if isinstance(data, dict) else data
        return not records
    except (OSError, ValueError):
        return True


def main() -> int:
    # Parse CLI: --version แสดงแล้วออก (ตรงกับ /api/version)
    parser = argparse.ArgumentParser(
        prog="LCA-Desktop",
        description="LCA Desktop — Local Code Assistant แอปก้อนเดียว")
    parser.add_argument(
        "--version", action="version",
        version=f"LCA Desktop {server.read_version()} (python "
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})",
        help="แสดงเวอร์ชันแล้วออก")
    parser.parse_args()

    root = data_dir()
    httpd, port = build_server(root)
    # LCA Chat first-run flow: ถ้ายังไม่มี connection → เปิดหน้า /console ก่อน
    # (user เห็นหน้าตั้งสมอง AI ทันที เหมือน Claude Desktop ถาม API key ครั้งแรก)
    path = "/console" if _is_first_run(root) else "/"
    url = f"http://127.0.0.1:{port}{path}"
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    print(f"[LCA Chat] กำลังทำงานที่ {url}  (ข้อมูลอยู่ที่ {root})")
    time.sleep(1)                    # ให้ server พร้อมก่อนเปิดหน้าต่าง
    open_app_window(url)
    try:
        while t.is_alive():
            t.join(timeout=3600)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
