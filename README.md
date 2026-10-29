# Local Code Assistant (LCA) — Windows Package

**Version:** 0.1.0 (official release 2026-10-29) · 812 tests pass · [CHANGELOG](CHANGELOG.md)

ตัวติดตั้ง AI Coding Assistant แบบฟรี รันด้วย Ollama บนเครื่อง (Windows 10/11, AMD64)

## 📥 ดาวน์โหลด .exe ไฟล์เดียว (แนะนำที่สุด)

ไปที่ [**หน้า Releases**](https://github.com/Ragam111/9nammon/releases) → โหลด **`TokenLCAlimit.exe`** → ดับเบิลคลิก → GUI โผล่ → เลือกโฟลเดอร์ → กด "ติดตั้ง" → แถบวิ่งจนเขียวเต็ม → Close พร้อมใช้งาน

- ไฟล์เดียวประมาณ ~15 MB (รวม Python runtime + GUI)
- ติดตั้งเองลงใน `%LOCALAPPDATA%\LocalCodeAssistant` (ไม่ต้อง admin)
- **ตรวจพื้นที่ดิสก์อัตโนมัติก่อนติดตั้ง** (ต้องมี ≥ 300 MB) — ถ้าไม่พอ แสดง error ชัดเจน ไม่ต้องรอ error กลางคัน
- ต้องมี **Python 3.10+** และ **Ollama** บนเครื่อง (ตัว .exe เป็น installer ไม่ได้ฝัง runtime)

> ❗ **ถ้าดาวน์โหลด zip แล้วแตกไฟล์เอง** และเจอ **"Not enough space on the disk"** จาก WinRAR —
> ให้ลบไฟล์เก่าใน `Downloads`/`Desktop` ก่อน หรือใช้ `.exe` installer แทน (จัดการพื้นที่เองได้ดีกว่า)

## ⚡ ติดตั้งออนไลน์ บรรทัดเดียว (ถ้าไม่อยากโหลด .exe)

เปิด **PowerShell** แล้วแปะบรรทัดนี้ (ดาวน์โหลด + แตกไฟล์ + ติดตั้งให้อัตโนมัติ):

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://raw.githubusercontent.com/Ragam111/9nammon/main/install_online.ps1 | iex"
```

จากนั้นดึงโมเดล (ครั้งเดียว): `ollama pull qwen2.5-coder:1.5b` แล้วเปิดใช้งานได้เลย

## มีอะไรให้ใช้บ้าง
- **แชตช่วยเขียนโค้ด** — CLI (`lca`) หรือหน้าเว็บ Chat UI (`lca-web` → `http://127.0.0.1:8420`), ตอบแบบสตรีมทีละคำ
- **ผู้ใช้หลายคน + สิทธิ์ (RBAC)** — ลูกน้อง login ได้, แอดมินเข้าผ่าน "รหัสไททัน" (master token) = CEO
- **พื้นที่ส่วนตัว/บริษัท (spaces)** — แยกข้อมูลต่อคน/ทีม ไม่ปนกัน
- **คลัสเตอร์หลายเครื่อง** — รวม health ที่เดียว + ส่งงานไปทำที่เครื่องที่พร้อม (cluster forward)
- **AI agent สายเทค (สภาที่ปรึกษา)** — `python -m app.agent council "โจทย์"` หลายมุม (ceo/elon/jobs/…) แล้วสังเคราะห์
- **เฝ้าระบบ 24/7 + rollback config** — เตือนเมื่อผิดปกติ, ย้อนเวอร์ชันได้เมื่อ incident
- **เสียบ cloud GPU ได้** — สลับ backend เป็น OpenAI-compatible endpoint จากหน้า `/dev`
- **Console ต่อสมอง AI ภายนอก (`/console`)** — ต่อ OpenAI-compatible (TokenMe/vLLM/cloud) หรือ Ollama หลายตัว → ทำ **Skills** (prompt สำเร็จรูป) → เปิดเป็น **Bots** ให้ n8n ยิง `POST /api/bots/run` (ดู `docs/CONSOLE_PLATFORM.md`)
- **System tray installer** — ติดตั้งปุ๊บแล้วอยู่ใน tray เหมือน Discord/Steam (ดู `docs/TRAY_INSTALLER.md`)
- **เวลาเปิด-ปิดเซิร์ฟเวอร์** (schedule gate) — ปิด server นอกเวลาทำการเพื่อประหยัดค่า cloud/ไฟ, แจ้งลูกค้าผ่าน `GET /api/status`

> **เวอร์ชันล่าสุด:** ดู `CHANGELOG.md` (อัพเดตทุก PR cycle)

> เอกสารเพิ่มเติม: `docs/CLUSTER_FORWARD.md`, `docs/AGENT_TECH_PLAN.md`, `docs/learn/` (ความรู้พื้นฐาน)
>
> **อยากเปิดให้คนอื่นเข้าผ่านเน็ต (โดเมน + server ฟรี)?** ทำตามทีละขั้นที่ `docs/GO_ONLINE_FREE.md`
>
> **อยากเข้าใจทั้งระบบแบบคอร์ส (ไฟล์ไหนทำอะไร, frontend↔backend, สร้างใหม่ทีละขั้น)?** อ่าน `docs/APP_WALKTHROUGH.md`

## แอปเดสก์ท็อป `LCA-Desktop.exe` (เหมือน ChatGPT/Claude/Gemini desktop)

ดับเบิลคลิก **`LCA-Desktop.exe`** → เปิดหน้าต่างแอป → แชตได้เลย (ฝัง Python+server มาในตัว ไม่ต้องลง Python)
- **โหมด cloud**: ตั้ง connection + API key ที่ `/console` → แชตได้เหมือน ChatGPT (ไม่ต้องลง Ollama)
- **โหมด local/ส่วนตัว**: ลง Ollama → ข้อมูลไม่ออกเครื่อง (bind 127.0.0.1)

โหลดจาก **Actions → build-exe → Artifacts → `LCA-Desktop-exe`** (หรือหน้า Releases เมื่อ push tag) — ดู `docs/INSTALLER_EXE.md`

## ติดตั้งด้วยตัวติดตั้ง .exe (ถ้ามีการปล่อย Release แล้ว)

ถ้ามี Release บน [หน้า Releases](https://github.com/Ragam111/9nammon/releases) แล้ว —
โหลด **`TokenLCAlimit.exe`** → ดับเบิลคลิก → เลือกโฟลเดอร์ → แถบวิ่งจนเขียวเต็ม → Close พร้อมใช้งาน
(ยังต้องมี **Python + Ollama** บนเครื่องปลายทาง — ตัว .exe เป็นตัวติดตั้ง ไม่ได้ฝัง runtime)

> ไฟล์ .exe ถูก build อัตโนมัติด้วย GitHub Actions ตอน push tag `v*` (ดู `docs/INSTALLER_EXE.md`)

## ติดตั้ง (แบบดาวน์โหลดแพ็กเกจเอง) — ดับเบิลคลิกล้วน ไม่ต้องใช้เทอร์มินัล

1. กด **⬇ ดาวน์โหลด .zip** (จากหน้า `/install` หรือ [GitHub](https://github.com/Ragam111/9nammon/archive/refs/heads/main.zip))
2. **คลิกขวา → Extract All** แตกไฟล์ (ได้โฟลเดอร์ `9nammon-main`)
3. เข้าโฟลเดอร์ แล้ว **ดับเบิลคลิก `install.bat`** → ติดตั้งให้อัตโนมัติ (เสร็จแล้วเปิดโฟลเดอร์ติดตั้งให้)
4. **ดับเบิลคลิก `start-lca.bat`** → เปิดเซิร์ฟเวอร์ + เด้งเบราว์เซอร์หน้าแชทให้เอง (ไม่ต้องพิมพ์คำสั่ง)
   · หรือ **`lca-desktop.bat`** → เปิดเป็น **หน้าต่างแอป** (app-mode เหมือน Claude/OpenAI/Gemini Desktop)

> ต้องมี **Python** และ **Ollama** ก่อน (ตัวติดตั้งจะบอกลิงก์ถ้ายังไม่มี) แล้วดึงโมเดลครั้งเดียว
> ตามที่แนะนำ เช่น `ollama pull qwen2.5-coder:1.5b`

**หรือถ้าถนัด PowerShell**:
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

สคริปต์จะ:
1. เช็คว่ามี Python และ Ollama ติดตั้งแล้วหรือยัง (ถ้าไม่มีจะบอกลิงก์ให้ไปโหลด)
2. ตรวจ RAM เครื่องอัตโนมัติ แล้วแนะนำโมเดล Ollama ที่เหมาะสม:
   | RAM | โมเดลแนะนำ |
   |---|---|
   | ต่ำกว่า 8GB | `qwen2.5-coder:0.5b` |
   | 8–16GB | `qwen2.5-coder:1.5b` |
   | 16–32GB | `qwen2.5-coder:7b` |
   | 32–64GB | `qwen2.5-coder:14b` |
   | 64GB+ | `qwen2.5-coder:32b` |
3. ติดตั้งไฟล์ไปที่ `%LOCALAPPDATA%\LocalCodeAssistant`
4. สร้างคำสั่ง `lca` ให้เรียกใช้จาก terminal ไหนก็ได้ (เพิ่มเข้า PATH อัตโนมัติ)

**หลังติดตั้ง** ต้องดึงโมเดลด้วยตัวเองอีก 1 ครั้ง (สคริปต์ไม่ pull ให้อัตโนมัติ
เพราะไฟล์โมเดลมีขนาดหลาย GB ควรให้ผู้ใช้กดยืนยันเอง):
```
ollama pull qwen2.5-coder:1.5b
```
(เปลี่ยนชื่อโมเดลตามที่ install.ps1 แนะนำ/ที่คุณเลือกไว้)

## ใช้งาน

เปิด terminal ใหม่ (CMD หรือ PowerShell) แล้ว:
```
lca C:\path\to\your\project
```
หรือเปิดหน้าเว็บ Chat UI:
```
lca-web C:\path\to\your\project
```
แล้วเปิดเบราว์เซอร์ที่ `http://127.0.0.1:8420`

## แนะนำ Terminal setup (ไม่บังคับ)

`lca` ใช้ ANSI escape code ธรรมดาแสดงสี (ดู `Color` class ใน `local_coder.py`)
รันได้ในทุก terminal อยู่แล้ว (CMD, PowerShell, Windows Terminal) — รายการด้านล่าง
เป็นแค่ **ตัวเลือกเสริมสำหรับคนที่อยากได้ประสบการณ์ใช้ terminal ที่ลื่นขึ้น**
ไม่เกี่ยวกับการรัน `lca` ให้ได้ผลลัพธ์ถูกต้อง ไม่ติดตั้งก็ใช้งานได้ปกติ:

| ส่วนประกอบ | ตัวเลือกที่แนะนำ | เหตุผล |
|---|---|---|
| Terminal Emulator | [Alacritty](https://github.com/alacritty/alacritty), [Kitty](https://sw.kovidgoyal.net/kitty/), [Warp](https://www.warp.dev/) | รองรับ True Color เต็มรูปแบบ, render เร็วกว่า CMD เดิม |
| Shell | [Zsh](https://www.zsh.org/) (WSL/macOS/Linux), [Fish](https://fishshell.com/) | มี auto-suggest และจัดการธีมง่ายกว่า `cmd.exe`/PowerShell เปล่าๆ |
| Prompt Framework | [Starship](https://starship.rs/) | โชว์สถานะ Git/Node ในบรรทัดคำสั่งแบบมินิมอล ใช้ได้ทั้ง PowerShell/Zsh/Fish |
| Font | [Nerd Fonts](https://www.nerdfonts.com/) เช่น JetBrainsMono Nerd Font | ต้องมีถ้าจะใช้ไอคอนของ Starship/theme อื่นๆ ไม่งั้นจะเห็นเป็นกล่องเปล่า `▯` |

หมายเหตุ: Alacritty/Kitty/Zsh/Fish/Starship ไม่ใช่ของทีมนี้เขียนเอง เป็นเครื่องมือ
โอเพนซอร์สทั่วไปที่แนะนำแยกต่างหาก — ยังไม่ได้ทดสอบร่วมกับ `lca` จริงบน Windows
(ทดสอบแค่ CMD/PowerShell ธรรมดา ดูหัวข้อ "สถานะที่ยังไม่ทดสอบจริง" ด้านล่าง)

## ถอนการติดตั้ง

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```
ลบเฉพาะไฟล์โปรแกรม ไม่แตะไฟล์โปรเจกต์ของคุณ (todos.json / CHANGELOG_local.md
อยู่แยกในแต่ละโฟลเดอร์โปรเจกต์ที่คุณใช้งาน ไม่ได้อยู่ใน install directory)

## อัปเดต

1. ดาวน์โหลดแพ็กเกจเวอร์ชันใหม่มาทับโฟลเดอร์นี้
2. รัน:
   ```powershell
   powershell -ExecutionPolicy Bypass -File update.ps1
   ```
อัปเดตเฉพาะไฟล์โปรแกรม ไม่ลบไฟล์งานของคุณ

## หมายเหตุด้านความปลอดภัย

- `lca-web` เปิด server ที่ `127.0.0.1` (เฉพาะเครื่องนี้) เป็นค่าเริ่มต้นเท่านั้น
- ถ้าต้องการให้มือถือ/เครื่องอื่นใน Wi-Fi เดียวกันเข้าถึงได้ ต้องรัน
  `server.py --host <IP ของเครื่องนี้ใน LAN> --token <รหัสลับที่ตั้งเอง>` เอง
  (ห้ามเปิดโดยไม่ตั้ง token — ดูรายละเอียดใน `SKILL.md` ของโปรเจกต์หลัก)

## สถานะที่ยังไม่ทดสอบจริง

สคริปต์ PowerShell ชุดนี้เขียนและตรวจ syntax แบบ static แล้ว แต่ **ยังไม่ได้รันจริง
บนเครื่อง Windows** (แซนด์บ็อกซ์ที่สร้างไฟล์นี้เป็น Linux ไม่มี PowerShell ให้ทดสอบ)
ส่วน `local_coder.py`/`server.py` ที่อยู่ในแพ็กเกจนี้ทดสอบแล้วว่ารันได้ถูกต้องบน Linux
กรุณาทดสอบ `install.ps1` บนเครื่อง Windows จริงอีกครั้งก่อนแจกจ่ายให้คนอื่นใช้
