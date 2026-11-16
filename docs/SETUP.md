# LCA — Setup & Deployment Guide

> รวมจาก: DEPLOY.md, GO_LIVE.md, GO_ONLINE_FREE.md, HOSTING.md, BUNDLING.md, INSTALLER_EXE.md, TRAY_INSTALLER.md

---

## DEPLOY

# Deploy LCA ขึ้นเว็บ (มี URL จริง) — ฟรี

> **ความจริงก่อน (9arm):** LCA = **web/API** + **Ollama (ตัว LLM)**. โฮสต์ฟรีส่วนใหญ่
> RAM 256–512MB รัน Ollama ไม่ได้. ทางออก: รัน web/API บนโฮสต์ฟรี แล้วชี้ LLM ไปที่อื่น
> (cloud API ผ่าน adapter) **หรือ** รัน LLM บนเครื่องตัวเอง แล้วเปิด public ด้วย tunnel.

---

## ทางที่ 1 — เทสไลฟ์ทันที (แนะนำสุดสำหรับทดสอบ)

รัน LCA บนเครื่องตัวเอง (Ollama มีอยู่แล้ว) แล้วเปิด public URL ด้วย **Cloudflare Tunnel**
(ฟรี ไม่ต้องใช้บัตร ไม่ต้อง deploy):

```powershell
# 1. รัน LCA (ตั้ง token กันคนอื่นสั่งแก้ไฟล์ — บังคับเมื่อเปิดออกนอกเครื่อง)
$env:LCA_HOST = "0.0.0.0"
$env:LCA_TOKEN = "ตั้งรหัสลับยาวๆ"
python server.py . --port 8420

# 2. อีกหน้าต่าง: เปิด tunnel (โหลด cloudflared ก่อน)
cloudflared tunnel --url http://localhost:8420
```

Cloudflare จะให้ URL แบบ `https://xxxx.trycloudflare.com` — เปิดจากมือถือ/ที่ไหนก็ได้

---

## ทางที่ 2 — ออนไลน์ตลอด 24 ชม. (ฟรี)

### 2a. Hugging Face Spaces / Render (ฟรี)
ตั้ง environment variables บนโฮสต์:
```
LCA_HOST   = 0.0.0.0
LCA_TOKEN  = <รหัสลับ>
MODEL_BACKEND  = openai
OPENAI_BASE_URL = https://<cloud-llm>/v1
OPENAI_API_KEY  = <key>
```

### 2b. Oracle Cloud Always Free (รัน Ollama ได้จริง)
VM ฟรีถาวร: ARM Ampere **4 core / 24GB RAM** — แรงพอรัน Ollama + โมเดลเองได้

---

## Docker

```bash
docker build -t lca .
docker run -p 8420:8420 \
  -e LCA_HOST=0.0.0.0 \
  -e LCA_TOKEN=<secret> \
  -e MODEL_BACKEND=openai \
  -e OPENAI_BASE_URL=https://<cloud-llm>/v1 \
  -e OPENAI_API_KEY=<key> \
  lca
```

---

## ตัวแปร environment ที่ server อ่าน

| env | ความหมาย | ค่า default |
|-----|----------|------------|
| `PORT` | พอร์ต (cloud ฉีดให้) | 8420 |
| `LCA_HOST` | bind address | 127.0.0.1 |
| `LCA_TOKEN` | auth token (บังคับเมื่อ bind ออกนอก localhost) | ไม่มี |
| `LCA_ALLOWED_HOSTS` | ชื่อ host เพิ่มเติมที่รับ คั่นด้วยจุลภาค | ไม่มี |
| `MODEL_BACKEND` | `ollama` \| `openai` | ollama |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | ปลายทาง cloud LLM | — |

> **ความปลอดภัย (Rule 12):** server จะ **ปฏิเสธ** ถ้า bind ออกนอก `127.0.0.1` โดยไม่มี token

---

## GO_LIVE

# LCA — เปิดให้คนใช้จริง (Go Live)

เปิดด้วยคำสั่งเดียว: `./scripts/serve.sh` (ดู `--help`)

## เตรียมก่อนทุกครั้ง
```bash
ollama serve &
ollama pull qwen2.5-coder:1.5b
```

## ระดับ 1 — เฉพาะเครื่องตัวเอง
```bash
./scripts/serve.sh
```
เปิด `http://127.0.0.1:8420`

## ระดับ 2 — เปิดให้คนในบ้าน/ออฟฟิศ (LAN)
```bash
./scripts/serve.sh --lan
```

