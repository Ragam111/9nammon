#!/usr/bin/env python3
"""
local_coder.py — AI Coding Assistant บน Terminal สไตล์ Aider
รันโมเดลผ่าน Ollama (ฟรี, local, ไม่มีค่า API)

การใช้งาน:
    python3 local_coder.py --model qwen2.5-coder:3b --lang th ./my_project

คำสั่งในโหมด chat:
    /add <path>     เพิ่มไฟล์เข้า context
    /files          แสดงไฟล์ที่อยู่ใน context
    /status         แสดงสถานะ token/context window ปัจจุบัน
    /model <name>   สลับโมเดล Ollama ระหว่างสนทนา (ต้อง pull ไว้ก่อน)
    /lang <th|en>   สลับภาษาที่โมเดลตอบระหว่างสนทนา
    /reset          รีเซ็ต context (ล้างประวัติสนทนา, เริ่มนับ token ใหม่)
    /undo           ย้อนกลับการแก้ไฟล์ล่าสุด
    /linear sync    ดึง issue ที่ assign ให้ตัวเองจาก Linear เข้า todo list
                    (ต้องตั้ง env var LINEAR_API_KEY ไว้ก่อน — อ่านอย่างเดียว
                    ไม่เขียนสถานะกลับ Linear อัตโนมัติ)
    /archive        แสดง path โฟลเดอร์เดสก์ท็อปที่ sync ข้อมูลไว้
    /websearch on|off   เปิด/ปิดการค้นหาเว็บจริงก่อนตอบ (switch 0/1 — ถ้ายังไม่มี
                    key จะถามให้ป้อนตรงๆ ครั้งแรกที่เปิด แทนต้องไป set env var เอง)
    /config set <KEY> <ค่า>   ตั้งค่า API key/config อื่นๆ แบบ hot-swap (ไม่ต้อง
                    restart โปรแกรม) เช่น /config set BRAVE_SEARCH_API_KEY xxxx
    /todo list      แสดงรายการ todo ทั้งหมด
    /todo add <ข้อความ>   เพิ่ม todo ใหม่
    /todo done <id>        ทำเครื่องหมายว่าเสร็จแล้ว/ยังไม่เสร็จ (toggle)
    /todo del <id>          ลบ todo
    /exit           ออกจากโปรแกรม
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "app"))
from todo_store import load_todos, add_todo, toggle_todo, delete_todo  # noqa: E402
from linear_connector import fetch_my_issues  # noqa: E402
from desktop_archive import sync_project, get_archive_root  # noqa: E402
import web_search  # noqa: E402
import tavily_search  # noqa: E402
from config_manager import get_key, set_key, prompt_for_key  # noqa: E402
from folder_trust import ensure_trusted  # noqa: E402
from context_manager import build_auto_context  # noqa: E402


# ============================================================
# ตกแต่ง CLI — เปิด ANSI escape บน Windows cmd.exe ให้แสดงสีได้
# (หลัก 9arm ข้อ 1 "ไม่แต่งเติม": banner ด้านล่างบอกแค่สิ่งที่ระบบทำได้จริง
#  ไม่อ้างว่า "เก่งเท่า Claude" หรือโอ้อวดความสามารถเกินจริง)
# ============================================================
if os.name == "nt":
    os.system("")
    # บังคับ stdout/stdin เป็น UTF-8 — PowerShell/CMD ใช้ codepage เก่า (874/1252) เป็นค่า
    # เริ่มต้น ทำให้ print() ภาษาไทยเพี้ยนตอนแสดงผลจริง แม้ไฟล์ .py จะเป็น UTF-8 ถูกต้องแล้ว
    # (คนละสาเหตุกับปัญหา BOM ใน .ps1 ที่แก้ไปแล้ว — นี่คือ runtime console encoding)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError) as e:
        print(f"[warn] ตั้ง UTF-8 console encoding ไม่สำเร็จ: {e} — ข้อความไทยอาจเพี้ยน "
              f"ลองรัน `chcp 65001` ก่อนเปิดโปรแกรมด้วยตัวเอง")


class Color:
    BOT = "\033[96m"      # ฟ้าอ่อน — ข้อความจากโมเดล
    USER = "\033[92m"     # เขียว — ข้อความผู้ใช้
    SYSTEM = "\033[90m"   # เทา — ข้อความระบบ/สถานะ
    WARN = "\033[93m"     # เหลือง — คำเตือน
    ERROR = "\033[91m"    # แดง — error
    ACCENT = "\033[95m"   # ม่วง — หัวข้อ/ไฮไลต์
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_banner(model: str, project_root: Path, lang: str):
    # ปรับความกว้าง banner ตามขนาด terminal จริง (กันข้อความล้น/สั้นเกินไป) —
    # จำกัดช่วง 50-90 กันกรณี terminal แคบมาก/กว้างมากผิดปกติ
    term_width = shutil.get_terminal_size(fallback=(80, 24)).columns
    box_width = max(50, min(term_width - 4, 90))
    title = f"Local Code Assistant v{__version__} — Ollama, รันในเครื่อง, ฟรี"
    title_display_len = sum(2 if ord(c) > 0x2E80 else 1 for c in title)  # ตัวอักษรไทย/CJK กว้างกว่า ASCII
    pad = max(0, box_width - title_display_len - 2)
    left_pad = pad // 2
    right_pad = pad - left_pad
    line = "─" * box_width
    print(f"{Color.ACCENT}{Color.BOLD}╭{line}╮{Color.RESET}")
    print(f"{Color.ACCENT}{Color.BOLD}│{' ' * left_pad}{title}{' ' * right_pad}│{Color.RESET}")
    print(f"{Color.ACCENT}{Color.BOLD}╰{line}╯{Color.RESET}")
    print(f"{Color.SYSTEM}โมเดล: {Color.RESET}{model}   "
          f"{Color.SYSTEM}ภาษา: {Color.RESET}{lang}   "
          f"{Color.SYSTEM}โปรเจกต์: {Color.RESET}{project_root}")
    print(f"{Color.SYSTEM}พิมพ์ /help ดูคำสั่งทั้งหมด, /add <path> เพิ่มไฟล์, /status ดู token, "
          f"/exit ออก{Color.RESET}\n")

__version__ = "0.0.2"  # early-stage — ยังไม่เคยทดสอบจริงบน Windows (ดู REPORT.md)

OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT_TH = """คุณเป็นผู้ช่วยเขียนโค้ด (coding assistant) ที่ทำงานบน terminal
ตอบเป็นภาษาไทยเสมอ ยกเว้นชื่อตัวแปร/ฟังก์ชัน/โค้ดที่ต้องเป็นภาษาอังกฤษตามธรรมชาติของภาษาโปรแกรม
เมื่อผู้ใช้ขอให้แก้ไฟล์ ให้ตอบเป็น SEARCH/REPLACE block เท่านั้น รูปแบบนี้:

