# Local Code Assistant — Report v0.0.1

วันที่: 2 สิงหาคม 2026
สถานะรวม: **Early-stage (0.0.1)** — ใช้งานได้จริงบน Linux/macOS, ยังต้องทดสอบบน Windows

## สรุปสั้น (ตามหลัก 9arm ข้อ 1 — ไม่แต่งเติม)

โปรเจกต์นี้คือ AI coding assistant ที่รันผ่าน Ollama (โมเดล local, ฟรี) แทน Claude
Code/API สำหรับงาน routine เพื่อประหยัดค่าใช้จ่าย ไม่ใช่สิ่งทดแทน Claude Code ได้
เต็มรูปแบบ — โมเดลขนาดเล็กที่รันได้บนเครื่องสเปกจำกัด (RAM 8GB) มีความแม่นยำต่ำกว่า
Claude อย่างมีนัยสำคัญ โดยเฉพาะงานที่ต้องใช้เหตุผลซับซ้อน

## ✅ ส่วนที่ทดสอบจริงแล้ว (รันได้จริง มีผลทดสอบยืนยัน)

| ฟีเจอร์ | แพลตฟอร์มที่ทดสอบ |
|---|---|
| Chat loop + diff engine (SEARCH/REPLACE) | Linux |
| Workflow 4 ขั้นตอน (Read→Re-check→Fix→Report) | Linux |
| กัน path traversal | Linux |
| `/add /files /undo /status /model /lang /reset` | Linux |
| ระบบ `/todo` (add/list/done/del) | Linux |
| Backend server (`server.py`) — GET/POST ครบ endpoint | Linux (mock Ollama) |
| `/websearch on|off` + fallback เมื่อไม่มี API key | Linux (mock Brave API) |
| Desktop archive sync (`/archive`) | Linux |
| **`install.sh`** (Linux/macOS installer) — ติดตั้งจริง เรียก `lca` ได้จริง | Linux |
| ตกแต่ง CLI (สี ANSI, banner) | Linux |

## ⚠️ ส่วนที่เขียนแล้วแต่ยังไม่ได้ทดสอบจริง

| ฟีเจอร์ | เหตุผลที่ยังไม่ทดสอบ |
|---|---|
| `install.ps1` / `install.bat` (Windows) | แซนด์บ็อกซ์พัฒนาเป็น Linux ไม่มี PowerShell |
| `uninstall.ps1` / `update.ps1` | เหตุผลเดียวกัน |
| `installer.iss` (Inno Setup → setup.exe) | ต้องคอมไพล์บน Windows ด้วย Inno Setup Compiler เท่านั้น ไม่มีเครื่องมือนี้ในแซนด์บ็อกซ์ |
| `/linear sync` (เชื่อม Linear) | พักไว้ตามคำสั่งผู้ใช้ (ดู Rule ข้อ 16 ใน SKILL.md) — ทดสอบ fetch อย่างเดียวผ่านแล้วก่อนพัก |

## ❌ ส่วนที่ยังไม่ได้ทำเลย

- คำสั่งอัปเดตสถานะ Linear ticket กลับ (มีแต่ฟังก์ชัน guard รอ UI ยืนยัน)
- Auto-update จริง (ตอนนี้ต้องให้ผู้ใช้ดาวน์โหลดแพ็กเกจใหม่มาทับเองแล้วรัน
  `update.ps1`/สคริปต์เทียบเวอร์ชัน — ไม่ได้เช็คเวอร์ชันใหม่จากเน็ตอัตโนมัติ)
- ระบบโหลด archive เก่ากลับเข้า context ให้โมเดล "จำ" ข้ามเซสชันได้จริง
  (ตอนนี้แค่เขียน archive อย่างเดียว)

## โครงสร้างไฟล์ปัจจุบัน

```
windows-package/
├── local_coder.py          # CLI หลัก
├── server.py                # backend web server
├── lca.bat / lca-web.bat    # launcher แบบ static (ใช้กับ installer.iss)
├── install.ps1 / .bat       # ตัวติดตั้งแบบ script (Windows) — ยังไม่ทดสอบจริง
├── install.sh                # ตัวติดตั้งแบบ script (Linux/macOS) — ทดสอบจริงแล้ว
├── installer.iss             # Inno Setup script → คอมไพล์เป็น setup.exe (Windows เท่านั้น)
├── INFO_BEFORE.txt           # ข้อความแสดงก่อนติดตั้งใน GUI installer
├── uninstall.ps1 / update.ps1
├── README.md
├── REPORT.md                 # ไฟล์นี้
└── app/
    ├── index.html            # หน้าเว็บ Chat UI
    ├── todo_store.py
    ├── linear_connector.py   # พักไว้ (ยังไม่พัฒนาต่อ)
    ├── desktop_archive.py
    └── web_search.py
```

## ขั้นตอนถัดไปที่แนะนำ (ถ้าจะทำต่อ)

1. ทดสอบ `install.sh` บน macOS จริง (ทดสอบแค่ Linux ในแซนด์บ็อกซ์)
2. ทดสอบ `install.ps1`/`install.bat` บน Windows จริง แก้บั๊กที่เจอ
3. คอมไพล์ `installer.iss` บน Windows ด้วย Inno Setup Compiler ให้ได้ `setup.exe`
   จริง แล้วทดสอบติดตั้ง/ถอนการติดตั้งผ่าน GUI
4. ถ้าต้องการ auto-update จริง ต้องมี server กลาง (เช่น GitHub Releases) ให้เช็ค
   เวอร์ชันล่าสุด — ยังไม่ได้ออกแบบส่วนนี้