## ระดับ 3 — เปิดให้คน "นอกวง" (อินเทอร์เน็ต)
```bash
./scripts/serve.sh
cloudflared tunnel --url http://localhost:8420
```

## bootstrap + ออก API key ให้ผู้ใช้
```bash
curl -X POST $URL/api/admin/users -H "X-Auth-Token: $TOK" \
  -d '{"username":"boss","password":"ตั้งรหัสยาว ๆ","role":"CEO"}'
curl -X POST $URL/api/admin/apikeys -H "X-Auth-Token: $TOK" \
  -d '{"owner":"user1","tier":"free"}'
```

## เช็กลิสต์ความปลอดภัยก่อนเปิดจริง
- [ ] token ตั้งไว้แล้ว
- [ ] `config.json`, `org.json`, `*.db` อยู่ใน `.gitignore`
- [ ] ออกเน็ตใช้ tunnel + HTTPS เท่านั้น
- [ ] จับตา `/dev` → มิเตอร์ RAM/CPU

---

## GO_ONLINE_FREE

# เอา LCA ขึ้นออนไลน์ให้ web users ใช้ — 3 เส้นทาง

## เปรียบเทียบ 3 เส้นทาง

| เส้นทาง | ค่าใช้จ่าย | โดเมน | รัน LLM ที่ไหน | เหมาะกับ |
|---|---|---|---|---|
| **A. Cloudflare Tunnel** | ฟรี 100% | ฟรี (subdomain ให้) | เครื่องพี่ | เริ่มไว/ทดสอบ |
| **B. Oracle Cloud Always Free** | ฟรีถาวร | ต้องหาเอง | บน VM ฟรี (24GB RAM) | ออนไลน์ 24 ชม. จริงจัง |
| **C. Render + cloud LLM** | ฟรี/จ่ายตาม LLM | subdomain ให้ | cloud API | ไม่อยากดูแล server |

## เส้นทาง A — Cloudflare Tunnel
```powershell
$env:LCA_HOST = "0.0.0.0"
$env:LCA_TOKEN = "ตั้งรหัสลับยาว ๆ"
python server.py . --port 8420
cloudflared tunnel --url http://localhost:8420
```

## เส้นทาง A+ — WSL (Ubuntu ใน Windows)
```bash
sudo apt update && sudo apt install -y python3 python3-pip git
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:1.5b
git clone https://github.com/Ragam111/9nammon.git && cd 9nammon
export LCA_HOST=0.0.0.0 LCA_TOKEN="รหัสลับยาว ๆ"
python3 server.py . --port 8420
```

## เส้นทาง B — Oracle Cloud Always Free
```bash
ssh ubuntu@<PUBLIC_IP>
sudo apt update && sudo apt install -y python3 python3-pip git
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:1.5b
git clone https://github.com/Ragam111/9nammon.git && cd 9nammon
export LCA_HOST=0.0.0.0 LCA_TOKEN="ตั้งรหัสลับยาว ๆ"
python3 server.py . --port 8420
```

## เส้นทาง C — Render + cloud LLM
ตั้ง env บน Render: `LCA_HOST=0.0.0.0`, `LCA_TOKEN=<secret>`, `MODEL_BACKEND=openai`,
`OPENAI_BASE_URL`, `OPENAI_API_KEY`

## จดโดเมน
| ตัวเลือก | ราคา | ได้อะไร |
|---|---|---|
| **DuckDNS** | ฟรี | subdomain `ชื่อคุณ.duckdns.org` |
| **Cloudflare + โดเมนจริง** | ~$1–12/ปี | โดเมนคงที่ + HTTPS ฟรี |

## สรุปแนะนำ
- **เริ่มวันนี้ ไม่เสียเงิน** → เส้นทาง A
- **จริงจัง ออนไลน์ 24 ชม. ฟรีถาวร** → เส้นทาง B + DuckDNS
- **โดเมนสวยคงที่** → ซื้อโดเมน ~$1–12/ปี

---

## HOSTING

# Hosting — ให้ลูกค้าใช้ LCA จริง (เจ้าของไม่ต้องเปิดเครื่องตลอด)

## 0. ความจริง 2 ข้อ
1. **บริการ 24 ชม. ต้องมีเครื่องเปิด 24 ชม.** — laptop ปิด = ลูกค้าใช้ไม่ได้ทันที → ต้องเช่า **VPS**
2. **จำนวนคนที่รับได้ = ฟังก์ชันของฮาร์ดแวร์** ไม่ใช่ของซอฟต์แวร์

