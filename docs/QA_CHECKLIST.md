# LCA v0.1.1 — QA Checklist

**ปรัชญา:** ตามที่ user สั่ง: **"PR เนี่ยคือ QA ด้วย"** — ก่อน merge ทุก PR ที่กระทบ installer ต้องรัน checklist นี้บน Windows จริง

**Scope:** manual QA ที่ cloud sandbox ทำเองไม่ได้ (Linux + proxy) — user รันบนเครื่อง

---

## 1. Automated gates (ผ่านแล้วใน CI/local)

- [x] `unittest discover` → 819 tests pass
- [x] `python scripts/qa.py` → 5/5 steps pass (syntax, imports, lint, test, smoke)
- [x] `build-exe` workflow build สำเร็จ (artifacts: `LCA-Desktop.exe`, `TokenLCAlimit.exe`)

## 2. Manual QA — Installation path (Windows)

### A. ตัว .exe (แนะนำที่สุด)

- [ ] ดาวน์โหลด `TokenLCAlimit.exe` จาก [Actions artifacts](https://github.com/Ragam111/9nammon/actions)
- [ ] ดับเบิลคลิก → GUI โผล่ ไม่มี error
- [ ] เลือกโฟลเดอร์ติดตั้ง (ลองทั้ง default และ custom)
- [ ] กด "ติดตั้ง" → แถบวิ่งจาก 2% → 100%
- [ ] เสร็จ → Close ได้ ไม่ค้าง
- [ ] Icon บน Desktop สร้าง (ถ้าเลือก checkbox)
- [ ] Icon ชี้ไปที่ `lca-tray.bat` (ถ้าเลือก "เริ่มใน system tray")

### B. ตัว LCA-Desktop.exe

- [ ] ดาวน์โหลด `LCA-Desktop.exe` จาก Actions artifacts
- [ ] ดับเบิลคลิก → หน้าต่างแชตเปิดใน Edge/Chrome `--app` mode
- [ ] ไม่มี address bar / tab (ดูเหมือน native app)
- [ ] พิมพ์ข้อความ → ตอบได้ (ต้องตั้ง connection ที่ `/console` ก่อน)
- [ ] ปิด → process จบสะอาด (ไม่มี zombie python.exe)

### C. ตัวติดตั้งแบบ zip (manual path)

- [ ] ดาวน์โหลด `main.zip` → extract → ดับเบิลคลิก `install.bat`
- [ ] เห็น **banner "มี .exe ไฟล์เดียวให้โหลดด้วยนะ"** ก่อนรัน
- [ ] ติดตั้งเสร็จ → เปิดโฟลเดอร์ให้
- [ ] ดับเบิลคลิก `start-lca.bat` → เบราว์เซอร์เด้งที่ `http://127.0.0.1:8420`

### D. one-liner PowerShell

- [ ] เปิด PowerShell → แปะคำสั่ง `iwr | iex`
- [ ] เห็น banner `.exe` ก่อน
- [ ] ติดตั้งเสร็จ ใช้งานได้

## 3. v0.1.1 bug fixes — regression test

### Bug 1: TEMP disk check
- [ ] ใน installer_gui.py GUI, เลือก install_dir บน drive ที่ว่าง
- [ ] ทำ TEMP ให้เต็ม (ลองใน VM: `fsutil file createnew C:\Users\...\Temp\big.dat 300000000`)
- [ ] กด "ติดตั้ง" → **ต้องเห็น error "พื้นที่ว่างไม่พอ ... ตึงที่ TEMP"** ชัดเจน
- [ ] ไม่ใช่พังกลางคัน (urlretrieve error)

### Bug 2: trailing slash on allowlist
- [ ] เปิด schedule gate (`SCHEDULE_ENABLED=true`, out-of-hours)
- [ ] จาก browser bookmark เข้า `/console/` (มี trailing slash)
- [ ] **ต้องเห็นหน้า console** ไม่ใช่ 503
- [ ] จาก curl: `curl http://127.0.0.1:8420/console/ -i` → 200 OK

## 4. Core features — smoke test (เร็ว)

- [ ] `/` → หน้าแชตโหลด
- [ ] `/console` → console โหลด
- [ ] `/install` → หน้า install ชี้ `.exe` card บนสุด (⭐)
- [ ] `/api/health` → 200 JSON
- [ ] `/api/status` → 200 JSON มี `state` + `message` ไทย
- [ ] ลองแชตข้อความ 1 ครั้ง → ตอบได้ (ต้องมี Ollama หรือ connection)

## 5. ใช้งานแบบ Claude Desktop ได้ไหม? (user asked)

- [ ] `lca-tray.bat` → icon ที่ system tray (ลูกศรบน taskbar)
- [ ] คลิกซ้าย icon → เปิดหน้าแชต (เหมือน Claude desktop)
- [ ] คลิกขวา icon → เมนู (เปิดแอป / เปิดคอนโซล / logs / ออก)
- [ ] กด "ออก" → tray clean exit (ไม่ค้างใน task manager)

## Sign-off

- [ ] คนทดสอบ: __________
- [ ] วันที่: __________
- [ ] Pass ทั้งหมด → merge PR / tag `v0.1.1`
- [ ] ถ้าเจอบั๊ก → **PR fix ใหม่** (user บอก: PR 1, PR 2, PR 3 ตามบั๊ก)

---

## วิธี trigger build-exe บน PR branch (เพื่อ QA)

ปกติ `build-exe` workflow trigger บน:
- `push: tags: ["v*"]` → แปะ Release
- `workflow_dispatch` → artifact

สำหรับ QA PR แบบที่ user สั่ง:
```bash
# จาก GitHub web UI: Actions → build-exe → Run workflow → เลือก branch
# หรือจาก gh CLI (ถ้า user มี):
gh workflow run build-exe.yml --ref claude/windows-package-architecture-j4znro
```

→ .exe artifacts ขึ้นใน run page ภายใน ~2 นาที → ดาวน์โหลดไป QA ตาม checklist ด้านบน