path/to/file.ext
<<<<<<< SEARCH
โค้ดเดิม (ต้อง match เป๊ะกับไฟล์จริง รวม indentation)
=======
โค้ดใหม่
>>>>>>> REPLACE

กฎ:
- ถ้าเป็นไฟล์ใหม่ทั้งไฟล์ ให้ SEARCH block ว่างเปล่า
- แก้ได้หลาย block ในคำตอบเดียว ถ้าต้องแก้หลายจุด/หลายไฟล์
- ถ้าผู้ใช้แค่ถามคำถามทั่วไป (ไม่ได้ขอให้แก้โค้ด) ให้ตอบเป็นข้อความปกติได้เลย
  ไม่ต้องใช้ format ด้านบน
- เมื่อผู้ใช้ขอให้ "แก้" ไฟล์ ห้ามตอบเป็นข้อความอธิบายเฉยๆ ต้องมี SEARCH/REPLACE block เสมอ

ตัวอย่าง — ผู้ใช้บอก "ในไฟล์ config.py เปลี่ยน DEBUG จาก False เป็น True" ให้ตอบแบบนี้เป๊ะ:
config.py
<<<<<<< SEARCH
DEBUG = False
=======
DEBUG = True
>>>>>>> REPLACE
"""

SYSTEM_PROMPT_EN = """You are a coding assistant running in a terminal.
Always answer in English.
When the user asks you to edit a file, respond ONLY with SEARCH/REPLACE blocks in this format:

path/to/file.ext
<<<<<<< SEARCH
original code (must match the real file exactly, including indentation)
=======
new code
>>>>>>> REPLACE

Rules:
- For a brand new file, leave the SEARCH block empty.
- You may include multiple blocks in one answer if multiple spots/files need edits.
- If the user is just asking a general question (not requesting a code edit),
  answer in plain text — do not use the format above.
- When the user asks to EDIT a file, never answer with a plain explanation only —
  you must include a SEARCH/REPLACE block.

