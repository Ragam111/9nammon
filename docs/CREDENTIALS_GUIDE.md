# คู่มือรหัสและคีย์ของ LCA: เอาที่ไหน ใส่ที่ไหน

กฎ: ห้าม commit รหัสใด ๆ ลง git, ห้ามวางในแชต, เก็บต้นฉบับใน password manager
ไฟล์ที่ใส่รหัสได้: `config.json` (อยู่ใน `.gitignore` แล้ว) หรือ environment variable ของ Windows
ชื่อเมนูของเว็บผู้ให้บริการอาจเปลี่ยนได้ ถ้าไม่ตรง ให้ค้นชื่อหัวข้อในหน้า docs ของผู้ให้บริการนั้น

| รหัส | ใช้ทำอะไร | ต้องมีตอนไหน |
|---|---|---|
| `LCA_TOKEN` | ล็อกให้เฉพาะคนที่มี token เข้า API ได้เมื่อเปิดให้ LAN/อินเทอร์เน็ต | ทุกครั้งที่ bind `0.0.0.0` |
| Google OAuth Client ID + Secret | ปุ่ม "เข้าสู่ระบบด้วย Google" | เมื่อเปิด Google login |
| Cloudflare Tunnel token | เปิดให้คนนอก LAN เข้าผ่านโดเมน | เมื่อเปิดผ่านอินเทอร์เน็ต |
| Discord Webhook URL | แจ้งเตือนเข้า Discord | ไม่บังคับ |
| SMTP (Gmail App Password) | ส่งอีเมลแจ้งเตือน | ไม่บังคับ |
| API key ผู้ให้บริการโมเดล (Groq, OpenRouter, OpenAI, Gemini, Anthropic) | ใช้โมเดล cloud รับโหลดเกิน | ไม่บังคับ (ค่าเริ่มต้นใช้ Ollama ในเครื่อง ฟรี) |

## 1. LCA_TOKEN (สร้างเองในเครื่อง ไม่ต้องสมัครที่ไหน)
```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
เก็บค่าที่ได้ใน password manager แล้วตั้งก่อนเปิดเซิร์ฟเวอร์:
```powershell
$env:LCA_TOKEN = "<ค่าที่ได้>"
python server.py "$env:USERPROFILE" --host 0.0.0.0 --port 8420
```
ใช้ค่าเดียวกันทั้ง PC และโน้ตบุ๊ก (ดู `docs/RUN_TWO_NODES.md`) ส่งให้ลูกค้าแบบส่วนตัวเท่านั้น

## 2. Google OAuth Client ID และ Secret
1. เข้า https://console.cloud.google.com/ แล้วสร้าง Project ใหม่ (เช่น `lca`)
2. เมนู **APIs & Services → OAuth consent screen**: เลือก External, ใส่ชื่อแอปและอีเมล, เพิ่ม scope `openid`, `email`, `profile`
3. เมนู **APIs & Services → Credentials → Create Credentials → OAuth client ID**: ชนิด **Web application**
4. **Authorized redirect URIs**: ใส่ `http://localhost:<พอร์ตเซิร์ฟเวอร์>/auth/google/callback` แล้วใส่ใน `config.json`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (ค่าเดียวกับ redirect URI)
5. กด Create แล้วคัดลอก **Client ID** และ **Client secret**
ข้อจำกัด: Google ไม่รับ IP ใน LAN (เช่น `192.168.2.44`) เป็น redirect URI ถ้าจะให้ลูกค้าคนอื่น login ด้วย Google ต้องมีโดเมนจริงพร้อม HTTPS (ข้อ 3)

