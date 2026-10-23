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
ทดสอบ login + ใช้งานจริง LLM รันบนเครื่องเรา ฟรี 100%.

> ทางเลือก tunnel อื่น: `ngrok http 8420` (ฟรี แต่ต้องสมัคร).

---

## ทางที่ 2 — ออนไลน์ตลอด 24 ชม. (ฟรี)

Deploy web/API ขึ้นโฮสต์ฟรี แล้ว **ชี้ LLM ไป cloud** (เครื่องฟรีไม่รัน Ollama เอง):

### 2a. Hugging Face Spaces / Render (ฟรี)
มี `Dockerfile` ให้แล้ว — โฮสต์พวกนี้ build เองจาก repo:

ตั้ง environment variables บนโฮสต์:
```
LCA_HOST   = 0.0.0.0
LCA_TOKEN  = <รหัสลับ>
MODEL_BACKEND  = openai
OPENAI_BASE_URL = https://<cloud-llm>/v1     # เช่น TOKEN ME, vLLM, ฯลฯ
OPENAI_API_KEY  = <key>
```
(`$PORT` โฮสต์ฉีดให้เอง — `server.py` อ่านอัตโนมัติ)

### 2b. Oracle Cloud Always Free (รัน Ollama ได้จริง)
VM ฟรีถาวร: ARM Ampere **4 core / 24GB RAM** — แรงพอรัน Ollama + โมเดลเองได้
(ต่างจากโฮสต์ฟรีอื่นที่ RAM น้อย). ลง Ollama + รัน LCA ปกติ, ตั้ง `LCA_TOKEN`,
เปิด port ใน security list.

---

## Docker (รันที่ไหนก็ได้)

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
| `MODEL_BACKEND` | `ollama` \| `openai` | ollama |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | ปลายทาง cloud LLM | — |

> **ความปลอดภัย (Rule 12):** server จะ **ปฏิเสธ** ถ้า bind ออกนอก `127.0.0.1`
> โดยไม่มี token — กันคนทั้งอินเทอร์เน็ตสั่งแก้ไฟล์บนเครื่อง. ตั้ง `LCA_TOKEN` เสมอตอน deploy.
