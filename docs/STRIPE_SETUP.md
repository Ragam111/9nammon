# ตั้งค่า Stripe Checkout (บัตร + PromptPay) — สำหรับเจ้าของระบบ

LCA ใช้ **Stripe hosted Checkout**: ลูกค้ากรอกบัตรบนหน้าของ Stripe เท่านั้น ข้อมูลบัตรไม่ผ่านเซิร์ฟเวอร์ LCA (PCI SAQ-A)
ถ้ายังไม่ตั้งค่า ปุ่ม Stripe จะถูกซ่อน และ `/api/pay/stripe/*` ตอบ 503 — PromptPay QR เดิมใช้ได้ตามปกติ

> ห้ามส่ง key ใด ๆ ในแชต/issue/commit — ใส่เองใน `config.json` บนเครื่อง server เท่านั้น

## 1. เริ่มจาก test mode
1. สมัคร/เข้าสู่ระบบ Stripe Dashboard → เปิด **Test mode**
2. เปิดใช้ PromptPay: Settings → Payment methods → PromptPay (บัญชีต้องเป็นประเทศไทย, สกุล THB)
3. Developers → API keys → คัดลอก **Secret key** (`sk_test_...`)

## 2. ใส่ใน config.json (หรือ env var ชื่อเดียวกัน)
```json
{
  "STRIPE_SECRET_KEY": "sk_test_...",
  "STRIPE_WEBHOOK_SECRET": "whsec_...",
  "STRIPE_MODE": "test",
  "PUBLIC_BASE_URL": "https://โดเมนของคุณ"
}
```
- `STRIPE_MODE` ค่าเริ่มต้น `test` — key `sk_live_` จะถูก **ปฏิเสธ** จนกว่าจะตั้ง `STRIPE_MODE` เป็น `live`
- `PUBLIC_BASE_URL` ใช้สร้าง success/cancel URL — **ไม่ใช้ Host ของ request เด็ดขาด**
  - โหมด `live`: ต้องเป็น `https://...`; ไม่ตั้ง/ไม่ใช่ https = checkout ตอบ 503 (`public_base_url_required`)
  - โหมด `test`: `https://...` หรือ `http://127.0.0.1|localhost|[::1]:<port>`; ไม่ตั้ง = `http://127.0.0.1:<พอร์ต server>`
- rate limit ของ checkout (5 ครั้ง/นาที/ผู้ใช้) เก็บในหน่วยความจำ — **รีเซ็ตเมื่อรีสตาร์ท server** (และไม่แชร์ข้าม process)
- ราคามาจากตารางแพ็กเกจ (`PLANS`) ฝั่ง server เท่านั้น

## 3. Webhook
Endpoint: `POST <โดเมน>/api/pay/stripe/webhook`
Events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
`checkout.session.async_payment_failed`, `checkout.session.expired`

**ข้อจำกัดตอนนี้:** server เปิดเฉพาะ LAN — Stripe ต้องเรียก webhook ผ่าน **HTTPS สาธารณะ** จึงยังรับ webhook จริงไม่ได้
จนกว่าเจ้าของจะตัดสินใจเรื่อง tunnel/โดเมน (เช่น Cloudflare Tunnel) ระหว่างนี้ทดสอบในเครื่องด้วย Stripe CLI:

```bash
stripe login
stripe listen --forward-to http://127.0.0.1:<port>/api/pay/stripe/webhook
# CLI พิมพ์ whsec_... ออกมา → ใส่เป็น STRIPE_WEBHOOK_SECRET ใน config.json
stripe trigger checkout.session.completed   # ทดสอบ (order จริงต้องสร้างจากหน้า /plans)
```
บัตรทดสอบ: `4242 4242 4242 4242` วันหมดอายุอนาคต CVC ใดก็ได้

เมื่อมีโดเมน HTTPS แล้ว: Dashboard → Developers → Webhooks → Add endpoint → คัดลอก Signing secret ใหม่มาใส่

## 4. พฤติกรรม
- ชำระสำเร็จ (ยอด + สกุลเงิน THB ตรงกับ order) → แพ็กเกจเปิดทันที 30 วัน
- ยอด/สกุลเงินไม่ตรง → ไม่เปิดแพ็กเกจ สถานะ `review` ให้ผู้ดูแลตรวจใน Dashboard
- event ซ้ำ/replay → ไม่ทำซ้ำ (เก็บ event id ในตาราง `stripe_events`)
- ลายเซ็นผิด/เกิน 5 นาที → 400
- คืนเงิน: ผู้ดูแลกด "คืนเงินผ่าน Stripe" ในหน้า /plans → เรียก Stripe Refunds API; PromptPay คืนเงินเองนอกระบบเหมือนเดิม

## 5. ขึ้น live
ทดสอบครบใน test mode ก่อน → สลับ key เป็น `sk_live_...` + `STRIPE_MODE: "live"` + webhook secret ของ endpoint live
