---
name: local-code-assistant
description: >

  LCA (Local Code Assistant) v0.2.9 — AI Coding Assistant + Desktop App แบบก้อนเดียว
  รันบน Ollama (local/cloud hybrid), bind 127.0.0.1, 1124 tests pass, Cloud Tunnel routes wired.

  ใช้ skill นี้เมื่อผู้ใช้ต้องการ: ผู้ช่วยเขียนโค้ดที่รันใน terminal, แก้ไฟล์โค้ด
  อัตโนมัติแบบ diff, ใช้โมเดล local (Ollama) แทน Claude/OpenAI, desktop app (.exe
  ไฟล์เดียว), AI Cluster LAN setup (Ollama+LiteLLM+WebUI+Cloudflare), 3-agent pattern,
  หรือพูดถึง "Aider", "coding agent ฟรี", "local LLM coding", "LCA Desktop"


skill_memory_updated: "2026-11-08"
version: "0.2.9"
tests_pass: 1124
customer_readiness_doc: "CUSTOMER_READINESS.md"

---

# Local Code Assistant (Aider-style, powered by Ollama)

## Description — คำอธิบาย

Skill นี้คือชุดเครื่องมือ (CLI + หน้าเว็บ + backend server) สำหรับให้ผู้ใช้มี
"ผู้ช่วยเขียนโค้ดแบบ AI" ของตัวเอง ที่ทำงานคล้าย Claude Code หรือ Aider แต่:
- **รันในเครื่องผู้ใช้เอง 100%** ผ่านโมเดล Ollama (ฟรี ไม่มีค่า token, ไม่ต้องมี
  internet หลัง pull โมเดลแล้ว)
- **เหมาะกับเครื่องสเปกจำกัด** (netbook, RAM ตั้งแต่ 8GB ขึ้นไป) โดยเลือกขนาด
  โมเดลอัตโนมัติตาม RAM ที่มี
- **มี workflow ความปลอดภัยบังคับ** (อ่าน→ตรวจซ้ำ→แก้→รายงาน) ทุกครั้งที่แก้ไฟล์
  กัน path traversal และ backup อัตโนมัติ
