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

> ต้องใช้ `LCA_HOST=0.0.0.0` + `LCA_TOKEN` แบบด้านบน (server รับ Host ที่ไม่มีพอร์ตจาก tunnel).
> ถ้ารันแบบ `127.0.0.1` ที่ไม่ตั้ง token แล้วต่อ tunnel → ชื่อ tunnel โดน 403 เว้นแต่ใส่ใน
> `LCA_ALLOWED_HOSTS=xxxx.trycloudflare.com` — และหน้าเว็บที่เปิดผ่านชื่อนั้นจะ **ไม่ได้** session token
> อัตโนมัติ (ต้องวาง token/API key เอง) กันคนนอกได้สิทธิ์ CEO.

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

**Host/Origin หลัง proxy HTTPS (2026-11-03):** โฮสต์พวกนี้ส่ง `Host: <ชื่อแอป>.onrender.com` /
`<ชื่อ>.hf.space` (ไม่มีพอร์ต) และเบราว์เซอร์ส่ง `Origin: https://<ชื่อเดียวกัน>` (พอร์ต 443)
ขณะที่ server ฟังพอร์ต `$PORT`. เมื่อ `LCA_HOST=0.0.0.0` (บังคับ `LCA_TOKEN` แล้ว) server
รับ Host ที่ไม่มีพอร์ต / `:443` / `:80` / พอร์ตที่ฟัง และเทียบ Origin กับชื่อใน Host โดยไม่สนพอร์ต
— ใช้ได้เลยไม่ต้องตั้งอะไรเพิ่ม. Origin ของเว็บอื่นยังโดน 403. ถ้าอยากล็อกชื่อให้แคบลง
หรือใช้ชื่อเฉพาะ ตั้ง `LCA_ALLOWED_HOSTS` (ดูตารางล่าง). หน้า HTML ส่ง
`X-Frame-Options: DENY` + `Content-Security-Policy: frame-ancestors 'none'` (ห้ามฝังใน iframe).

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
| `LCA_ALLOWED_HOSTS` | ชื่อ host เพิ่มเติมที่รับใน `Host`/`Origin` คั่นด้วยจุลภาค เช่น `lca.example.com,xxxx.trycloudflare.com` (ไม่สนพอร์ต; ชื่อ loopback ไม่ถูกคลาย; ไม่แจก session token ให้ชื่อเหล่านี้) | ไม่มี |
| `MODEL_BACKEND` | `ollama` \| `openai` | ollama |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | ปลายทาง cloud LLM | — |

> **ความปลอดภัย (Rule 12):** server จะ **ปฏิเสธ** ถ้า bind ออกนอก `127.0.0.1`
> โดยไม่มี token — กันคนทั้งอินเทอร์เน็ตสั่งแก้ไฟล์บนเครื่อง. ตั้ง `LCA_TOKEN` เสมอตอน deploy.