## 1. รับได้กี่คน? (ตัวเลขจริง)

| เครื่อง | ความเร็ว | คนพร้อมกันจริง | เหมาะกับ |
|---|---|---|---|
| laptop i3/8GB | ~17 t/s | **1–2 คน** | ทดสอบ/เดโม |
| VPS 4GB CPU | ใกล้เคียง | **2–5 คน** | ใช้จริงกลุ่มเล็ก 24/7 |
| 1x cloud GPU | เร็วมาก | **หลายสิบคน** | ลูกค้าจริงเริ่มเยอะ |
| หลาย GPU | scale แนวนอน | **หลักร้อย–พัน** | ระดับบริษัท |

## 2. สถาปัตยกรรม

```
ลูกค้า ──HTTPS──► [ LCA web/API ] ──► [ Model backend ]
                   rate-limit+token     Ollama / cloud GPU
```

## 3. ตัวเลือก + ต้นทุน

| | เครื่อง | โมเดล | ค่าใช้จ่าย | ตรงโจทย์? |
|---|---|---|---|---|
| A | VPS 1GB + tunnel ไปเครื่องพี่ | เครื่องพี่ | ~150–250 | ❌ ต้องเปิดเครื่องตอน AI ตอบ |
| **B** ⭐ | VPS 4–8GB | 0.5b CPU | ~350–900 | ✅ |
| C | VPS 1GB + cloud GPU | จ่ายต่อ use | ~150+ | ✅ เร็วกว่า |

## 4. Runbook — deploy LCA ขึ้น VPS

```bash
sudo apt update && sudo apt install -y python3 python3-pip git
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:0.5b
git clone https://github.com/Ragam111/9nammon.git /opt/lca
cd /opt/lca && pip3 install -r requirements.txt

sudo tee /etc/systemd/system/lca.service >/dev/null <<'UNIT'
[Unit]
Description=LCA server
After=network.target
[Service]
WorkingDirectory=/opt/lca
ExecStart=/usr/bin/python3 /opt/lca/server.py /opt/lca-project --host 127.0.0.1 --port 8420 --token CHANGE_ME_SECRET
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl enable --now lca
```

**HTTPS ผ่าน Caddy:**
```bash
sudo apt install -y caddy
# /etc/caddy/Caddyfile:
# your-domain.com {
#     reverse_proxy 127.0.0.1:8420
# }
sudo systemctl reload caddy
```

## 5. Checklist ก่อนเปิดจริง
- [ ] `--token` ตั้งเป็นความลับจริง
- [ ] HTTPS ผ่าน Caddy/Cloudflare
- [ ] `config.json` / `*.db` อยู่ใน .gitignore ✅
- [ ] backup `*.db` เป็นงวด
- [ ] firewall: เปิดแค่ 80/443 (+22 ssh) ปิด 8420

## สรุป
- **เจ้าของไม่ต้องเปิดเครื่องเอง = เช่า VPS (ตัวเลือก B)**
- **เครื่อง laptop = ทดสอบ/เดโม 1–2 คนเท่านั้น**
- ขยายทีละขั้นตามลูกค้าจริง + รายได้จริง

---

## BUNDLING

# LCA Bundling — ก้อนเดียวจริงกับก้อนเดียวแบบ installer

## 2 ชนิดของ .exe

### 1. `LCA-Desktop.exe` (~10 MB) — **ก้อนเดียวจริง** ⭐

```bash
pyinstaller --onefile --windowed --name LCA-Desktop \
    --add-data "app;app" \
    --add-data "sysmanager;sysmanager" \
    --add-data "local_coder.py;." \
    lca_app.py
```

ข้อมูลเก็บที่: `%LOCALAPPDATA%\LocalCodeAssistant\data` (bind `127.0.0.1`)

### 2. `TokenLCAlimit.exe` (~12 MB) — ตัวติดตั้ง GUI

```bash
pyinstaller --onefile --windowed --name TokenLCAlimit installer_gui.py
```

## เทียบตรงๆ

| จุด | LCA-Desktop.exe | TokenLCAlimit.exe |
|-----|-----------------|-------------------|
| ก้อนเดียวจริง? | ✅ | ❌ ดาวน์โหลดเพิ่มตอนรัน |
| ต้องมี Python 3.10+? | ❌ | ✅ |
| แชตได้ทันที? | ✅ | ❌ ต้องติดตั้งก่อน |
| ใช้ CLI (`lca`)? | ❌ | ✅ |
| ใช้ server แบบ cluster? | ❌ | ✅ |

