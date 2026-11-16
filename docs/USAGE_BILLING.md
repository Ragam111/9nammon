# LCA — Usage Metering & Billing (ข้อเสนอ / proposal)

สถานะ: **บันทึก + สรุปเท่านั้น ยังไม่เชื่อม payment gateway จริง** (Item H)
ตัวเลขราคาเป็นค่าตั้งต้นสำหรับประมาณการ ไม่ใช่การเรียกเก็บเงินจริง

## ทำไมต้องมี metering แยกจากโควตา
`org_store` เก็บแค่ตัวนับรายวัน (`used_today` / `usage_date`) ที่ **รีเซ็ตทุกวัน** —
ใช้กันคนยิงถล่ม (rate limit) ได้ แต่ดูย้อนหลังไม่ได้ว่าเดือนนี้ใครใช้เท่าไร / tier paid
สร้างค่าใช้จ่ายรวมเท่าไร. `usage_store` (SQLite, append-only) จึงบันทึกทุก event ที่สำเร็จ
เพื่อ query ย้อนหลัง + สรุปต่อ key / ต่อ tier

## โมเดลข้อมูล (`app/usage_store.py`, ตาราง `usage`)
| คอลัมน์ | ความหมาย |
|---------|----------|
| `used_at` | เวลา (ISO) ที่ใช้ |
| `key_id` | API key ที่ใช้ (จาก org_store) |
| `owner` | username เจ้าของ key |
| `tier` | free / paid ณ ตอนใช้ |
| `endpoint` | จุดที่ใช้ (ตอนนี้ = `chat`) |
| `units` | จำนวนหน่วย (ตอนนี้ 1 request = 1 unit) |

บันทึกที่ไหน: `server.py` → `_handle_chat` หลังตอบสำเร็จ + หักโควตา (เฉพาะ identity ที่มี key_id;
master/local ไม่นับ). ถ้า DB ล้ม (locked/disk เต็ม) จะ log warning แล้วข้าม — **ไม่ทำ response ผู้ใช้พัง**

## ราคา (ประมาณการ — แก้ได้ที่ `TIER_UNIT_PRICE`)
| tier | ราคา/หน่วย (บาท) | หมายเหตุ |
|------|------------------|----------|
| free | 0.00 | ฟรี จำกัดโควตารายวัน (ดู `org_store.TIER_DAILY_LIMIT`) |
| paid | 0.10 | ไม่จำกัดโควตารายวัน คิดตามการใช้จริง |

`summary()` คืน `total_units`, `total_cost` (= units × ราคา/หน่วย), แยก `by_tier` และ `by_key`

## Endpoint (gate ADMIN)
- `GET /api/admin/usage?key_id=` — รายการ event ล่าสุดก่อน (กรองตาม key ได้)
- `GET /api/admin/usage/summary` — สรุป units + cost ต่อ tier/ต่อ key

## นอกขอบเขต (ยังไม่ทำ — ต้อง user ตัดสินใจก่อน)
- เชื่อม payment gateway จริง (Stripe/PromptPay/บัตรเครดิต) — ต้องเลือกผู้ให้บริการ + ความปลอดภัยระดับการเงิน
- ออกใบแจ้งหนี้/ตัดเงินอัตโนมัติ
- แปลง usage → finance_ledger entry อัตโนมัติ (ตอนนี้แยกกัน: usage = เมตริกการใช้, finance = บันทึกเงินจริงที่ user กรอก)
