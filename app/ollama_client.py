"""ollama_client.py — สิ่งที่ทั้ง CLI (local_coder.py) และ server ใช้ร่วมกัน: URL ของ Ollama,
system prompt, ค่าจูน, และ call_ollama แบบไม่ stream.

แยกออกจาก local_coder.py เพื่อให้ server.py / model_backend / chat_hub ไม่ต้อง import
ทั้ง CLI (web_search, tavily_search, linear_connector, desktop_archive, folder_trust,
context_manager, cli_render ...) ตอนบูต — เปิดเร็วขึ้นบนเครื่อง HDD และไม่โหลด
config_manager/todo_store ซ้ำเป็นโมดูลชื่อ top-level อีกชุด. local_coder ยัง re-export
ชื่อเดิมทั้งหมด (from local_coder import call_ollama ใช้ได้เหมือนเดิม). stdlib ล้วน.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

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

ห้ามตอบแบบนี้ (ผิด) — โค้ดเปล่าใน code fence ไม่มี path + ไม่มี marker ระบบจะแกะไฟล์ไม่ได้:
```python
DEBUG = True
```
ต้องมี path บรรทัดแรก + <<<<<<< SEARCH / ======= / >>>>>>> REPLACE ครบทุกครั้งที่แก้ไฟล์
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

Do NOT answer like this (wrong) — bare code in a fence, no path + no markers, the system cannot apply it:
```python
DEBUG = True
```
Always include the path on the first line + <<<<<<< SEARCH / ======= / >>>>>>> REPLACE whenever you edit a file.
"""


def get_system_prompt(lang: str) -> str:
    return SYSTEM_PROMPT_EN if lang == "en" else SYSTEM_PROMPT_TH


def get_tuning_options(num_ctx: int) -> dict:
    """คำนวณ num_thread/keep_alive ตามสเปกเครื่อง (ไอเดียจาก HARNESS_ENGINEERING.md
    ที่เสนอมา — เก็บ 1 core ไว้ให้ OS ถ้ามีหลาย core, ปล่อย RAM คืนถ้าไม่ใช้เกิน 5 นาที)"""
    cpu_cores = os.cpu_count() or 2
    threads = max(1, cpu_cores - 1) if cpu_cores >= 4 else max(1, cpu_cores)
    return {"num_ctx": num_ctx, "num_thread": threads, "keep_alive": "5m"}


def call_ollama(model: str, messages: list, num_ctx: int = 8192,
                options: Optional[dict] = None) -> str:
    opts = get_tuning_options(num_ctx)
    if options:
        opts.update(options)  # เช่น {"temperature": 0} สำหรับ eval ให้ผลนิ่ง (reproducible)
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": opts,
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