## แนวทาง recommend
- **คนทั่วไป / อยากแชตเลย** → `LCA-Desktop.exe` ⭐
- **devops / admin / รัน server สำหรับทีม** → `TokenLCAlimit.exe`

---

## INSTALLER_EXE

# LCA Desktop.exe — แอปก้อนเดียว

> ดับเบิลคลิก **`LCA-Desktop.exe`** → เปิดหน้าต่างแอป → แชตได้เลย
> ข้อมูลเก็บที่ `%LOCALAPPDATA%\LocalCodeAssistant\data` และ bind `127.0.0.1`

## 2 โหมดสมอง (เลือกที่ `/console`)
| โหมด | ต้องมีอะไร | ความเป็นส่วนตัว |
|---|---|---|
| **(ก) Cloud** | API key OpenAI-compatible | prompt วิ่งไป cloud ที่คุณตั้ง |
| **(ข) Local** | ลง **Ollama** ในเครื่อง | **ข้อมูลไม่ออกเครื่องเลย** |

## โหลด .exe จากไหน
- **ตอนนี้**: GitHub Actions → build-exe → Artifacts → `LCA-Desktop-exe`
- **หน้า Releases**: โผล่อัตโนมัติเมื่อ push tag `v*`

---

# ตัวติดตั้ง GUI — TokenLCAlimit.exe

`installer_gui.py` (Python stdlib: tkinter + urllib + zipfile)
- ดาวน์โหลดซอร์สที่ปัก commit ไว้ → ตรวจ SHA-256 → คัดลอกลงโฟลเดอร์ที่เลือก
- สร้าง `start-lca.bat`
- แถบ progress เป็น **สีเขียว** เมื่อ 100%

## วิธีที่แนะนำ: GitHub build+แปะ Release อัตโนมัติ

```bash
git tag v0.1.0
git push origin v0.1.0
```
GitHub จะ: build `TokenLCAlimit.exe` → สร้าง Release → แปะ `.exe` ไว้ให้ดาวน์โหลด

## ข้อควรรู้
- ต้องแพ็ก + ทดสอบ .exe **บนเครื่อง Windows** — ตรรกะติดตั้งเทสผ่านแล้ว
- ตัว .exe ยัง **ต้องมี Python + Ollama บนเครื่องปลายทาง**
- Windows SmartScreen อาจเตือนครั้งแรก — กด More info → Run anyway

---

## TRAY_INSTALLER

# LCA Tray Installer

## วิธีติดตั้ง (ครั้งแรก)
1. ดาวน์โหลด `TokenLCAlimit.exe`
2. ดับเบิลคลิก → หน้าต่างติดตั้งโผล่
3. ตั้งค่า: โฟลเดอร์ติดตั้ง, สร้าง Desktop icon, เริ่มใน system tray
4. กด "ติดตั้ง" → progress bar → เขียวเต็มหลอด = เสร็จ

## ควบคุมจาก tray
- **คลิกซ้าย**: เปิดหน้าต่างแอป
- **คลิกขวา**: เมนู (เปิดแอป / เปิดคอนโซล / ดู logs / ออก)

## ไฟล์ที่เกี่ยวข้อง

| ไฟล์ | หน้าที่ |
|------|-------|
| `installer_gui.py` | GUI installer |
| `lca-tray.ps1` | PowerShell script สร้าง tray icon + รัน server |
| `lca-tray.bat` | Launcher ของ `lca-tray.ps1` |
| `lca-desktop.bat` | โหมดหน้าต่างแอป (Edge --app) |
| `start-lca.bat` | โหมดเปิดเซิร์ฟเวอร์ + เบราว์เซอร์ fallback |

## ความต้องการระบบ
- Windows 10/11, Python 3.10+, Edge หรือ Chrome (optional)

## ซื่อตรง: ข้อจำกัด
- ใช้ `System.Windows.Forms.NotifyIcon` → **Windows เท่านั้น**
- Icon ใช้ `SystemIcons.Information` (built-in) ไม่ใช่ custom .ico

## Troubleshooting

**ไอคอนไม่โผล่:** เช็ค `%LOCALAPPDATA%\LocalCodeAssistant\data\lca-tray.log` ลองรัน:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File lca-tray.ps1
```

**พอร์ต 8420 ชน:** เปิด `lca-tray.ps1` แก้ `$Port = 8420` เป็นเลขอื่น
