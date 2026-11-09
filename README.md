# Local Code Assistant (LCA) — Windows Package

**Version:** 0.3.4 · [CHANGELOG](CHANGELOG.md)

ตัวติดตั้ง AI Coding Assistant แบบฟรี รันด้วย Ollama บนเครื่อง (Windows 10/11, AMD64)

## 🚀 เริ่มเร็ว (Windows 10/11)

เปิด **PowerShell** แล้ววางทีละบรรทัด — โหลด Release ล่าสุด + ตรวจ SHA-256 ให้เอง

**ติดตั้ง**
```powershell
powershell -ExecutionPolicy Bypass -c "iex ((irm https://raw.githubusercontent.com/Ragam111/9nammon/main/install.ps1) -replace '^\uFEFF')"
```

**อัปเดต** (เก็บข้อมูลเดิม, migrate ฐานข้อมูล, เปิดแอปกลับให้)
```powershell
lca-update
```
ครั้งแรกที่อัปจาก 0.1.x (ยังไม่มี `lca-update`) ใช้:
```powershell
powershell -ExecutionPolicy Bypass -c "iex ((irm https://raw.githubusercontent.com/Ragam111/9nammon/main/update.ps1) -replace '^\uFEFF')"
```

ต้องมี Python 3.10+ ก่อน · โหมด local ต้องมี [Ollama](https://ollama.com/download/windows) ·
เครื่อง RAM 8GB ตัวติดตั้งจะถามว่าจะจูน Ollama ไหม (`scripts/setup-ollama.ps1`)

*Quick start (EN): run the two lines above in PowerShell — install, then `lca-update` to update.
Both download the latest GitHub Release and check its SHA-256 before installing.*

## 📥 แนะนำที่สุด: `LCA-Desktop.exe` — LCA Chat ก้อนเดียว เหมือน Claude Desktop

ไปที่ [**หน้า Releases**](https://github.com/Ragam111/9nammon/releases) → โหลด **`LCA-Desktop.exe`** (~10 MB) → ดับเบิลคลิก → **แชตได้เลย**

- ✅ **ก้อนเดียวจริง** — ฝัง Python runtime + server + app assets (pyinstaller `--onefile --add-data`)
- ✅ ไม่กระจายไฟล์ ไม่ต้อง extract zip ไม่ต้องลง Python
- ✅ **First-run wizard** — ครั้งแรกเปิดจะไปหน้า `/console` ให้ตั้งสมอง (API key หรือ Ollama) → ครั้งที่ 2+ เปิดหน้าแชตตรง (เหมือน Claude Desktop ขอ API key ครั้งแรก)
- ✅ Cloud mode (OpenAI/TokenMe/vLLM) หรือ Local mode (Ollama — ข้อมูลไม่ออกเครื่อง)
- 🔒 bind `127.0.0.1` — ข้อมูลเก็บที่ `%LOCALAPPDATA%\LocalCodeAssistant\data`

> 📖 คู่มือ advanced users: [`docs/LCA_CHAT.md`](docs/LCA_CHAT.md) — เทียบกับ Claude Desktop + API access + bot workflows

## 🔧 ทางเลือก: `TokenLCAlimit.exe` — ตัวติดตั้ง GUI (ต้องมี Python)

ถ้ามี Python 3.10+ อยู่แล้ว + อยากติดตั้งแบบระบบ (ใช้ CLI/server เองได้) → โหลด **`TokenLCAlimit.exe`** (~12 MB) → ดับเบิลคลิก → GUI → เลือกโฟลเดอร์ → ติดตั้ง

- ตรวจพื้นที่ดิสก์อัตโนมัติ (รวม TEMP folder — v0.1.1 bug fix) — fail-fast ถ้าดิสก์เต็ม
- ติดตั้งลง `%LOCALAPPDATA%\LocalCodeAssistant\` (ไม่ต้อง admin)
- ⚠️ ต้องมี **Python 3.10+** และ **Ollama** บนเครื่อง

> ❗ **ถ้าดาวน์โหลด zip แล้วแตกไฟล์เอง** และเจอ **"Not enough space on the disk"** จาก WinRAR — ลบไฟล์ใน `Downloads`/`Desktop` ก่อน หรือใช้ `LCA-Desktop.exe` แทน (ไม่ต้อง extract เลย)

## มีอะไรให้ใช้บ้าง
- **แชตช่วยเขียนโค้ด** — CLI (`lca`) หรือเปิดหน้าเว็บด้วย `start-lca.bat` / `lca-desktop.bat` → `http://127.0.0.1:8420`, ตอบแบบสตรีมทีละคำ
- **ผู้ใช้หลายคน + สิทธิ์ (RBAC)** — ลูกน้อง login ได้, แอดมินเข้าผ่าน "รหัสไททัน" (master token) = CEO
- **พื้นที่ส่วนตัว/บริษัท (spaces)** — แยกข้อมูลต่อคน/ทีม ไม่ปนกัน
- **คลัสเตอร์หลายเครื่อง** — รวม health ที่เดียว + ส่งงานไปทำที่เครื่องที่พร้อม (cluster forward)
- **AI agent สายเทค (สภาที่ปรึกษา)** — `python -m app.agent council "โจทย์"` หลายมุม (ceo/elon/jobs/…) แล้วสังเคราะห์
- **เฝ้าระบบ 24/7 + rollback config** — เตือนเมื่อผิดปกติ, ย้อนเวอร์ชันได้เมื่อ incident
- **เสียบ cloud GPU ได้** — สลับ backend เป็น OpenAI-compatible endpoint จากหน้า `/dev`
- **Console ต่อสมอง AI ภายนอก (`/console`)** — ต่อ OpenAI-compatible (TokenMe/vLLM/cloud) หรือ Ollama หลายตัว → ทำ **Skills** (prompt สำเร็จรูป) → เปิดเป็น **Bots** ให้ n8n ยิง `POST /api/bots/run` (ดู `docs/CONSOLE_PLATFORM.md`)
- **System tray installer** — ติดตั้งปุ๊บแล้วอยู่ใน tray เหมือน Discord/Steam
- **เวลาเปิด-ปิดเซิร์ฟเวอร์** (schedule gate) — ปิด server นอกเวลาทำการเพื่อประหยัดค่า cloud/ไฟ, แจ้งลูกค้าผ่าน `GET /api/status`

> **เวอร์ชันล่าสุด:** ดู `CHANGELOG.md` (อัพเดตทุก PR cycle)

> เอกสารเพิ่มเติม: `docs/CLUSTER.md`, `docs/AGENTS.md`, `docs/learn/` (ความรู้พื้นฐาน)
>
> **อยากเปิดให้คนอื่นเข้าผ่านเน็ต (โดเมน + server ฟรี)?** ทำตามทีละขั้นที่ `docs/SETUP.md`
>
> **อยากเข้าใจทั้งระบบแบบคอร์ส (ไฟล์ไหนทำอะไร, frontend↔backend, สร้างใหม่ทีละขั้น)?** อ่าน `docs/APP_WALKTHROUGH.md`

## แอปเดสก์ท็อป `LCA-Desktop.exe` (เหมือน ChatGPT/Claude/Gemini desktop)

ดับเบิลคลิก **`LCA-Desktop.exe`** → เปิดหน้าต่างแอป → แชตได้เลย (ฝัง Python+server มาในตัว ไม่ต้องลง Python)
- **โหมด cloud**: ตั้ง connection + API key ที่ `/console` → แชตได้เหมือน ChatGPT (ไม่ต้องลง Ollama)
- **โหมด local/ส่วนตัว**: ลง Ollama → ข้อมูลไม่ออกเครื่อง (bind 127.0.0.1)

โหลดจาก **Actions → build-exe → Artifacts → `LCA-Desktop-exe`** (หรือหน้า Releases เมื่อ push tag) — ดู `docs/SETUP.md`

## ติดตั้งด้วยตัวติดตั้ง .exe (ถ้ามีการปล่อย Release แล้ว)

ถ้ามี Release บน [หน้า Releases](https://github.com/Ragam111/9nammon/releases) แล้ว —
โหลด **`TokenLCAlimit.exe`** → ดับเบิลคลิก → เลือกโฟลเดอร์ → แถบวิ่งจนเขียวเต็ม → Close พร้อมใช้งาน
(ยังต้องมี **Python + Ollama** บนเครื่องปลายทาง — ตัว .exe เป็นตัวติดตั้ง ไม่ได้ฝัง runtime)

> ไฟล์ .exe ถูก build อัตโนมัติด้วย GitHub Actions ตอน push tag `v*` (ดู `docs/SETUP.md`)

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
หรือเปิดหน้าเว็บ Chat UI (ดับเบิลคลิก):
```
start-lca.bat     — เปิด server + browser ที่ 127.0.0.1:8420
lca-desktop.bat   — เปิดในหน้าต่างแอป (Edge/Chrome --app mode)
```

## Develop in VS Code

เปิดโฟลเดอร์นี้ใน VS Code บน Windows (CI ใช้ Python 3.13):

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest ruff
code .
```

`pytest` กับ `ruff` เป็นเครื่องมือตอนพัฒนา ไม่ได้อยู่ใน `requirements.txt` และ CI ไม่รัน ruff
แชตต้องมี Ollama ที่ `127.0.0.1:11434`

| Run and Debug / Run Task | คำสั่งจริง |
|---|---|
| LCA Server (web UI :8420) | `python server.py` (โปรเจกต์ = โฟลเดอร์ปัจจุบัน; ระบุเองได้ `python server.py <โฟลเดอร์>`) — พิมพ์ลิงก์ `http://127.0.0.1:8420/chat#lca_token=…` ให้คลิก |
| LCA Desktop (`lca_app.py`) | `python lca_app.py` (ไม่มี argument; `--version` ได้) |
| LCA CLI (`local_coder.py`) | `python local_coder.py <โฟลเดอร์> --model qwen2.5-coder:3b` |
| Installer GUI | `python installer_gui.py` |
| test: all (CI parity) | `python -m unittest discover -s tests` |
| version smoke | `python server.py --version` (ไม่ต้องใส่โฟลเดอร์) |

คอนฟิกดีบักของ server ใช้โฟลเดอร์ workspace เป็น `project_dir` และเคลียร์ `PORT` / `LCA_HOST`
เพื่อไม่ให้ค่า cloud ทับพอร์ต 8420 — `start-lca.bat` ที่ติดตั้งแล้วส่ง `%USERPROFILE%` แทน
ไฟล์ใน repo เป็น LF (`files.eol` ใน `.vscode/settings.json` จึงเป็น `\n`)
task ชี้ `.venv\Scripts\python.exe` (Windows)

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

```powershell
lca-update
```
หรือดับเบิลคลิก `lca-update.bat` ในโฟลเดอร์ที่ติดตั้ง. ขั้นตอน: โหลด Release ล่าสุด → ตรวจ SHA-256 →
ปิด LCA ที่เปิดอยู่ → ทับเฉพาะไฟล์โปรแกรม → migrate ฐานข้อมูล (มี backup) → เปิดกลับ.
ไม่แตะ `%LOCALAPPDATA%\LocalCodeAssistant\data` และไฟล์ในโปรเจกต์ของคุณ.
ออฟไลน์: แตก `lca-source.zip` แล้วรัน `update.ps1 -Package <โฟลเดอร์ที่แตก>`.

## หมายเหตุด้านความปลอดภัย

- `start-lca.bat`/`lca-desktop.bat` เปิด server ที่ `127.0.0.1` (เฉพาะเครื่องนี้) เป็นค่าเริ่มต้นเท่านั้น
- ถ้าต้องการให้มือถือ/เครื่องอื่นใน Wi-Fi เดียวกันเข้าถึงได้ ต้องรัน
  `server.py --host <IP ของเครื่องนี้ใน LAN> --token <รหัสลับที่ตั้งเอง>` เอง
  (ห้ามเปิดโดยไม่ตั้ง token — ดูรายละเอียดใน `SKILL.md` ของโปรเจกต์หลัก)

## สถานะที่ยังไม่ทดสอบจริง

สคริปต์ PowerShell ชุดนี้เขียนและตรวจ syntax แบบ static แล้ว แต่ **ยังไม่ได้รันจริง
บนเครื่อง Windows** (แซนด์บ็อกซ์ที่สร้างไฟล์นี้เป็น Linux ไม่มี PowerShell ให้ทดสอบ)
ส่วน `local_coder.py`/`server.py` ที่อยู่ในแพ็กเกจนี้ทดสอบแล้วว่ารันได้ถูกต้องบน Linux
กรุณาทดสอบ `install.ps1` บนเครื่อง Windows จริงอีกครั้งก่อนแจกจ่ายให้คนอื่นใช้
