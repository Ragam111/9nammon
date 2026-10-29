# LCA Bundling — ก้อนเดียวจริงกับก้อนเดียวแบบ installer

**ปรัชญา (ตามที่ user สั่ง):** "ลองทำให้ตัวโค้ดใน GitHub ดาวน์โหลดเป็นก้อนเดียวกัน เพื่อจะได้ไม่มีปัญหาในการติดตั้ง"

## 2 ชนิดของ .exe ที่สร้างออกมา

### 1. `LCA-Desktop.exe` (~10 MB) — **ก้อนเดียวจริง** ⭐ แนะนำที่สุด

**Build command** (`.github/workflows/build-exe.yml`):
```bash
pyinstaller --onefile --windowed --name LCA-Desktop \
    --add-data "app;app" \
    --add-data "sysmanager;sysmanager" \
    --add-data "local_coder.py;." \
    lca_app.py
```

**ที่ฝังมาด้วย:**
- ✅ Python runtime (ผ่าน pyinstaller bootloader)
- ✅ `app/` ทั้งโฟลเดอร์ (store modules, html files, agent code)
- ✅ `sysmanager/` (system detection code)
- ✅ `local_coder.py` (CLI entry point)
- ✅ `server.py` (จาก `lca_app.py` import)

**External deps:**
- Ollama (ถ้าใช้ local mode)
- OR API key ที่ `/console` (cloud mode — ไม่ต้องมี Ollama เลย)

**ข้อมูลเก็บที่:** `%LOCALAPPDATA%\LocalCodeAssistant\data` (bind `127.0.0.1`)

**วิธีใช้:**
1. ดาวน์โหลด `LCA-Desktop.exe`
2. ดับเบิลคลิก → หน้าต่างแอปเปิด (Edge/Chrome `--app` mode)
3. ตั้ง connection ที่ `/console` → แชตได้

### 2. `TokenLCAlimit.exe` (~12 MB) — ตัวติดตั้ง GUI (installer)

**Build command:**
```bash
pyinstaller --onefile --windowed --name TokenLCAlimit installer_gui.py
```

**ที่ฝังมาด้วย:**
- ✅ Python runtime
- ✅ tkinter GUI
- ✅ Logic ดาวน์โหลด + extract + copy ไฟล์

**ไม่ได้ฝัง:**
- ❌ `app/` — ดาวน์โหลดจาก GitHub ตอนรัน
- ❌ `server.py` — ดาวน์โหลดจาก GitHub ตอนรัน

**วิธีใช้:**
1. ดาวน์โหลด `TokenLCAlimit.exe`
2. ดับเบิลคลิก → GUI
3. เลือกโฟลเดอร์ติดตั้ง
4. **ดาวน์โหลด main.zip จาก GitHub** → extract → copy ไป install_dir
5. ต้องมี Python 3.10+ บนเครื่อง (ตัว installer ไม่ฝัง Python ของ server)

## เทียบตรงๆ

| จุด | LCA-Desktop.exe | TokenLCAlimit.exe |
|-----|-----------------|-------------------|
| **ก้อนเดียวจริง?** | ✅ ทุกอย่างใน .exe | ❌ ดาวน์โหลดเพิ่มตอนรัน |
| **ขนาด** | ~10 MB | ~12 MB (installer) + ~30 MB (ของจริงที่ถูก install) |
| **ต้องมี Python 3.10+?** | ❌ ไม่ต้อง (ฝังมาแล้ว) | ✅ ต้องมี |
| **ต้องมี Ollama?** | ⚠️ ขึ้นกับโหมด (local=ต้อง, cloud=ไม่ต้อง) | ⚠️ เหมือนกัน |
| **แชตได้ทันที?** | ✅ ดับเบิลคลิก → แชต | ❌ ต้องติดตั้งก่อน + รัน server ก่อน |
| **อัพเดต** | ดาวน์โหลด .exe ใหม่ | ดับเบิลคลิก installer ใหม่ |
| **ใช้ CLI (`lca`)?** | ❌ ไม่มี | ✅ มี (ติดตั้งแล้วมี `.bat`) |
| **ใช้ server แบบ cluster?** | ❌ รันคนเดียว | ✅ ตั้ง LAN mode ได้ |

## แนวทาง recommend

- **คนทั่วไป / คนที่อยากแชตเลย** → `LCA-Desktop.exe` (⭐)
- **devops / admin / รัน server สำหรับทีม** → `TokenLCAlimit.exe` (ติดตั้งแบบระบบ + CLI)

## แผนปรับปรุงต่อ (ไม่ใช่ v0.1.1)

### Option A: Portable mode (ไม่ติดตั้งเลย)
สร้าง `LCA-Portable.zip`:
```
LCA-Portable/
├── LCA-Desktop.exe
├── ollama.exe (บันเดิลมาด้วย ~400 MB!)
├── models/qwen2.5-coder-1.5b.gguf (optional ~1 GB)
└── README.txt
```
→ ก้อนเดียวแท้ ไม่พึ่งอะไรเลย แต่ขนาดใหญ่มาก (ollama + model ~1.4 GB)

**Pros:** ติดตั้งไม่ได้ก็ใช้ได้ (USB drive)
**Cons:** ขนาดใหญ่ · Ollama license + model distribution อาจมีข้อจำกัด

### Option B: Build cache in installer
ให้ `TokenLCAlimit.exe` เช็คว่ามี Python แล้วหรือยัง — ถ้าไม่มี → ดาวน์โหลด embeddable Python
แทนที่จะพึ่งพาระบบ

**Pros:** installer path ยัง work โดยไม่ต้องลง Python
**Cons:** ซับซ้อนขึ้น · ต้องจัดการ runtime version

### Option C (ปัจจุบัน — v0.1.1): แค่ promote LCA-Desktop.exe
- ทำให้ `LCA-Desktop.exe` ขึ้นก่อนในทุก landing (README, install.html)
- อธิบายว่ามันคือ "ก้อนเดียวจริง"
- เก็บ `TokenLCAlimit.exe` ไว้สำหรับ advanced use cases

→ **เลือก Option C** สำหรับ v0.1.1 — minimal change, maximum clarity

## สรุป (สำหรับ user)

- user ต้องการ "ก้อนเดียว" — **มีแล้ว** คือ `LCA-Desktop.exe`
- เราแก้ที่ **marketing/discoverability** ไม่ใช่ที่ build pipeline
- ของเดิมคือ `TokenLCAlimit.exe` ขึ้นก่อน → ทำให้คนสับสน
- v0.1.1 swap → `LCA-Desktop.exe` ขึ้นก่อน พร้อม badge "ก้อนเดียวจริง"
