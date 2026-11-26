# คู่มือเปิดเซิร์ฟเวอร์ LCA (ฉบับเดียวจบ)

สำหรับเจ้าของระบบ อ่านจากบนลงล่างครั้งแรก ครั้งต่อไปดูแค่ข้อ 3 และข้อ 9

---

## 1. ของที่ต้องมี
- Windows 10/11, RAM 8 GB ขึ้นไป
- Ollama (https://ollama.com) เปิดแอปค้างไว้ ตั้งให้เปิดเองตอน login
- โมเดลอย่างน้อย 1 ตัว:
  ```powershell
  ollama pull qwen2.5-coder:0.5b
  ```
- ไฟล์ 2 ตัวจาก GitHub Actions (build ล่าสุด):
  - `lcalocalai.exe` สำหรับลูกค้า (หน้าแชต / API)
  - `LCA-Admin.exe` สำหรับคุณคนเดียว (หลังบ้าน)

## 2. ตั้งค่าครั้งแรก (`config.json`)
วางไฟล์ `config.json` ไว้ข้าง exe (หรือในโฟลเดอร์โปรเจกต์ถ้ารันจาก source) ใส่เฉพาะค่าที่ใช้
**ห้ามส่งค่าเหล่านี้ในแชตหรือ commit ขึ้น git**

```json
{
  "LCA_TOKEN": "<สุ่มเอง ดูข้อ 2.1>",
  "BUSINESS_NAME": "<ชื่อธุรกิจ ตรงกับที่ให้ Stripe>",
  "CONTACT_EMAIL": "<อีเมลติดต่อลูกค้า>",
  "PROMPTPAY_ID": "<เบอร์มือถือหรือเลขบัตรที่ผูกพร้อมเพย์>",
  "GOOGLE_CLIENT_ID": "....apps.googleusercontent.com",
  "GOOGLE_CLIENT_SECRET": "GOCSPX-....",
  "GOOGLE_REDIRECT_URI": "http://localhost:8420/auth/google/callback",
  "STRIPE_SECRET_KEY": "sk_test_....",
  "STRIPE_WEBHOOK_SECRET": "whsec_....",
  "STRIPE_MODE": "test",
  "PUBLIC_BASE_URL": ""
}
```

### 2.1 สร้าง LCA_TOKEN
```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
ใช้ค่าเดียวกันทั้งสองเครื่อง (ถ้ามีเครื่องที่ 2)

### 2.2 ค่าไหนไม่ใส่ได้
| ค่า | ถ้าไม่ใส่ |
|---|---|
| GOOGLE_* | ปุ่ม Google ซ่อน ล็อกอินด้วยรหัสผ่านได้ปกติ |
| STRIPE_* | ปุ่มบัตร/Stripe ซ่อน ใช้ QR พร้อมเพย์อย่างเดียว |
| PROMPTPAY_ID | สร้าง QR ไม่ได้ |
| BUSINESS_NAME / CONTACT_EMAIL | หน้า terms/privacy/refund ขึ้น “[ยังไม่ได้ตั้งค่า]” |

## 3. เปิดเซิร์ฟเวอร์ (ทุกวัน)
1. เปิด Ollama
2. ดับเบิลคลิก `lcalocalai.exe` → หน้าเว็บลูกค้าเปิดที่ `http://127.0.0.1:8420`
3. ถ้าจะให้เครื่องอื่นใน LAN เข้า (รันจาก source):
   ```powershell
   $env:LCA_TOKEN = "<ค่าจาก config>"
   python server.py "$env:USERPROFILE" --host 0.0.0.0 --port 8420
   ```
   ลูกค้าใน LAN เข้า `http://<IP เครื่องนี้>:8420` (ดู IP ด้วย `ipconfig`)
4. ตรวจว่าพร้อม (ต้องได้ 200):
   ```powershell
   curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8420/api/health
   ```

ถ้าพอร์ต 8420 ไม่ว่าง เซิร์ฟเวอร์ย้ายไปพอร์ตว่างเองและพิมพ์พอร์ตใหม่ออกมา

## 4. เปิดหลังบ้าน (LCA-Admin)
1. ดับเบิลคลิก `LCA-Admin.exe` → เปิดที่ `http://127.0.0.1:8430/admin`
2. เข้าได้จากเครื่องนี้เท่านั้น และต้องเป็นบัญชี CEO
3. ใช้ฐานข้อมูลเดียวกับแอปลูกค้า

| เมนู | ใช้ทำอะไร |
|---|---|
| Overview | สถานะเครื่อง, Ollama, RAM |
| Users | สร้าง/ปิดบัญชี, กำหนดสิทธิ์ |
| API keys | สร้าง (เห็นค่าเต็มครั้งเดียว) / ยกเลิกคีย์ |
| Plans & Orders | ยืนยันยอดโอนพร้อมเพย์, ดูออเดอร์ Stripe |
| Refunds | คืนเงิน (Stripe คืนอัตโนมัติ, พร้อมเพย์โอนคืนเอง) |
| Models | ติดตั้งโมเดล |
| Database | ดูข้อมูลแบบอ่านอย่างเดียว ค่าลับถูกปิด |
| Nodes | ควบคุมเครื่องที่ 2 |

ถ้าเปิด Cloudflare tunnel อยู่ หลังบ้านจะปฏิเสธคำขอ (403) โดยตั้งใจ

## 5. บัญชีแรก (CEO)
ครั้งแรกที่ยังไม่มีผู้ใช้ ระบบจะให้สร้าง CEO โดยต้องใส่ `LCA_TOKEN`
CEO คนเดียวปิดบัญชีตัวเองไม่ได้ (กันล็อกตัวเองออก)

## 6. รับเงิน
### 6.1 พร้อมเพย์ (ใช้ได้ทันที)
ลูกค้าเลือกแผนที่ `/plans` → สแกน QR → คุณเช็กยอดในแอปธนาคาร → กดยืนยันใน LCA-Admin

### 6.2 Stripe (บัตร + พร้อมเพย์อัตโนมัติ)
1. ทำ onboarding ใน Stripe ให้เสร็จ (KYC/บัญชีธนาคาร ทำเอง)
2. ใส่ test key ใน `config.json` แล้วเปิด PromptPay ที่ Stripe → Settings → Payment methods
3. ทดสอบในเครื่อง (ต้องมี Stripe CLI):
   ```powershell
   stripe listen --forward-to http://127.0.0.1:8420/api/pay/stripe/webhook
   ```
   ใช้ `whsec_` ที่ CLI พิมพ์ออกมา จ่ายด้วยบัตรทดสอบ 4242 4242 4242 4242
4. รับเงินจริง: ต้องมี HTTPS สาธารณะ (โดเมน หรือ tunnel) ตั้ง `PUBLIC_BASE_URL=https://...` และ `STRIPE_MODE=live` กับ `sk_live_` ดู `docs/STRIPE_SETUP.md`, `docs/PUBLIC_URL_RESEARCH.md`

## 7. Google login
สร้าง OAuth Client ที่ https://console.cloud.google.com/ (Web application, redirect URI ตรงกับ `GOOGLE_REDIRECT_URI`) แล้วใส่ค่าใน `config.json` ดู `docs/CREDENTIALS_GUIDE.md`
ผู้ใช้ฟรีได้ 1,000,000 token ต่อเดือน

## 8. API แบบ OpenAI (ให้ลูกค้าเขียนโปรแกรมเรียก)
```powershell
curl.exe http://127.0.0.1:8420/v1/models -H "Authorization: Bearer lca_xxx"
```
คีย์ `lca_...` สร้างที่ API keys ตัวอย่างโค้ดอยู่ที่หน้า `/models`

## 9. ปัญหาที่เจอบ่อย
| อาการ | ทำอย่างไร |
|---|---|
| หน้าแชตขึ้น Ollama ไม่ทำงาน | เปิดแอป Ollama แล้วรีเฟรช |
| เครื่องอื่นเข้าไม่ได้ | เช็กว่าเปิดด้วย `--host 0.0.0.0` และตั้ง `LCA_TOKEN`; เช็ก firewall พอร์ต 8420; IP เครื่องเปลี่ยน → ตั้ง DHCP reservation ที่เราเตอร์ |
| ช้า / ค้าง | RAM ไม่พอ ใช้ `qwen2.5-coder:0.5b`; รับคนพร้อมกันได้ราว 9–13 คนต่อเครื่อง |
| อัปเดต exe แล้วลบไฟล์เก่าไม่ได้ | ปิดโปรแกรมตัวเก่าก่อน (ไอคอนถาด หรือ Task Manager) |
| หน้าเว็บยังเป็นแบบเก่า | กด Ctrl+F5 (PWA แคช) |
| ปุ่ม Google / Stripe ไม่ขึ้น | ยังไม่ได้ใส่ค่าใน `config.json` หรือยังไม่รีสตาร์ต |
| หลังบ้าน 403 | เปิดจากเครื่องอื่น หรือเปิด tunnel อยู่ ต้องเปิดจากเครื่องนี้ |

## 10. เครื่องที่ 2 (ถ้ามี)
ต่อสาย LAN ตรง แล้วทำตาม `docs/REMOTE_NODE.md` ส่วนที่ 1 (ครั้งเดียว) หลังจากนั้นสั่งจากเครื่องนี้:
```powershell
python scripts\node_ctl.py status
python scripts\node_ctl.py deploy
python scripts\node_ctl.py restart
```

## 11. สำรองข้อมูล
ข้อมูลทั้งหมดอยู่ในไฟล์ SQLite `data/lca.db` (และ `-wal`) ในโฟลเดอร์ข้อมูล ปิดเซิร์ฟเวอร์ก่อนแล้วคัดลอกทั้งโฟลเดอร์ `data` ไปเก็บ อย่าคัดลอกข้ามเครื่องขณะเซิร์ฟเวอร์รัน

## 12. ก่อนเปิดขายจริง (เช็กลิสต์)
- [ ] อ่านและแก้หน้า `/terms`, `/privacy`, `/refund` (เป็นฉบับร่าง)
- [ ] ใส่ `BUSINESS_NAME`, `CONTACT_EMAIL`, `PROMPTPAY_ID`
- [ ] ทดลองซื้อแผนด้วยพร้อมเพย์ 1 ครั้งและยืนยันใน LCA-Admin
- [ ] สร้าง API key ทดสอบ เรียก `/v1/models` ได้ แล้วยกเลิกแล้วเรียกไม่ได้
- [ ] สำรอง `data/` ก่อนเปิด