- **มี "หน่วยความจำถาวร" ของตัวเองที่โฟลเดอร์เดสก์ท็อป** — ทุกครั้งที่ผู้ช่วยแก้ไฟล์
  หรือจัดการ todo ข้อมูลจะถูก sync ไปที่ `~/Desktop/LocalCodeAssistant-Data/`
  ทันที เหมือนเป็น "สมอง" กลางที่เก็บประวัติงานของทุกโปรเจกต์ไว้ที่เดียว ให้ผู้ใช้
  เปิดดูย้อนหลังได้ตลอดโดยไม่ต้องเข้าไปหาทีละโปรเจกต์ (ดูหัวข้อ "พื้นที่จัดเก็บ
  ข้อมูลถาวร" ด้านล่าง)
- มาพร้อม todo system, ตัวติดตั้งสำหรับ Windows, และแผนขยายเชื่อม project
  ภายนอก (Linear — ปัจจุบันพักไว้ก่อนตาม Rule ข้อ 16)

พูดสั้นๆ: **"Claude Code เวอร์ชันฟรี รันในเครื่อง เก็บข้อมูลไว้ให้เห็นตลอดที่หน้าเดสก์ท็อป"**

**ขอบเขตจริงของ "หน่วยความจำ" นี้ (พูดตรงๆ กันสับสน)**: ตอนนี้เป็นการ **เขียน
ข้อมูลออกไปเก็บ (archive)** เท่านั้น — ไม่ใช่การ fine-tune โมเดลหรือทำให้โมเดล
"จำ" อะไรได้จริงในความหมาย AI memory ทุกครั้งที่เริ่มเซสชันใหม่ โมเดล Ollama
ยังเริ่มจากศูนย์เหมือนเดิม ไฟล์ในเดสก์ท็อปเป็นแค่ที่เก็บให้**ผู้ใช้**เปิดอ่านเอง
หรือถ้าจะให้โมเดล "จำ" ข้ามเซสชันได้จริง ต้องมีอีกขั้นคือโหลด `index.json`/
`CHANGELOG_local.md` เก่ากลับเข้า context ตอนเริ่มสนทนาใหม่ — ฟีเจอร์นี้ยัง
ไม่ implement (ดูตาราง TODO)

## Instructions — สรุปขั้นตอนสำหรับผู้ใช้ที่จะไปติดตั้งจริงบน Windows

ไฟล์ติดตั้งอยู่ที่ราก repo (โฟลเดอร์ `windows-package/` ไม่มีแล้ว)
ขั้นตอนสำหรับผู้ใช้ (รายละเอียดใน `README.md`):

1. **ทางที่แนะนำ**: โหลด `LCA-Desktop.exe` จากหน้า Releases แล้วดับเบิลคลิก
   หรือใช้ `TokenLCAlimit.exe` (`installer_gui.py`) ถ้ามี Python อยู่แล้ว
2. **หรือดับเบิลคลิก `install.bat`** หลังแตก zip
   (หรือรัน `install.ps1` ผ่าน PowerShell ถ้าถนัด)
   - สคริปต์จะตรวจ RAM อัตโนมัติแล้วแนะนำโมเดลให้ กด Enter ยอมรับ หรือพิมพ์
     ชื่อโมเดลอื่นเองก็ได้
   - ติดตั้งออนไลน์บรรทัดเดียวใช้ `install.ps1` (`install_online.ps1` ลบใน v0.1.3, #101):
     `powershell -ExecutionPolicy Bypass -Command "iwr -useb https://raw.githubusercontent.com/Ragam111/9nammon/main/install.ps1 | iex"`
3. **ติดตั้ง Ollama** ถ้ายังไม่มี (ลิงก์จะโชว์ตอนรัน install.ps1) แล้วรัน
   `ollama pull <ชื่อโมเดลที่แนะนำ>`
4. **เปิด terminal ใหม่** แล้วใช้คำสั่ง `lca <path โปรเจกต์>` (CLI) หรือ
   `start-lca.bat` (หน้าเว็บที่ `http://127.0.0.1:8420`) หรือ `LCA-Desktop.exe --version` เพื่อตรวจเวอร์ชัน
   — `start-lca.bat` เรียก `python server.py "%USERPROFILE%" --port 8420`
   แล้วเปิดเบราว์เซอร์ให้ คำสั่ง `lca-web` / ไฟล์ `lca-web.bat` ลบใน v0.1.3 (#101)
5. **ตรวจสอบพื้นที่เก็บข้อมูลถาวร**: พิมพ์ `/archive` ใน CLI เพื่อดู path เดสก์ท็อป
   ที่ข้อมูลถูก sync ไปไว้ (ค่าเริ่มต้นคือ `Desktop\LocalCodeAssistant-Data\`
   บน Windows)
6. **ถอน/อัปเดต** ทำได้ด้วย `uninstall.ps1` / `update.ps1` ในโฟลเดอร์เดียวกัน
7. **Linux/macOS** ไม่มี `install.sh` แล้ว (ลบใน v0.1.3, #101):
   `pip install -r requirements.txt` แล้ว `python server.py <โฟลเดอร์โปรเจกต์>`

**สิ่งที่ผู้ใช้ต้องรู้ก่อนใช้จริง (ย้ำอีกครั้งจาก TODO table)**: สคริปต์ `.ps1`
ทั้งหมดเขียนและตรวจ syntax แบบ static แล้ว แต่ **ยังไม่เคยรันบน Windows จริง**
เพราะสภาพแวดล้อมที่พัฒนา skill นี้เป็น Linux ควรทดสอบขั้นตอนที่ 2 (install.bat)
ก่อนเป็นอันดับแรกบนเครื่อง Windows จริง หากเจอปัญหาให้แจ้งกลับมาเพื่อแก้ไข

## Trigger — เมื่อไหร่ Claude ควรเรียกใช้ skill นี้

แบ่งเป็น 2 แบบ: **keyword-based** (พูดถึงชื่อเครื่องมือ/เทคโนโลยีตรงๆ) และ
**intent-based** (ไม่พูดชื่อเครื่องมือเลย แต่ความต้องการตรงกับ skill นี้)
Claude ควรเรียก skill นี้เมื่อเข้าเงื่อนไขข้อใดข้อหนึ่งด้านล่าง — ไม่จำเป็นต้อง
เจอ keyword ตรงตัวเสมอไป เพราะผู้ใช้จำนวนมากไม่รู้จักชื่อ Ollama/Aider มาก่อน

**Keyword-based:**
- พูดถึง "Aider", "Claude Code แบบฟรี", "local LLM coding", "Ollama coding"
- ขอปรับปรุง/แก้ไข `local_coder.py`, `server.py`, `SKILL.md`, หรือไฟล์ติดตั้งที่ราก repo
  (`install.ps1`, `install.bat`, `start-lca.bat`) ของ skill นี้โดยเฉพาะ

**Intent-based (ไม่ต้องพูดชื่อเครื่องมือก็เข้าเงื่อนไขได้):**
- ต้องการ "AI coding assistant" หรือ "coding agent" ที่รันบน terminal ของตัวเอง
- ต้องการแก้ไฟล์โค้ดอัตโนมัติแบบ diff โดยไม่พึ่ง API ที่เสียเงิน (Claude/OpenAI)
- บอกข้อจำกัดสเปกเครื่อง (RAM น้อย, ไม่มี GPU, เป็น netbook) พร้อมอยากได้ผู้ช่วยเขียนโค้ด
- อยากได้ผู้ช่วย AI ที่ **เก็บข้อมูล/ประวัติงานไว้ที่เดียวถาวร** เช่น พูดถึง
  "อยากให้มันจำงานไว้ที่เดสก์ท็อป", "เก็บ log ไว้ดูย้อนหลังได้", "โฟลเดอร์รวมข้อมูล"
- อยากได้ตัวติดตั้งที่ใช้งานง่ายแบบแอป (ติดตั้ง/ถอน/อัปเดตได้) สำหรับเครื่องมือ
  AI coding ที่รันในเครื่อง

**ไม่ใช้** เมื่อผู้ใช้แค่ต้องการให้ Claude เขียน/แก้โค้ดให้ตรงๆ ในแชทนี้
(กรณีนั้นทำงานได้เลยไม่ต้องผ่าน skill)

### ฟังก์ชันเป้าหมาย (สิ่งที่ตัวผู้ช่วยต้องทำได้ให้ครบแบบ Claude Code)

| ฟังก์ชัน | รายละเอียด |
|---|---|
| **ภาษา 2 ภาษา** | ตอบเป็นไทยเป็นค่าเริ่มต้น สลับเป็นอังกฤษได้เมื่อผู้ใช้สั่งหรือถามเป็นอังกฤษ ตั้งค่าได้ผ่าน `--lang th|en` |
| **ประหยัด token** | ส่งเฉพาะไฟล์/ส่วนที่เกี่ยวข้องเข้า context ไม่ส่งทั้งโปรเจกต์, ตัด system prompt ให้สั้นที่สุดเท่าที่ยังคุม format diff ได้ |
| **Skill-mode อัตโนมัติ** | เปิดโหมดพิเศษที่ให้ระบบตรวจจับเองว่าคำสั่งเข้าข่ายงานแบบไหน (แก้โค้ด / ค้นข้อมูล / เชื่อม project ภายนอก) แล้วเลือก flow ที่เหมาะสมโดยไม่ต้องให้ผู้ใช้พิมพ์คำสั่งเปิดโหมดเอง |
| **ทำงานอัตโนมัติในเครื่องผู้ใช้** | รันเป็น background process/loop บนเครื่อง local ต่อเนื่องได้ ไม่ใช่แค่ตอบครั้งเดียวจบ |
| **เชื่อมกับ project/product ภายนอก** | ตั้งค่า connector สำหรับงานที่ต้องอ้างอิงระบบอื่น เช่น Linear (ticket/issue tracker) — ผู้ใช้สั่งไว้ล่วงหน้าได้ว่าให้ไปดึงงานจาก Linear มาทำต่อ หรืออัปเดตสถานะ ticket กลับไป |
| **พัฒนา/ปรับแต่ง Ollama chat ของตัวเอง** | ไม่ได้ผูกกับ 1 โมเดล — ผู้ใช้สลับ/เทรน/ปรับ prompt โมเดล Ollama ของตัวเองต่อยอดจากสคริปต์นี้ได้ตามคำสั่งที่ตั้งไว้ |
| **แสดงสถานะ Token/Context** | คำสั่ง `/status` แสดงจำนวน token โดยประมาณที่ใช้ไปในบทสนทนาปัจจุบัน เทียบกับ `num_ctx` สูงสุดที่ตั้งไว้ — ไม่ใช่ค่าใช้จ่ายเงิน แต่เป็นเพดานความจำของโมเดล |
| **Up Version หลายเวอร์ชัน** | คำสั่ง `/model <ชื่อ>` สลับโมเดล Ollama ระหว่างสนทนาได้ทันที เช่นสลับจาก `qwen2.5-coder:0.5b` ไป `qwen2.5-coder:1.5b` ถ้า RAM เครื่องรองรับ โดยไม่ต้องออกจากโปรแกรม |
| **รี Token (Reset context)** | คำสั่ง `/reset` ล้าง conversation history ทั้งหมด เริ่มนับ context ใหม่จากศูนย์ — ใช้เมื่อ context เต็มหรือคำตอบเริ่มสับสนจากบทสนทนายาวเกิน |

### เรื่อง Token ที่ต้องเข้าใจให้ตรง (สำคัญ)

- **Ollama local ไม่มีระบบเก็บเงินตาม token** ไม่เหมือน Claude/OpenAI API —
  ใช้ได้ไม่จำกัดจำนวนครั้ง เพราะรันในเครื่องเอง ไม่มีบิล ไม่มี "token หมด"
- สิ่งที่จำกัดจริงคือ **context window (`num_ctx`)** = จำนวน token สูงสุดที่โมเดล
  "จำได้" ในบทสนทนาเดียว ยิ่งตั้งค่าสูง ยิ่งกิน RAM มากขึ้นตามไปด้วย
- **RAM ยิ่งเยอะ → ตั้ง `num_ctx` ได้สูงขึ้น → คุย/ส่งโค้ดเข้า context ได้เยอะขึ้น**
  ก่อนที่จะต้อง reset (ตารางอ้างอิงคร่าวๆ):
  | RAM ว่างจริง | `num_ctx` แนะนำ | ผลลัพธ์ |
  |---|---|---|
  | 8GB (netbook) | 4096–8192 | คุยได้สั้น ต้อง `/reset` บ่อย ถ้าส่งไฟล์เยอะ |
  | 16GB | 16384–32768 | ส่งหลายไฟล์เข้า context พร้อมกันได้มากขึ้น |
  | 32GB+ | 32768+ | ทำงานกับโปรเจกต์ใหญ่ต่อเนื่องได้นานก่อน reset |
- **"รี token" ในที่นี้หมายถึง reset context** ไม่ใช่การเติมโควตา — ใช้ `/reset`
  เพื่อล้างประวัติสนทนาแล้วเริ่มนับ token ใหม่ ไม่มีผลกระทบต่อไฟล์ที่แก้ไปแล้ว

หมายเหตุสำคัญ: ฟังก์ชัน "เชื่อม Linear" และ "ทำงานอัตโนมัติต่อเนื่องในเครื่อง" ต้องอาศัย
credential/API key ของบริการนั้นๆ และการตั้งค่า scheduler (เช่น cron/Task Scheduler)
เพิ่มเติมนอกเหนือจากตัวสคริปต์หลัก — ดูรายละเอียดใน Process ด้านล่าง

## Objective — เป้าหมายหลัก

สร้างผู้ช่วย AI ที่ครอบคลุมงานหลากหลายแบบ Claude ให้ได้มากที่สุดเท่าที่จะทำได้
**โดยไม่มีค่าใช้จ่าย** และรันได้บนเครื่องสเปกจำกัด (RAM ~8GB, ไม่มี GPU แยก)

**เป้าหมายด้านการติดตั้ง (สำคัญพอๆ กับตัวฟีเจอร์)**: ผู้ใช้ทั่วไปที่ไม่คุ้นเคยกับ
PowerShell/CMD ต้องติดตั้งสำเร็จได้เองจริง ไม่ใช่แค่ script รันได้ในทางทฤษฎี — ทุก
ครั้งที่ช่วยผู้ใช้ติดตั้ง ให้เช็ค **Troubleshooting** ด้านล่างก่อนเสมอว่าเจอปัญหานี้
มาก่อนหรือยัง ก่อนเริ่มไล่ debug ใหม่ตั้งแต่ศูนย์
แบ่งเป็น 3 มิติเป้าหมายที่ผู้ใช้ต้องการ:

1. **Claude Code-like** — เขียน/แก้/รีวิวโค้ดในโปรเจกต์จริงผ่าน terminal
   (ทำได้แล้วใน `local_coder.py`)
2. **Claude Work-like** — ช่วยงานทั่วไปนอกเหนือจากโค้ด เช่น สรุปเอกสาร, ร่างข้อความ,
   วางแผนงาน — ใช้ system prompt แยกโหมด ไม่ผูกกับ diff format ของโหมดโค้ด
3. **Claude Chat-like** — พูดคุยทั่วไป ถาม-ตอบ โดยไม่ต้องมีโปรเจกต์อ้างอิงเลย

**เป้าหมายด้านการเข้าถึง (multi-device / เครื่องมือใช้สะดวก):**
- ใช้งานได้จาก **หลายอุปกรณ์** (PC, มือถือ) โดยรันตัว "สมอง" (Ollama + สคริปต์)
  บนเครื่องหลักเครื่องเดียว แล้วให้เครื่องอื่นเชื่อมเข้ามาผ่านเครือข่ายภายใน (LAN/VPN)
  แทนที่จะติดตั้งซ้ำทุกเครื่อง
- โครงสร้างแบบ **MVC-style server**: แยก Model (เรียก Ollama), View (หน้าเว็บ/
  API response), Controller (รับคำสั่งจากอุปกรณ์ภายนอก) ออกจากกัน เพื่อให้เพิ่ม
  ช่องทางเข้าถึงใหม่ (เว็บ, มือถือ, CLI) ได้โดยไม่ต้องแก้ core logic
- **สั่งงานจากภายนอกได้** เช่น มือถือส่งคำสั่งเข้ามาให้ PC หลักรันงานแทน —
  ทำได้จริงในระดับ local network เท่านั้น (ไม่เปิดพอร์ตออก internet โดยตรง
  เพราะเสี่ยงด้านความปลอดภัย ต้องผ่าน VPN/SSH tunnel ถ้าจะใช้งานนอกบ้าน)

**ข้อจำกัดที่ต้องยอมรับตรงๆ:**
- โมเดล local ขนาดเล็ก (0.5b–3b พารามิเตอร์) **ไม่เก่งเท่า** Claude ระดับพรีเมียม
  ในงานที่ต้องใช้เหตุผลซับซ้อนหลายขั้น หรือโค้ดเบสขนาดใหญ่
- แลกกับความฟรีและ private คือ ต้องยอมรับว่าโมเดลอาจตอบผิดรูปแบบ diff
  บ่อยกว่า ต้องมีระบบตรวจสอบ/ยืนยันก่อน apply เสมอ (ดู Rules ด้านล่าง)
- **สถานะปัจจุบันของโปรเจกต์นี้คือ CLI เดี่ยวบนเครื่องเดียว** (`local_coder.py`)
  ส่วน "MVC Server" + "เข้าถึงจากมือถือ/หลายอุปกรณ์" เป็น **ส่วนขยายที่ยังไม่ได้
  implement** ต้องเพิ่ม web server (เช่น FastAPI) แยกต่างหาก — ดูรายละเอียด
  แผนใน Process ด้านล่าง
- เป้าหมายที่เป็นจริงได้ตอนนี้: งาน routine เช่น เพิ่มฟังก์ชันเล็กๆ, แก้ bug ที่ระบุชัด,
  เขียน boilerplate, อธิบายโค้ด, ตอบคำถามทั่วไป — ไม่ใช่งาน architecture ระดับใหญ่
  หรือ agent ที่ทำงานอิสระเต็มรูปแบบแบบ Claude Code จริงๆ

## PR History — ประวัติ PR ทั้งหมด (autopilot loop)

| PR | Version | วันที่ | เรื่อง | สถานะ |
|---|---|---|---|---|
| #89–#114 | v0.1.0–v0.1.7 | 2026-10-29–11-04 | Official Release → bug fixes → .exe → /api/version → --version → hw-profile tests | ✅ merged |
| #117 | v0.1.8–v0.2.6 | 2026-11-04 | rate-limit tests → stats → news → DB → hw-meter → Ollama selector → LAN discovery → cluster sync → AI cluster setup (1101 tests) | ✅ merged |
| #118 | v0.2.7 | 2026-11-04 | Storage Slim: docs/ 32→22 files, CHANGELOG compact, SKILL.md compact | 🔄 open |

| #195 | v0.2.8 | 2026-11-07 | Cloud Tunnel (cloudflared, free) + consolidated CI workflow + +13 tests | 🔄 open |
| #196 | v0.2.9 | 2026-11-08 | Wire cloud_tunnel routes into server: GET/POST /api/admin/tunnel/* + 10 tests | 🔄 open |


**หลักการ autopilot loop**: open atomic PR → CI → merge → sync branch → next PR
Branch ทำงาน: `claude/windows-package-architecture-j4znro`

---

## TODO — สถานะ Implement จริง (เช็คตรงนี้ที่เดียว)

หัวข้ออื่นในเอกสารนี้พูดถึงฟีเจอร์ที่ "ยังไม่ implement" กระจายอยู่หลายจุด
สรุปรวมไว้ที่นี่ที่เดียวเพื่อเช็คง่าย — อัปเดตทุกครั้งที่มีการเพิ่ม/แก้โค้ดจริง
(ตามกฎข้อ 13 ที่บังคับให้ doc กับโค้ดตรงกันเสมอ):

| ฟีเจอร์ | สถานะ | ไฟล์ | หมายเหตุ |
|---|---|---|---|

| Core features (chat loop, diff, todo, web, CLI, server) v0.0.1–v0.2.6 | ✅ เสร็จครบ | `local_coder.py`, `server.py`, `app/*` | 1124 tests ผ่าน — ดูรายละเอียดใน CHANGELOG.md |
| AI Cluster Setup (Ollama+LiteLLM+WebUI+Cloudflare) | ✅ เสร็จ | `scripts/ai_cluster_setup.sh`, `.claude/skills/ai-cluster-setup/SKILL.md` | single-file bash, 5 phases, `/ai-cluster-setup` skill |
| Cloud Tunnel (cloudflared, free Quick Tunnel) | ✅ เสร็จ | `app/cloud_tunnel.py` | stdlib only, no account needed, 13 tests |
| Cloud Tunnel HTTP routes (GET/POST /api/admin/tunnel/*) | ✅ เสร็จ | `server.py` + `tests/test_tunnel_api.py` | ADMIN-only, 10 tests, Rule 24 |
| Customer Readiness doc + Gap Analysis vs Claude/OpenAI | ✅ เสร็จ | `CUSTOMER_READINESS.md` | ภาษาไทย+อังกฤษ, roadmap P1-P4 |
| Streaming SSE chat (real-time ทีละตัวอักษร) | ❌ ยังไม่มี | `server.py` | P1 roadmap — ต้องทำก่อนจะเป็น chat UI จริง |
| Chat UI (chat.html, bubble layout, markdown) | ❌ ยังไม่มี | `app/chat.html` | P1 roadmap — console.html ไม่ใช่ chat |
| Conversation history / threads | ❌ ยังไม่มี | `app/threads.py` | P2 roadmap |
| Multi-user auth (login, JWT) | ❌ ยังไม่มี | user table + login.html | P2 roadmap |

| `/linear` เขียนสถานะกลับ | ⏸️ พักไว้ก่อน | `app/linear_connector.py` | ห้ามแตะจนกว่าผู้ใช้จะขอกลับมาทำต่อ — ดู Rule ข้อ 16 |

**สิ่งที่ยังไม่ครบแม้ฟีเจอร์หลักจะเสร็จแล้ว**:
- `/linear` ยังไม่มีคำสั่งอัปเดตสถานะ ticket กลับ (มีแต่ฟังก์ชัน `update_issue_status()`
  รอ UI ที่ถาม y/n ก่อนเรียก — ยังไม่ได้ผูกเข้า `/linear` command ใน `local_coder.py`)
- `/model <name>` และ dropdown บนเว็บยังไม่เช็คว่าโมเดลถูก `ollama pull` ไว้จริง
  ก่อนเรียก (จะรู้ว่า error ก็ต่อเมื่อเรียก Ollama แล้วล้มเหลว)
- ทุกการทดสอบข้างต้นทำกับ **mock Ollama/Linear server** (จำลอง response) เพราะ
  sandbox นี้ไม่มี Ollama ติดตั้งจริงและไม่มี Linear API key จริง — ผู้ใช้ควรทดสอบซ้ำ
  กับ Ollama/Linear ของจริงบนเครื่องตัวเองอีกครั้งก่อนใช้งานจริงจัง

## Context — ข้อมูลพื้นฐานที่ต้องรู้ก่อนเริ่ม

- **Hardware**: netbook, RAM 8GB, ไม่มี GPU แยก → ต้องเลือกโมเดลเล็กมากเท่านั้น
- **โมเดลที่แนะนำจริง** (หมายเหตุ: "qwen3.5" ยังไม่มีอยู่จริงในปัจจุบัน — ตระกูลที่มีจริง
  และเก่งเรื่องโค้ดในกลุ่มฟรี/open-weight คือ `qwen2.5-coder`):
  | ระดับ RAM | โมเดลแนะนำ | หมายเหตุ |
  |---|---|---|
  | 8GB (netbook) | `qwen2.5-coder:0.5b` หรือ `qwen2.5-coder:1.5b` | เร็ว แต่ความแม่นยำ diff ต่ำ ต้องตรวจก่อน apply ทุกครั้ง |
  | 16GB | `qwen2.5-coder:7b` | จุดสมดุลดีที่สุดสำหรับ local coding |
  | 32GB | `qwen2.5-coder:14b` หรือ `qwen2.5-coder:32b` (ถ้ามี GPU) | สมดุลระหว่างความเร็วกับคุณภาพ |
  | 64GB+ / มี GPU แรง | `qwen2.5-coder:32b`, `deepseek-coder-v2:16b` | ใกล้เคียงคุณภาพ premium มากขึ้น |
- ทุกอย่างรันผ่าน **Ollama** (`http://localhost:11434`) — ไม่ต้องใช้ internet
  หลัง pull โมเดลแล้ว, ไม่มีค่า token
- ไฟล์หลักของระบบ: `local_coder.py` (CLI: chat loop + diff engine + `/todo` + `/linear`),
  `server.py` (backend web server, MVC-style), `app/index.html` (หน้าเว็บ Chat UI),
  `app/todo_store.py` (todo เก็บ JSON), `app/linear_connector.py` (เชื่อม Linear API),
  `app/desktop_archive.py` (sync ข้อมูลไป `~/Desktop/LocalCodeAssistant-Data/`),
  `app/web_search.py` (switch `/websearch on|off` ค้นเว็บจริงผ่าน Brave API),
  `app/cloud_tunnel.py` (Cloudflare Quick Tunnel — เปิด server ให้เข้าได้จากอินเทอร์เน็ต ฟรี ไม่ต้องมี account),
  `CHANGELOG_local.md` (log ที่ระบบสร้างอัตโนมัติในทุกโปรเจกต์ที่ใช้งาน)

## Troubleshooting — ปัญหาที่เจอจริงตอนช่วยผู้ใช้ติดตั้ง (บันทึกไว้กันถามซ้ำ)

**เคยเจอ: ผู้ใช้แปะโค้ดชุดใหญ่จาก AI อื่น (เอกสาร "HARNESS_ENGINEERING.md") อ้างว่า
เป็นเวอร์ชันปรับปรุงของโปรเจกต์นี้** — ตรวจแล้วพบว่าถ้าใช้แทนทั้งหมดจะเป็นการถอย
หลัง (ไม่มี diff engine/todo/websearch/archive ที่ทดสอบแล้ว, ใช้ `ctypes.windll`
อย่างเดียวจน crash บน Linux/Mac, เปลี่ยน `/api/generate`+prompt เดี่ยวทำลาย
conversation history, installer ขอ admin rights ทั้งที่ของเดิมเลี่ยงได้)
**หลักการ**: เจอโค้ด/config ก้อนใหญ่จาก AI อื่นเมื่อไหร่ ต้อง **สแกนหาไอเดียดีมา
แพตช์เฉพาะจุดเข้าโค้ดที่ทดสอบแล้ว ไม่ใช่ copy-paste แทนที่ทั้งไฟล์** แม้เอกสารจะ
ดูเป็นระบบ/มั่นใจแค่ไหนก็ตาม — ในเคสนี้หยิบมาแค่ 2 อย่างที่ดีจริง: (1) RAM detection
+ `num_thread`/`keep_alive` tuning (แก้ให้ cross-platform ก่อนใช้) (2) self-relocating
uninstaller (copy ไปรันที่ `%TEMP%` ก่อนลบตัวเอง กันปัญหาไฟล์ถูกล็อก) — ทั้งสองแพตช์
เข้า `local_coder.py`/`uninstall.ps1` เดิมแล้ว ทดสอบผ่านแล้วบน Linux (RAM detection
คืนค่าได้จริง, tuning options ส่งถึง mock Ollama ครบ, chat loop เดิมไม่พัง)

รายการนี้มาจากการช่วย debug จริงกับผู้ใช้ ไม่ใช่ทฤษฎี — เช็คก่อนอธิบายใหม่ทุกครั้ง:

| อาการ | สาเหตุจริง | วิธีแก้ที่ใช้ได้ผล |
|---|---|---|
| **`install.ps1` รันแล้ว error `ParserError`/`MissingExpressionAfterToken` เต็มจอ ข้อความไทยกลายเป็นขยะ (`เน€เธฅเธทเธญเธ`)** — พบจากการทดสอบจริงบน Windows ครั้งแรก | **ไฟล์ `.ps1` ไม่มี UTF-8 BOM** — PowerShell 5.1 (default บน Windows) อ่านไฟล์ที่ไม่มี BOM โดยตีความเป็น codepage เก่า (874/1252) แทน UTF-8 ทำให้ข้อความไทยเพี้ยน แล้วไปทำลาย string literal boundary จน parse ไม่ผ่านทั้งไฟล์ | **เติม UTF-8 BOM (`\xef\xbb\xbf`) นำหน้าทุกไฟล์ `.ps1` และ `.iss`/`.txt` ที่มีข้อความไทยแสดงผลจริง** — **ห้ามเติม BOM ให้ `.bat`** เพราะ `cmd.exe` อาจตีความ BOM ผิดจนพังแทน (ถ้า `.bat` มีแต่ข้อความไทยใน `REM` comment ไม่ต้องแก้อะไร เพราะไม่ execute อยู่แล้ว) |
| ดับเบิลคลิก `.ps1` แล้วเจอ "How do you want to open this file?" | Windows ไม่ให้รัน `.ps1` โดยตรงจากการดับเบิลคลิก (security feature) | ใช้ `install.bat` แทนเสมอ ไม่ใช่ `install.ps1` ตรงๆ |
| พิมพ์คำสั่ง PowerShell เองแล้ว error (`-xecutionolicy` ไม่รู้จักคำสั่ง, ตัวพิมพ์ใหญ่หาย) | ผู้ใช้พิมพ์/copy คำสั่งเองแล้วพลาดตัวอักษร | อย่าให้ผู้ใช้พิมพ์คำสั่ง PowerShell เองถ้าเลี่ยงได้ — ให้ดับเบิลคลิก `.bat` แทนเสมอ เพราะ `install.ps1` มีเมนูเลือกไดรฟ์ในตัวอยู่แล้ว ไม่ต้อง set env var เอง |
| "install.bat ไม่มี" / "no file" error ตอนรัน installer | ผู้ใช้ได้ไฟล์มาไม่ครบชุด (ดาวน์โหลดทีละไฟล์แยกจากแชท แทนที่จะโหลดทั้งโฟลเดอร์) — `install.bat` ต้องอยู่โฟลเดอร์เดียวกับ `install.ps1` เพราะอ้างอิงกันด้วย `%~dp0` | **ส่งเป็น .zip รวมไฟล์เดียวเท่านั้น ห้ามส่งแยกไฟล์เมื่อมีไฟล์ที่อ้างอิงกัน** (เช่น .bat เรียก .ps1, หรือ installer.iss อ้างถึงไฟล์อื่นใน [Files]) — ทดสอบ extract แล้วรันจริงก่อนส่งมอบทุกครั้ง |
| มองไม่เห็นนามสกุลไฟล์ (เห็น `install` เฉยๆ ไม่รู้ว่าเป็น `.bat` หรือ `.exe`) | Windows ซ่อนนามสกุลไฟล์ที่รู้จักเป็นค่าเริ่มต้น (`Hide extensions for known file types`) | บอกให้ดูไอคอน (`.bat` = จอดำเล็กๆ) หรือแนะนำเปิด File Explorer → View → ติ๊ก "File name extensions" เพื่อความชัดเจนถาวร |
| **`ModuleNotFoundError: No module named 'folder_trust'`** (หรือ `context_manager`) ตอนรัน `lca` | `local_coder.py` import สองโมดูลนี้ผ่าน `sys.path` ที่ชี้ไปโฟลเดอร์ `app\` แต่ installer เดิม copy ไม่ครบ | **แก้แล้วถาวร**: `update.ps1` v0.1.0 (PR #86) ทำ recursive copy `app\` ทั้งโฟลเดอร์ (รวม `app\agent\*`) + ลบ `fix_missing_modules.ps1` ออกแล้ว (ไม่จำเป็นอีก) — รัน `update.ps1` ใหม่ครั้งเดียวแก้ได้ |
| **ไฟล์ `.ps1` ไม่มี UTF-8 BOM ทั้งที่ SKILL.md บันทึกไว้ว่า "เติม BOM แก้แล้ว"** (พบจากการแพ็ก zip รอบล่าสุด 19 ส.ค. 2026) | เอกสารบันทึกผลลัพธ์ที่ตั้งใจไว้ ไม่ใช่สถานะไฟล์จริงเสมอไป — เมื่อไฟล์ถูกคัดลอก/ส่งต่อผ่านช่องทางอื่น BOM ที่เติมไว้อาจหายระหว่างทางได้ | **ห้ามเชื่อคำบรรยายในเอกสารเฉยๆ ว่า BOM มีอยู่แล้ว — ต้องเปิดไฟล์จริงเช็ค 3 byte แรกทุกครั้งก่อนแพ็ก zip ส่งมอบ** (`b'\xef\xbb\xbf'`) — เจอเคสนี้จริงกับ `install.ps1`/`uninstall.ps1`/`update.ps1` |
| **ไฟล์ `app/*.py` (todo_store, linear_connector, desktop_archive, web_search, config_manager) + `app/index.html` หายไปทั้งหมดจาก working copy** (พบ 19 ส.ค. 2026 ตอนจะแพ็ก zip ส่งทดสอบ) | ไฟล์เหล่านี้เคยเขียนเสร็จจริงตามที่ตาราง TODO บันทึกไว้ แต่ไม่ได้อยู่ใน context/Project files ชุดล่าสุดที่ใช้แพ็ก — เป็นปัญหาการ sync ไฟล์เข้า Project knowledge ไม่ใช่โค้ดหาย | เขียนใหม่ทั้ง 6 ไฟล์จาก **interface ที่ `local_coder.py`/`server.py` เรียกใช้จริง** (อ่านทุกจุด `import`/เรียกฟังก์ชันก่อนเขียน ไม่เดา signature) |

**บทเรียนเชิงระบบจากรายการนี้**: ผู้ใช้ทั่วไปไม่คุ้นเคยกับ PowerShell/CMD/นามสกุลไฟล์ที่ซ่อนอยู่
— เวลาส่งมอบไฟล์ติดตั้งให้ **(1)** always แพ็กเป็น zip เดียวเมื่อมีไฟล์เกิน 1 ไฟล์ที่ต้องอยู่ด้วยกัน
**(2)** ให้ขั้นตอนแบบ "ดับเบิลคลิกไฟล์นี้" ไม่ใช่ "พิมพ์คำสั่งนี้" เป็นตัวเลือกแรกเสมอ
**(3)** ถามหา error message เต็มๆ ทันทีที่ผู้ใช้บอกว่า "error" โดยไม่เดาสาเหตุลอยๆ ก่อน

## Process — ขั้นตอนการทำงานทีละสเต็ป

**ขั้นตอนติดตั้ง (ทำครั้งเดียว):**
1. ติดตั้ง Ollama (`curl -fsSL https://ollama.com/install.sh | sh`)
2. Pull โมเดลเล็กที่เหมาะกับ RAM: `ollama pull qwen2.5-coder:0.5b`
3. เช็คว่า Ollama รันอยู่: `curl http://localhost:11434/api/tags`

**ขั้นตอนใช้งาน (ทุกครั้งที่แก้โค้ด — บังคับ 4 สเต็ป ห้ามข้าม):**
1. **อ่านไฟล์ (Read)** — อ่านไฟล์เป้าหมายสดจากดิสก์ก่อนเสมอ ไม่ใช้ cache เก่า
2. **ตรวจโปรเจกต์ซ้ำ (Re-check)** — สแกนรายชื่อไฟล์ในโปรเจกต์ ดูผลกระทบข้างเคียง
   ก่อน apply diff ใดๆ
3. **แก้ไข (Fix)** — apply เฉพาะหลังผู้ใช้ยืนยัน (y/n) พร้อม backup อัตโนมัติ
4. **เขียนรายงาน (Report)** — บันทึกทุกการเปลี่ยนแปลงลง `CHANGELOG_local.md`
   (เวลา, ไฟล์, สถานะ, สรุป) ไม่ว่าจะสำเร็จหรือล้มเหลว

รายละเอียด implementation ของ 4 สเต็ปนี้อยู่ในฟังก์ชัน `apply_diff_blocks()`
ของ `local_coder.py`

**ขั้นตอน Skill-mode อัตโนมัติ:**
1. รับ input ผู้ใช้ → จัดหมวด: (ก) แก้โค้ดในไฟล์ local, (ข) ค้นข้อมูล/ถามความรู้ทั่วไป, (ค) งานที่ต้องอ้างอิง project ภายนอก
2. ถ้าเป็น (ก) → เข้า flow 4 สเต็ปหลัก
3. ถ้าเป็น (ข) → ตอบตรงในแชท ไม่ต้อง apply diff
4. ถ้าเป็น (ค) → เรียก connector → ดึงข้อมูลงาน → เข้า flow 4 สเต็ปถ้ามีการแก้โค้ด

**การเชื่อมกับ project/product ภายนอก (เช่น Linear):**
1. ผู้ใช้ตั้งค่า API key ใน environment variable (เช่น `LINEAR_API_KEY`) — **ห้าม hardcode**
2. ผู้ใช้สั่ง `/linear sync` เพื่อดึง ticket มาเป็น context
3. เมื่อแก้โค้ดเสร็จ ต้องผู้ใช้ยืนยันก่อนอัปเดตสถานะกลับเสมอ
4. ฟีเจอร์นี้เป็น *ส่วนขยาย* ที่ยังไม่รวมอยู่ใน `local_coder.py` เวอร์ชันปัจจุบัน

**แผนขยายเป็น MVC Server (multi-device access — ยังไม่ implement, เป็น roadmap):**
1. **Model** — ห่อ `call_ollama()` และ `apply_diff_blocks()` ปัจจุบันเป็น service layer
2. **Controller** — เพิ่ม web server (FastAPI) รับ request จากอุปกรณ์ภายนอก
3. **View** — endpoint JSON (สำหรับแอปมือถือ) และหน้าเว็บเบาๆ
4. **ความปลอดภัย** — เปิด server เฉพาะ local network, ใส่ auth token ก่อนรับคำสั่งแก้ไฟล์

## Rules — กฎตายตัว ห้ามทำผิด

1. **ห้าม apply diff โดยไม่ผ่านการยืนยันจากผู้ใช้ (y/n) เด็ดขาด**
2. **ห้ามข้ามขั้นตอนใดใน 4 สเต็ป (Read → Re-check → Fix → Report)**
3. **ห้ามเขียนทับไฟล์โดยไม่ backup ก่อน** — ทุกไฟล์ที่มีอยู่แล้วต้อง copy ไป `.local_coder_backup/`
4. **ห้ามใช้โมเดลใหญ่กว่าที่ RAM รองรับ** — เครื่อง 8GB ห้ามแนะนำโมเดล 7b ขึ้นไป
5. **ห้าม log ข้อมูลอ่อนไหว** (API key, password, token) ลงใน `CHANGELOG_local.md`
6. **ถ้า SEARCH block ไม่ match ไฟล์จริง ให้ข้ามและรายงานว่าล้มเหลว** ห้ามเดาตำแหน่ง
7. **เมื่อแนะนำโมเดล ต้องอิงชื่อที่มีอยู่จริงใน Ollama registry เท่านั้น**
8. **ห้าม hardcode API key** ของบริการภายนอกลงในโค้ด
9. **ห้ามอัปเดตสถานะ/เขียนข้อมูลกลับไปยัง project ภายนอกโดยไม่ผ่านการยืนยัน**
10. **ห้ามใส่ context เกินความจำเป็นเข้า prompt**
11. **เมื่อ Aider ใช้ไม่ได้จริง ห้ามพยายามยัดเยียดให้ติดตั้งซ้ำๆ** ให้ยึด `local_coder.py`
12. **ถ้าขยายเป็น MVC server ห้าม bind ออก internet โดยตรงโดยไม่มี auth**
13. **เมื่อ Claude เขียน/แก้โค้ดในโปรเจกต์นี้เอง ต้องทำตามมาตรฐาน:**
    - เขียนโค้ดให้รันได้จริงก่อนส่งมอบ — ทดสอบด้วย syntax check หรือรันจริงก่อนบอกว่าเสร็จ
    - แก้ไฟล์เดิมด้วย `str_replace` แบบ targeted เท่านั้น ห้ามเขียนทับทั้งไฟล์
    - ห้ามเพิ่ม dependency ภายนอกใหม่โดยไม่จำเป็น — ยึด Python standard library
    - ทุกครั้งที่แก้ `local_coder.py` ต้องอัปเดตส่วนที่เกี่ยวข้องใน `SKILL.md`
14. **มาตรฐานเพิ่มเติม — ห้ามละเลยแม้เป็นการแก้เล็กน้อย:**
    - Error handling บังคับ: ทุกจุดที่เรียก network, อ่าน/เขียนไฟล์, หรือ parse ข้อมูลจากโมเดล
    - ห้ามไว้ใจ input จากโมเดลโดยไม่ตรวจสอบ — path ต้องอยู่ภายใน `project_root`
    - Fail loudly ไม่ใช่ fail silently
    - Idempotency สำหรับ backup
15. **ห้ามเริ่มเขียนโค้ดทันทีสำหรับงานใหญ่โดยไม่เสนอแผนภาพรวมให้ผู้ใช้อนุมัติก่อน**
16. **⚠️ พักฟีเจอร์ Linear ไว้ก่อน** — ห้ามเพิ่ม/แก้โค้ดส่วน `/linear` จนกว่าผู้ใช้จะขอกลับมาทำต่อ
17. **ทุกฟังก์ชันที่เปลี่ยนแปลงข้อมูลถาวรต้องเรียก `sync_project()` ทันทีหลังทำสำเร็จ**
18. **`/websearch` ต้องปิด (0) เป็นค่าเริ่มต้นเสมอ** — ผู้ใช้ต้องเปิดเองทุกครั้ง
19. **งานตกแต่ง UX/UI ต้องยึดหลัก 9arm ข้อ 1 "ไม่แต่งเติม"** — ห้ามอวดอ้างความสามารถเกินจริง
20. **ก่อนช่วย debug ปัญหาการติดตั้ง ต้องเช็คตาราง Troubleshooting ก่อนเสมอ**
21. **Rule of Scrutiny for AI Refactoring** — Never Replace Only Patch; Cross-Platform First; Preserve Stateful Conversations
22. **ทุกไฟล์ `.ps1`/`.iss` ที่มีข้อความไทยต้องมี UTF-8 BOM นำหน้าเสมอ** — ห้ามเติม BOM ให้ `.bat`
23. **`config.json` ต้องไม่ถูก commit เข้า git เด็ดขาด** — ต้องอยู่ใน `.gitignore` และห้าม print ค่า key เต็มๆ ออกจอ

24. **`cloud_tunnel.py` tunnel เฉพาะ `127.0.0.1:{port}` เท่านั้น** — ห้ามแก้ให้ชี้ไป host อื่น หรือ expose LCA token ใน URL

## Observability Chain (v0.1.4–v0.2.9)


| endpoint / คำสั่ง | auth | คืนอะไร | ใช้ตอนไหน |
|---|---|---|---|
| `GET /api/health` | public | ok, ollama, ram_pressure, recommended_model, backend, network | liveness check, smoke test |
| `GET /api/status` | public | isOpen, nextChange, Retry-After | ลูกค้าดูว่าเซิร์ฟเวอร์เปิดอยู่ไหม |
| `GET /api/version` | public | version, python, name | QA/support ถามเวอร์ชัน |
| `server.py --version` | CLI | LCA X.Y.Z (python X.Y.Z) | dev เช็กก่อนรัน |
| `lca_app.py --version` | CLI | LCA Desktop X.Y.Z (python X.Y.Z) | dev/sysadmin เช็ก bundle |
| `GET /api/admin/hw-profile` | ADMIN+ | tier, cpu_model, ram_gb, recommended_config, next_upgrade | support ถามสเปกเครื่อง |
| `GET /api/admin/tunnel/status` | ADMIN+ | running, url, port | ตรวจสถานะ tunnel ปัจจุบัน |
| `POST /api/admin/tunnel/start` | ADMIN+ | url, port | เปิด Cloudflare Quick Tunnel |
| `POST /api/admin/tunnel/stop` | ADMIN+ | stopped | ปิด tunnel |

ทุก endpoint ใช้ `VERSION` file ผ่าน `read_version()` helper เดียวกัน — ไม่มี drift
กฎ: อย่าเพิ่ม observability endpoint ใหม่โดยไม่เพิ่มเข้าตารางนี้

---

## Data Stores — Quick Reference

| โมดูล | ไฟล์ | เก็บที่ | ข้อมูลที่เก็บ |
|---|---|---|---|
| config_manager | `app/config_manager.py` | `config.json` (gitignored) | API keys, model, port — ห้าม commit (Rule 23) |
| secret_store | `app/secret_store.py` | `%LOCALAPPDATA%\LocalCodeAssistant\secrets.json` | encrypted credentials |
| todo_store | `app/todo_store.py` | `{project_root}/todos.json` | todo items ต่อโปรเจกต์ |
| chat_store | `app/chat_store.py` | `{project_root}/chat_history.json` | conversation history |
| desktop_archive | `app/desktop_archive.py` | `~/Desktop/LocalCodeAssistant-Data/` | sync/archive ทุกโปรเจกต์ |
| cluster_store | `app/cluster_store.py` | `%LOCALAPPDATA%\LocalCodeAssistant\cluster.json` | LAN cluster nodes |
| skills_store | `app/skills_store.py` | `%LOCALAPPDATA%\LocalCodeAssistant\skills.json` | installed skills |
| org_store | `app/org_store.py` | `%LOCALAPPDATA%\LocalCodeAssistant\org.json` | org/team config |

**Cloud Tunnel state** — in-memory only (module-level in `app/cloud_tunnel.py`):
`_proc`, `_url`, `_port` — ไม่มี persistence ข้ามรีสตาร์ต, thread-safe with `_lock`

---

## แนวคิด

ตัว Aider จริงๆ ทำ 3 อย่างหลัก:
1. **อ่านโค้ดในโปรเจกต์** → ส่ง context ให้โมเดล
2. **ให้โมเดลตอบกลับเป็น diff / โค้ดเต็ม** → parse แล้ว apply ลงไฟล์จริง
3. **คุยกันต่อเนื่องแบบ chat loop** พร้อม memory ของบทสนทนา

เราจะ clone แนวคิดนี้ แต่ใช้ **Ollama** (รันโมเดล local, ฟรี 100%,
ไม่ต้องมี internet ตอนใช้งาน) แทนการเรียก Claude/OpenAI API

## ทำไมใช้ Ollama

| จุดเด่น | รายละเอียด |
|---|---|
| ฟรี | ไม่มีค่า token, รันในเครื่องล้วนๆ |
| Private | โค้ดไม่หลุดออกนอกเครื่อง |
| ออฟไลน์ได้ | ไม่ต้องพึ่งเน็ตหลัง download โมเดลแล้ว |
| ข้อเสีย | ต้องมีแรมพอ (อย่างน้อย 8GB สำหรับโมเดลเล็ก), คุณภาพสู้ Claude/GPT ระดับ frontier ไม่ได้ |

**คำแนะนำโมเดล** (เรียงตามสเปกเครื่อง):
- เครื่องแรงน้อย (netbook, 8GB RAM): `qwen2.5-coder:1.5b` หรือ `qwen2.5-coder:3b`
- เครื่องกลาง (16GB RAM): `qwen2.5-coder:7b` หรือ `deepseek-coder-v2:16b`
- เครื่องแรง (32GB+ / มี GPU): `qwen2.5-coder:32b`, `codellama:34b`

## ขั้นตอนติดตั้ง

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:3b
curl http://localhost:11434/api/tags
```

## โครงสร้างสคริปต์ผู้ช่วย

`local_coder.py` ทำหน้าที่:
1. รับ path ไฟล์/โฟลเดอร์ที่จะแก้
2. อ่านเนื้อหาไฟล์ ใส่ใน prompt เป็น context
3. ส่งไปที่ Ollama API (`/api/chat`) พร้อม system prompt บังคับตอบเป็น diff block
4. Parse diff แล้ว apply ลงไฟล์จริงด้วยการยืนยันจากผู้ใช้ก่อนทุกครั้ง
5. เก็บ conversation history ไว้คุยต่อเนื่องได้

### รูปแบบ diff (SEARCH/REPLACE block)

```
path/to/file.py
<<<<<<< SEARCH
โค้ดเดิมตรงนี้
=======
โค้ดใหม่ตรงนี้
>>>>>>> REPLACE
```

## เทคนิคสำหรับเครื่องสเปกต่ำ

1. ใช้โมเดลขนาด 1.5b–3b เท่านั้น
2. จำกัด context — ส่งแค่ไฟล์ที่เกี่ยวข้อง
3. ตั้ง `num_ctx` ไม่เกิน 4096–8192 token
4. ปิด GUI อื่นๆ ตอนรันโมเดล

## ทำไมไม่ใช้ Aider ของจริง

- เครื่อง/สภาพแวดล้อมอาจไม่มีสิทธิ์ `pip install` ได้ตลอดเวลา
- Aider ผูกกับ dependency เยอะ กิน RAM ตอนติดตั้ง/รันบนเครื่อง 8GB
- ต้องการ workflow เฉพาะทาง (บังคับ 4 ขั้นตอน, ภาษาไทยเป็นหลัก, เชื่อม Linear)

**ข้อสรุป**: ให้ใช้ `local_coder.py` เป็นหลัก — ควบคุมได้ทุกจุด ไม่มี dependency ภายนอกนอกจาก Python มาตรฐาน + Ollama