## 3. Cloudflare Tunnel (เปิดผ่านอินเทอร์เน็ต ฟรี ต้องมีโดเมน)
1. มีโดเมนที่ย้าย DNS มาไว้ที่ Cloudflare แล้ว (สมัครที่ https://dash.cloudflare.com/)
2. เมนู **Zero Trust → Networks → Tunnels → Create a tunnel** เลือก Cloudflared ตั้งชื่อ (เช่น `lca`)
3. หน้าถัดไปจะแสดงคำสั่ง `cloudflared service install <token>` ค่า `<token>` คือ Tunnel token ห้ามเผยแพร่
4. ติดตั้ง cloudflared บน PC และโน้ตบุ๊ก แล้วรันคำสั่งนั้นบนทั้งสองเครื่อง (เป็น replica ของ tunnel เดียวกัน)
5. แท็บ **Public Hostname**: ชี้ `lca.<โดเมนของคุณ>` ไปที่ `http://localhost:8420`
6. ตั้งให้ LCA เชื่อ IP จาก tunnel: `$env:LCA_TRUST_PROXY = "1"` (มีแล้วตั้งแต่ commit `4cd3631`)
ห้ามใช้ Quick Tunnel (`trycloudflare.com`) กับลูกค้า เพราะ URL เปลี่ยนทุกครั้งและไม่รองรับ SSE
ก่อนเปิดจริงต้องตัดสินเรื่อง `cloud_tunnel` ใน `server.py` และทำงานกะ 2 ให้ครบ

## 4. Discord Webhook URL (ไม่บังคับ)
Discord → เซิร์ฟเวอร์ของคุณ → **Server Settings → Integrations → Webhooks → New Webhook** → เลือกห้อง → **Copy Webhook URL**
ใส่ `config.json` คีย์ `DISCORD_WEBHOOK_URL`
ทดสอบ: `POST /api/admin/notify` ด้วย body `{"event":"test","text":"hello"}` (สิทธิ์ ADMIN)

## 5. SMTP ด้วย Gmail App Password (ไม่บังคับ)
1. เปิด 2-Step Verification ที่ https://myaccount.google.com/security
2. ไปที่ https://myaccount.google.com/apppasswords สร้าง App password (16 ตัวอักษร)
3. ใส่ `config.json`: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER=<อีเมล>`, `SMTP_PASS=<app password>`, `SMTP_FROM`, `SMTP_TO`
อย่าใช้รหัสผ่านหลักของ Gmail

## 6. API key ผู้ให้บริการโมเดล (ไม่บังคับ มีค่าใช้จ่ายตามการใช้)
| ผู้ให้บริการ | หน้าสร้างคีย์ | ตัวแปรใน LCA |
|---|---|---|
| Groq | https://console.groq.com/keys | ใช้แบบ OpenAI-compatible: `OPENAI_BASE_URL=https://api.groq.com/openai/v1` + คีย์ |
| OpenRouter | https://openrouter.ai/keys | `OPENAI_BASE_URL=https://openrouter.ai/api/v1` + คีย์ |
| OpenAI | https://platform.openai.com/api-keys | ตามช่องในหน้า `/console` |
| Google Gemini | https://aistudio.google.com/apikey | ตามช่องในหน้า `/console` |
| Anthropic | https://console.anthropic.com/settings/keys | ตามช่องในหน้า `/console` |
ใส่คีย์ผ่านหน้า `/console` (สิทธิ์ ADMIN) ระบบเก็บไว้ฝั่งเซิร์ฟเวอร์และแสดงแค่ 4 ตัวท้าย
ตั้งวงเงินสูงสุด (spending limit) ในหน้าบัญชีของผู้ให้บริการทุกเจ้า กันค่าใช้จ่ายพุ่งถ้าโดนใช้ผิด

## ถ้ารหัสหลุด
1. ยกเลิก/สร้างใหม่ที่หน้าเดียวกับที่สร้าง (Google: Credentials → Reset secret, Cloudflare: Tunnel → Refresh token, Discord: Delete webhook, ผู้ให้บริการโมเดล: Revoke key)
2. อัปเดตค่าใหม่ใน `config.json` หรือ environment ทั้งสองเครื่อง แล้วรีสตาร์ตเซิร์ฟเวอร์
3. `LCA_TOKEN` หลุด: สร้างใหม่ตามข้อ 1 แล้วแจ้งลูกค้าใหม่