Example — user says "in config.py change DEBUG from False to True", answer exactly like this:
config.py
<<<<<<< SEARCH
DEBUG = False
=======
DEBUG = True
>>>>>>> REPLACE
"""


def get_system_prompt(lang: str) -> str:
    return SYSTEM_PROMPT_EN if lang == "en" else SYSTEM_PROMPT_TH

DIFF_BLOCK_RE = re.compile(
    r"([^\n]+)\n<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
    re.DOTALL,
)


def get_system_ram_gb() -> float:
    """ตรวจ RAM รวมของเครื่อง แบบ cross-platform (Windows/Linux/macOS)
    ต่างจากเอกสารต้นทางที่ใช้ ctypes.windll อย่างเดียว (crash บน Linux/Mac)
    ที่นี่แยกตาม platform.system() แล้ว fallback เป็น 8.0GB ถ้าตรวจไม่ได้เลย"""
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        elif system == "Darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) / (1024 ** 3)
        else:  # Linux
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / (1024 ** 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 8.0  # fallback ปลอดภัย ถ้าตรวจไม่ได้ให้ถือว่า RAM น้อย (เผื่อเหนียว ไม่ตั้งค่าเกินตัว)


def get_tuning_options(num_ctx: int) -> dict:
    """คำนวณ num_thread/keep_alive ตามสเปกเครื่อง (ไอเดียจาก HARNESS_ENGINEERING.md
    ที่เสนอมา — เก็บ 1 core ไว้ให้ OS ถ้ามีหลาย core, ปล่อย RAM คืนถ้าไม่ใช้เกิน 5 นาที)"""
    cpu_cores = os.cpu_count() or 2
    threads = max(1, cpu_cores - 1) if cpu_cores >= 4 else max(1, cpu_cores)
    return {"num_ctx": num_ctx, "num_thread": threads, "keep_alive": "5m"}


def call_ollama(model: str, messages: list, num_ctx: int = 8192) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": get_tuning_options(num_ctx),
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(f"[error] ต่อ Ollama ไม่ได้: {e}")
        print("ตรวจสอบว่ารัน `ollama serve` อยู่หรือยัง")
        sys.exit(1)

    try:
        data = json.loads(raw)
        return data["message"]["content"]
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[error] ตอบกลับจาก Ollama ผิดรูปแบบ: {e}")
        print(f"[debug] raw response (ตัดให้สั้น): {raw[:200]}")
        sys.exit(1)


def call_ollama_stream(model: str, messages: list, num_ctx: int = 8192) -> str:
    """เหมือน call_ollama() แต่ขอ response แบบ streaming (NDJSON ทีละบรรทัด) จาก Ollama
    แล้ว print แต่ละ chunk ทันทีที่ได้รับ (ลด latency ที่ผู้ใช้รู้สึกได้ — เห็นคำตอบ
    ทยอยขึ้นแทนรอทั้งก้อน) คืนค่าข้อความเต็มที่ประกอบจากทุก chunk เพื่อให้ apply_diff_blocks()
    เอาไปตรวจต่อได้เหมือนเดิม — แยกจาก call_ollama() เดิมโดยตั้งใจ เพราะ server.py ยัง import
    call_ollama() แบบ blocking อยู่ (HTTP response แบบ chunked ต้องออกแบบแยกต่างหาก ไม่ทำในรอบนี้)"""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": get_tuning_options(num_ctx),
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    full_text = []
    first_chunk = True

    # Spinner หมุนระหว่างรอ chunk แรกจาก Ollama (โมเดลอาจ "คิด" นานก่อนตอบตัวแรก) —
    # ใช้ ASCII ธรรมดา (ไม่ใช่ unicode braille) เพื่อความชัวร์เรื่อง encoding บน
    # terminal เก่า/codepage แปลกๆ, เธรดแยกกิน RAM ไม่กี่ KB ไม่กระทบข้อจำกัด RAM เครื่อง
    stop_spinner = threading.Event()

    def _spin():
        frames = "|/-\\"
        i = 0
        while not stop_spinner.is_set():
            print(f"\r{Color.SYSTEM}(กำลังคิด...) {frames[i % len(frames)]}{Color.RESET}", end="", flush=True)
            i += 1
            stop_spinner.wait(0.15)

    spinner_thread = threading.Thread(target=_spin, daemon=True)
    spinner_thread.start()

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    # บรรทัดเดียวพังไม่ควรทำให้ทั้งสตรีมล้ม ข้ามแล้วไปต่อ
                    continue
                content = chunk.get("message", {}).get("content", "")
                if content:
                    if first_chunk:
                        stop_spinner.set()
                        spinner_thread.join(timeout=1)
                        print("\r" + " " * 24 + "\r", end="")  # เคลียร์บรรทัด spinner ทิ้ง
                        print(f"{Color.BOT}", end="", flush=True)
                        first_chunk = False
                    print(content, end="", flush=True)
                    full_text.append(content)
                if chunk.get("done"):
                    break
    except urllib.error.URLError as e:
        stop_spinner.set()
        print(f"\n[error] ต่อ Ollama ไม่ได้: {e}")
        print("ตรวจสอบว่ารัน `ollama serve` อยู่หรือยัง")
        sys.exit(1)
    finally:
        stop_spinner.set()  # กันเธรดค้างถ้าเกิด exception อื่นก่อนถึง done

    if not first_chunk:
        print(f"{Color.RESET}\n")

    result = "".join(full_text)
    if not result.strip():
        print(f"{Color.WARN}[warn] โมเดลไม่ได้ตอบอะไรกลับมา (ลอง /status เช็ค context "
              f"หรือ /model เช็คว่า pull โมเดลไว้จริงหรือยัง){Color.RESET}")
    return result


SEARCH_PROVIDERS = {"brave": web_search, "tavily": tavily_search}
SEARCH_PROVIDER_KEY_NAME = {"brave": "BRAVE_SEARCH_API_KEY", "tavily": "TAVILY_API_KEY"}


def get_search_provider(project_root: Path):
    """คืน module ของ search provider ที่ตั้งค่าไว้ผ่าน /config set SEARCH_PROVIDER
    — ค่า default คือ 'brave' เสมอ (ไม่เปลี่ยนพฤติกรรมเดิมที่ทดสอบผ่านแล้ว ถ้าผู้ใช้
    ไม่ได้ตั้งค่าอะไรใหม่) ชื่อ provider ที่ไม่รู้จักจะ fallback เป็น brave พร้อมเตือน"""
    name = (get_key(project_root, "SEARCH_PROVIDER") or "brave").strip().lower()
    if name not in SEARCH_PROVIDERS:
        print(f"[websearch][warn] ไม่รู้จัก provider '{name}' — ใช้ brave แทน "
              f"(ตัวเลือกที่มี: {', '.join(SEARCH_PROVIDERS)})")
        name = "brave"
    return name, SEARCH_PROVIDERS[name]


EXTERNAL_PROJECT_KEYWORDS = ("linear", "jira", "ticket", "issue tracker", "ตั๋วงาน")
CODE_EDIT_KEYWORDS = (
    "แก้", "เพิ่มฟังก์ชัน", "แก้บั๊ก", "รีแฟกเตอร์", "สร้างไฟล์", "ลบฟังก์ชัน",
    "fix", "add function", "refactor", "implement", "bug", "create file",
)


def classify_input(text: str, has_files_in_context: bool) -> str:
    """Skill-mode อัตโนมัติ: จัดหมวดคำสั่งผู้ใช้คร่าวๆ ด้วย keyword heuristic
    คืนค่า: 'external_project' | 'code_edit' | 'general'
    (การจำแนกนี้เป็น heuristic ง่ายๆ ไม่ใช่ NLU เต็มรูปแบบ — ผิดพลาดได้บ้าง
    แต่ใช้เป็น "คำแนะนำเส้นทาง" ไม่ใช่ตัวบังคับ 100%)"""
    lower = text.lower()
    if any(kw in lower for kw in EXTERNAL_PROJECT_KEYWORDS):
        return "external_project"
    if has_files_in_context or any(kw in lower for kw in CODE_EDIT_KEYWORDS):
        return "code_edit"
    return "general"


def build_context(files: dict) -> str:
    parts = []
    for path, content in files.items():
        parts.append(f"### {path}\n```\n{content}\n```")
    return "\n\n".join(parts)


def rescan_project(project_root: Path, ignore_dirs=(".git", ".local_coder_backup", "__pycache__", "node_modules")) -> list:
    """ขั้นตอนที่ 2: Re-check Project — สแกนรายชื่อไฟล์ปัจจุบันในโปรเจกต์"""
    found = []
    for p in project_root.rglob("*"):
        if p.is_file() and not any(part in ignore_dirs for part in p.parts):
            found.append(str(p.relative_to(project_root)))
    return found


def write_report(project_root: Path, entries: list):
    """ขั้นตอนที่ 4: Write Report — บันทึกลง CHANGELOG_local.md แล้ว sync
    ไปโฟลเดอร์เดสก์ท็อปทันที (ตามที่ผู้ใช้ขอให้อัปเดตข้อมูลตลอดเวลา)"""
    changelog = project_root / "CHANGELOG_local.md"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"\n## {ts}\n"]
    for e in entries:
        lines.append(f"- **{e['file']}** — {e['status']}: {e['summary']}")
    with open(changelog, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[report] บันทึก log ลง {changelog.name} แล้ว")

    dest = sync_project(project_root)
    if dest:
        print(f"[archive] sync ไปเดสก์ท็อปแล้ว: {dest}")


def apply_diff_blocks(response: str, project_root: Path, files: dict) -> bool:
    blocks = DIFF_BLOCK_RE.findall(response)
    if not blocks:
        return False

    print("\n--- การแก้ไขที่เสนอ ---")
    for path_str, search, replace in blocks:
        path_str = path_str.strip()
        print(f"\n[ไฟล์] {path_str}")
        print(f"  - ลบ: {search[:80]!r}{'...' if len(search) > 80 else ''}")
        print(f"  + เพิ่ม: {replace[:80]!r}{'...' if len(replace) > 80 else ''}")

    confirm = input("\nใช้การแก้ไขนี้เลยไหม? (y/n): ").strip().lower()
    if confirm != "y":
        print("ยกเลิกแล้ว")
        return True

    # ขั้นตอนที่ 2: ตรวจสอบโปรเจกต์ซ้ำก่อน apply อะไรทั้งหมด
    project_files = rescan_project(project_root)
    print(f"[re-check] สแกนโปรเจกต์พบ {len(project_files)} ไฟล์")

    report_entries = []

    for path_str, search, replace in blocks:
        path_str = path_str.strip()
        target = (project_root / path_str).resolve()

        # กฎเข้มงวด: ห้ามให้โมเดลแก้ไฟล์นอก project_root แม้จะพยายามระบุ path
        # แบบ ../../ ก็ตาม — ตรวจสอบก่อนทำอะไรกับไฟล์ทุกครั้ง
        try:
            target.relative_to(project_root.resolve())
        except ValueError:
            print(f"[ปฏิเสธ] path '{path_str}' อยู่นอกโปรเจกต์ — ข้ามเพื่อความปลอดภัย")
            report_entries.append({
                "file": path_str, "status": "ปฏิเสธ",
                "summary": "path อยู่นอก project_root ต้องสงสัยว่าเป็น path traversal",
            })
            continue

        target.parent.mkdir(parents=True, exist_ok=True)

        # ขั้นตอนที่ 1: อ่านไฟล์ล่าสุดจากดิสก์เสมอ (ไม่ใช้ cache เก่า)
        try:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
        except OSError as e:
            print(f"[error] อ่านไฟล์ {path_str} ไม่ได้: {e}")
            report_entries.append({"file": path_str, "status": "ล้มเหลว", "summary": f"อ่านไฟล์ไม่ได้: {e}"})
            continue

        # backup ก่อนแก้ (สำหรับ /undo)
        backup_dir = project_root / ".local_coder_backup"
        backup_dir.mkdir(exist_ok=True)
        if target.exists():
            shutil.copy(target, backup_dir / target.name)

        # ขั้นตอนที่ 3: แก้ไข/apply
        if search.strip() == "":
            target.write_text(replace, encoding="utf-8")
            print(f"[สร้างไฟล์ใหม่] {path_str}")
            files[path_str] = replace
            report_entries.append({"file": path_str, "status": "สำเร็จ (สร้างใหม่)", "summary": "สร้างไฟล์ใหม่ทั้งไฟล์"})
        elif search not in current:
            print(f"[คำเตือน] หา SEARCH block ไม่เจอใน {path_str} — ข้ามไฟล์นี้")
            report_entries.append({"file": path_str, "status": "ล้มเหลว", "summary": "SEARCH block ไม่ match กับไฟล์จริง"})
            continue
        else:
            updated = current.replace(search, replace, 1)
            target.write_text(updated, encoding="utf-8")
            print(f"[แก้ไขแล้ว] {path_str}")
            files[path_str] = updated
            report_entries.append({"file": path_str, "status": "สำเร็จ", "summary": f"แทนที่ {len(search)} → {len(replace)} ตัวอักษร"})

    # ขั้นตอนที่ 4: เขียนรายงาน
    if report_entries:
        write_report(project_root, report_entries)

    return True


def undo_last(project_root: Path):
    backup_dir = project_root / ".local_coder_backup"
    if not backup_dir.exists() or not any(backup_dir.iterdir()):
        print("ไม่มีอะไรให้ undo")
        return
    for backup_file in backup_dir.iterdir():
        target = project_root / backup_file.name
        shutil.copy(backup_file, target)
        print(f"[undo] คืนค่า {backup_file.name}")


def estimate_tokens(history: list) -> int:
    """ประมาณจำนวน token คร่าวๆ จากความยาวข้อความ (ไม่แม่นยำ 100% แต่พอกะสถานะได้)
    กฎคร่าวๆ: ~4 ตัวอักษรภาษาอังกฤษ หรือ ~2 ตัวอักษรไทย ต่อ 1 token"""
    total_chars = sum(len(m["content"]) for m in history)
    return total_chars // 3  # ค่าเฉลี่ยคร่าวๆ ระหว่างไทย/อังกฤษ


def main():
    parser = argparse.ArgumentParser(description="Local AI coding assistant (Ollama)")
    parser.add_argument("project_dir", type=str, help="โฟลเดอร์โปรเจกต์")
    parser.add_argument("--model", type=str, default="qwen2.5-coder:3b")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--lang", type=str, choices=["th", "en"], default="th",
                         help="ภาษาที่โมเดลใช้ตอบ (ค่าเริ่มต้น: th)")
    args = parser.parse_args()

    project_root = Path(args.project_dir).resolve()
    if not project_root.exists():
        print(f"ไม่พบโฟลเดอร์: {project_root}")
        sys.exit(1)

    if not ensure_trusted(project_root):
        sys.exit(0)

    files = {}
    current_lang = args.lang
    web_search_enabled = False  # switch 0/1 ตามที่คุยกัน — ปิดเป็นค่าเริ่มต้น
    history = [{"role": "system", "content": get_system_prompt(current_lang)}]
    current_model = args.model  # เก็บเป็นตัวแปรแยกเพื่อให้ /model สลับได้ระหว่างรัน

    print_banner(current_model, project_root, current_lang)

    while True:
        try:
            user_input = input(f"{Color.USER}{Color.BOLD}> {Color.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nลาก่อน")
            break

        if not user_input:
            continue
        if user_input == "/exit":
            break
        if user_input == "/help":
            help_rows = [
                ("/add <path>", "เพิ่มไฟล์เข้า context ด้วยตนเอง"),
                ("/files", "แสดงไฟล์ทั้งหมดใน context (auto + manual)"),
                ("/status", "ดูจำนวน token โดยประมาณเทียบกับ num_ctx"),
                ("/model <name>", "สลับโมเดล Ollama (ต้อง pull ไว้ก่อน)"),
                ("/lang th|en", "สลับภาษาที่โมเดลตอบ"),
                ("/reset", "ล้างประวัติสนทนา เริ่มนับ token ใหม่"),
                ("/undo", "ย้อนกลับการแก้ไฟล์ล่าสุด"),
                ("/websearch on|off", "เปิด/ปิดการค้นเว็บจริงก่อนตอบ"),
                ("/config set <KEY> <ค่า>", "ตั้งค่า API key (Brave/Tavily)"),
                ("/todo list|add|done|del", "จัดการ todo list ของโปรเจกต์"),
                ("/archive", "ดู path ที่ข้อมูล sync ไปเก็บที่เดสก์ท็อป"),
                ("/linear sync", "ดึง issue จาก Linear (พักไว้ตาม Rule 16)"),
                ("/help", "แสดงข้อความนี้"),
                ("/exit", "ออกจากโปรแกรม"),
            ]
            col_width = max(len(cmd) for cmd, _ in help_rows) + 2
            print(f"\n{Color.ACCENT}{Color.BOLD}คำสั่งทั้งหมด:{Color.RESET}")
            for cmd, desc in help_rows:
                print(f"  {Color.BOT}{cmd.ljust(col_width)}{Color.RESET}{Color.SYSTEM}{desc}{Color.RESET}")
            print()
            continue
        if user_input == "/files":
            auto_files = build_auto_context(project_root, args.num_ctx, set(files.keys()))
            tagged = [f"[manual] {p}" for p in files.keys()] + [f"[auto] {p}" for p in auto_files.keys()]
            print("ไฟล์ใน context:", tagged or "(ไม่มี)")
            continue
        if user_input == "/undo":
            undo_last(project_root)
            continue
        if user_input == "/status":
            used = estimate_tokens(history)
            pct = used / args.num_ctx * 100 if args.num_ctx else 0
            print(f"[status] โมเดล: {current_model}")
            print(f"[status] Token ใช้ไปโดยประมาณ: ~{used:,} / {args.num_ctx:,} ({pct:.1f}%) ของ context window")
            print("[status] หมายเหตุ: Ollama local ไม่มีระบบเก็บเงินตาม token — นี่คือเพดานความจำของโมเดล ไม่ใช่โควตาเงิน")
            if pct > 80:
                print("[status] ⚠ context ใกล้เต็มแล้ว แนะนำพิมพ์ /reset เพื่อรีเซ็ตบทสนทนา")
            continue
        if user_input == "/reset":
            history = [{"role": "system", "content": get_system_prompt(current_lang)}]
            print("[reset] ล้างประวัติสนทนาแล้ว เริ่มนับ token ใหม่จากศูนย์ (ไฟล์ที่แก้ไปแล้วไม่ถูกกระทบ)")
            continue
        if user_input.startswith("/lang "):
            new_lang = user_input[len("/lang "):].strip().lower()
            if new_lang not in ("th", "en"):
                print("[lang][error] รองรับเฉพาะ th หรือ en")
                continue
            current_lang = new_lang
            history[0] = {"role": "system", "content": get_system_prompt(current_lang)}
            print(f"[lang] เปลี่ยนภาษาเป็น {current_lang} แล้ว (ไม่ล้างประวัติสนทนา)")
            continue
        if user_input.startswith("/model "):
            new_model = user_input[len("/model "):].strip()
            current_model = new_model
            print(f"[model] สลับไปใช้โมเดล: {current_model}")
            print("[model] หมายเหตุ: ต้อง `ollama pull` โมเดลนี้ไว้ก่อนแล้ว มิฉะนั้นจะเรียกไม่ได้")
            continue
        if user_input.startswith("/websearch "):
            choice = user_input[len("/websearch "):].strip().lower()
            if choice not in ("on", "off"):
                print("[websearch][error] ใช้ /websearch on หรือ /websearch off เท่านั้น")
                continue
            web_search_enabled = (choice == "on")
            status = "เปิด (1)" if web_search_enabled else "ปิด (0)"
            print(f"[websearch] {status}")
            if web_search_enabled:
                print("[websearch] หมายเหตุ: โมเดลไม่ได้ต่อเน็ตเอง — ระบบจะค้นหาแทนแล้วแปะผลลัพธ์"
                      " เข้า context ให้โมเดลอ่านก่อนตอบทุกครั้งที่เปิดโหมดนี้")
                # hot-swap config: ถ้ายังไม่มี key เลย (ทั้ง config.json และ env var)
                # ถามผู้ใช้ตรงๆ ใน CLI แทนที่จะบังคับให้ไป set env var เอง — ถาม key
                # ตาม provider ที่ตั้งไว้ (/config set SEARCH_PROVIDER brave|tavily, default brave)
                provider_name, _ = get_search_provider(project_root)
                key_name = SEARCH_PROVIDER_KEY_NAME[provider_name]
                print(f"[websearch] provider ปัจจุบัน: {provider_name}")
                if not get_key(project_root, key_name):
                    prompt_for_key(project_root, key_name)
            continue
        if user_input.startswith("/config set "):
            rest = user_input[len("/config set "):].strip()
            parts = rest.split(maxsplit=1)
            if len(parts) != 2:
                print("[config][error] ใช้: /config set <KEY_NAME> <ค่า>")
                continue
            key_name, value = parts
            set_key(project_root, key_name, value)
            print(f"[config] บันทึก {key_name} แล้ว (ใช้ได้ทันที ไม่ต้องรีสตาร์ท)")
            continue
        if user_input == "/archive":
            archive_root = get_archive_root()
            print(f"[archive] ข้อมูลทุกโปรเจกต์ถูก sync ไว้ที่: {archive_root}")
            print(f"[archive] ดูรายชื่อโปรเจกต์ทั้งหมดได้ที่ {archive_root / 'index.json'}")
            continue
        if user_input == "/linear sync":
            try:
                issues = fetch_my_issues()
            except RuntimeError as e:
                print(f"[linear][error] {e}")
                continue
            if not issues:
                print("[linear] ไม่มี issue ที่ assign ให้คุณตอนนี้")
                continue
            print(f"[linear] พบ {len(issues)} issue — เพิ่มเข้า todo list ให้แล้ว")
            for issue in issues:
                text = f"[{issue['identifier']}] {issue['title']} ({issue['state']['name']}) — {issue['url']}"
                add_todo(project_root, text)
                print(f"  + {text}")
            sync_project(project_root)
            continue
        if user_input == "/todo list":
            todos = load_todos(project_root)
            if not todos:
                print("[todo] ยังไม่มีรายการ")
            for t in todos:
                mark = "x" if t["done"] else " "
                print(f"[{mark}] #{t['id']} {t['text']}")
            continue
        if user_input.startswith("/todo add "):
            text = user_input[len("/todo add "):].strip()
            item = add_todo(project_root, text)
            print(f"[todo] เพิ่มแล้ว #{item['id']}: {item['text']}")
            sync_project(project_root)
            continue
        if user_input.startswith("/todo done "):
            try:
                tid = int(user_input[len("/todo done "):].strip())
            except ValueError:
                print("[todo][error] ต้องระบุ id เป็นตัวเลข")
                continue
            print(f"[todo] toggle สำเร็จ #{tid}" if toggle_todo(project_root, tid) else f"[todo] ไม่พบ #{tid}")
            sync_project(project_root)
            continue
        if user_input.startswith("/todo del "):
            try:
                tid = int(user_input[len("/todo del "):].strip())
            except ValueError:
                print("[todo][error] ต้องระบุ id เป็นตัวเลข")
                continue
            print(f"[todo] ลบแล้ว #{tid}" if delete_todo(project_root, tid) else f"[todo] ไม่พบ #{tid}")
            sync_project(project_root)
            continue
        if user_input.startswith("/add "):
            rel = user_input[len("/add "):].strip()
            target = project_root / rel
            if target.exists():
                files[rel] = target.read_text(encoding="utf-8")
                print(f"เพิ่ม {rel} เข้า context แล้ว")
            else:
                print(f"ไม่พบไฟล์ {rel}")
            continue

        # Catch-all: คำสั่งที่ขึ้นต้นด้วย "/" แต่ไม่ตรงกับ pattern ไหนข้างบนเลย
        # (เช่น พิมพ์ผิด "/todo ad", "/models", ลืมเว้นวรรค ฯลฯ) — ต้องหยุดที่นี่
        # แสดง error ให้ผู้ใช้เห็นชัดเจน ห้ามปล่อยให้หลุดไปเป็นข้อความแชทส่งเข้าโมเดล
        if user_input.startswith("/"):
            typed_cmd = user_input.split()[0]
            print(f"{Color.ERROR}[error] ไม่รู้จักคำสั่ง: {typed_cmd}{Color.RESET}")
            print(f"{Color.SYSTEM}[error] คำสั่งที่มี: /help /add /files /status /model /lang /reset /undo "
                  f"/linear sync /archive /websearch /config set /todo list|add|done|del /exit{Color.RESET}")
            print(f"{Color.SYSTEM}[error] เช็ค syntax เช่น /todo add <ข้อความ> ต้องมีเว้นวรรคตามหลังคำสั่งย่อย{Color.RESET}")
            continue

        # Skill-mode อัตโนมัติ: จัดหมวดคำสั่งก่อนตัดสินใจว่าจะเข้า flow ไหน
        category = classify_input(user_input, bool(files))
        if category == "external_project":
            print("[skill-mode] ดูเหมือนคำขอนี้เกี่ยวกับ project ภายนอก (เช่น Linear) "
                  "— ลองใช้ /linear sync ก่อนถ้าต้องการดึง ticket มาเป็น context")
        # หมวด code_edit / general ไม่ต้องแจ้งเตือนอะไรเพิ่ม ปล่อยให้ system prompt
        # ตัดสินใจ format คำตอบเอง (ตาม flow เดิม)

        # Auto-scan: สแกนใหม่ทุกครั้งก่อนส่งข้อความ (ตาม design doc เฟส 3) แต่ content
        # cache ไว้ด้วย mtime ใน context_manager.py กันอ่านไฟล์ซ้ำโดยไม่จำเป็น
        auto_files = build_auto_context(project_root, args.num_ctx, set(files.keys()))
        combined_files = {**auto_files, **files}  # manual ทับ auto เสมอถ้าชื่อซ้ำ (ปกติไม่ซ้ำเพราะกรองแล้ว)
        context_block = build_context(combined_files)

        # Switch 0/1: ถ้าเปิด websearch ให้ค้นหาจริงก่อน แล้วแปะผลลัพธ์เข้า context
        # (ใช้ provider ตามที่ตั้งค่าไว้ /config set SEARCH_PROVIDER brave|tavily, default brave)
        search_block = ""
        if web_search_enabled:
            provider_name, provider = get_search_provider(project_root)
            try:
                results = provider.search_web(user_input, project_root=project_root)
                search_block = "\n\n" + provider.format_results_for_context(results)
                print(f"[websearch:{provider_name}] ค้นเจอ {len(results)} ผลลัพธ์ — แนบเข้า context แล้ว")
            except RuntimeError as e:
                print(f"[websearch][error] {e}")
                print("[websearch] ตอบต่อโดยไม่มีข้อมูลจากเน็ต (fallback ไปโหมด LLM ล้วน)")

        user_msg = (
            f"บริบทไฟล์ปัจจุบัน:\n{context_block}{search_block}\n\nคำขอ: {user_input}"
            if combined_files or search_block
            else user_input
        )
        history.append({"role": "user", "content": user_msg})

        est_before = estimate_tokens(history)
        if est_before > args.num_ctx:
            print(f"[คำเตือน] Token โดยประมาณ (~{est_before:,}) เกิน num_ctx ({args.num_ctx:,}) แล้ว "
                  f"โมเดลอาจ \"ลืม\" ข้อความช่วงต้น แนะนำ /reset ก่อนคุยต่อ")

        response = call_ollama_stream(current_model, history, args.num_ctx)
        history.append({"role": "assistant", "content": response})

        # ไม่ต้อง print(response) ซ้ำ เพราะ call_ollama_stream() แสดงผลระหว่างสร้างคำตอบไปแล้ว
        apply_diff_blocks(response, project_root, files)


if __name__ == "__main__":
    main()
