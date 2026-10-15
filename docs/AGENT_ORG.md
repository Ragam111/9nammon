# LCA — Agent Organization (องค์กร AI 10 บทบาท)

Design doc (ยังไม่ implement ครบ) — วางสถาปัตยกรรม "องค์กรพนักงาน AI 10 คน" ให้
autopilot สร้างทีละชิ้นบนของที่มีอยู่แล้ว ไม่ปล่อยสร้างมั่ว

สไตล์ 9arm: เริ่มจาก simple, ต่อยอดจากของจริงที่มี (org RBAC + job queue + ledger ที่
build ไปแล้ว), บอก tradeoff ตรง ๆ, แยก "ทำได้จาก cloud" กับ "ต้องตั้งค่าฝั่ง user"

## หลักคิด: อย่าสร้าง runtime หลาย agent ทันที
"พนักงาน 10 คน" ที่ยั่งยืน = **substrate ประสานงาน** ก่อน ไม่ใช่โยน 10 LLM วิ่งพร้อมกัน
(เผาเงิน + คุมไม่ได้). เรามีชิ้นส่วน substrate อยู่แล้ว:
- **org_store** (RBAC: CEO/Admin/User) → "ใครเป็นใคร มีสิทธิ์อะไร"
- **job_queue** (SQLite, claim atomic) → "task board" ที่ agent หยิบงานไปทำ
- **finance_ledger / usage ledger** (กำลังสร้าง) → บันทึกเงิน/การใช้งาน
- **sysmanager** → รู้ว่าเครื่องไหวไหม (8GB RAM)

องค์กร 10 บทบาทจึงเป็น **layer บาง ๆ บน substrate นี้**: แต่ละบทบาท = ชุดสิทธิ์ +
ประเภทงานในคิวที่รับผิดชอบ + ช่องแจ้งเตือน

## 10 บทบาท (map กับโมดูลจริง)
| # | บทบาท | รับผิดชอบ | map กับโค้ด |
|---|-------|----------|-------------|
| 1 | **CEO** (คน=user) | อนุมัติ, ตัดสินใจเงิน/ทิศทาง, merge | role CEO (org_store) |
| 2 | **COO / Coordinator** | แจกงานเข้า job_queue, ส่งแจ้งเตือน, สรุปรายงาน | job_queue + notifier |
| 3 | **Architect/CTO** | review design, ADR | docs/ + code-review |
| 4 | **Backend Engineer** | server.py / API / endpoint | job type `backend` |
| 5 | **Frontend Engineer** | index.html / dev.html / UX | job type `frontend` |
| 6 | **DevOps/Infra** | CI, deploy, sysmanager/metrics | job type `infra` |
| 7 | **QA/Tester** | unittest, หาบั๊ก, เปิดใช้จริง | job type `qa` |
| 8 | **Security Officer** | audit, rate-limit, secret | job type `security` |
| 9 | **Data/DB Engineer** | SQLite layer, history/log | job type `data` |
| 10 | **Finance/Accounting** | finance_ledger, usage/billing | job type `finance` |

> บทบาท 3–10 ตอนแรกไม่ต้องเป็น "LLM แยกตัว" — เป็น **คิวงานแยกประเภท + สิทธิ์** ก่อน
> คนหรือ autopilot ตัวเดียวก็หยิบงานตามประเภทได้ พอ substrate นิ่งค่อยต่อ LLM worker จริง

## การสื่อสาร (ตามที่ user เลือก)
- **Discord group** — แจ้งเตือนเหตุการณ์ (งานใหม่, เสร็จ, bug, เงินเข้า/รออนุมัติ) ผ่าน **Incoming Webhook**
- **Email (ทางเดียว)** — สรุป/แจ้งเตือนสำคัญ ส่งออกอย่างเดียว (ไม่รับเข้า)

### โมดูลที่จะสร้าง: `app/notifier.py`
- `notify(event, text, channels=("discord","email"))` — stdlib (`urllib` สำหรับ Discord webhook, `smtplib` สำหรับ email)
- อ่าน config จาก `config_manager` (Rule 23: webhook URL / SMTP creds อยู่ใน config.json gitignored)
- ถ้าไม่มี config → log แล้วข้ามเงียบ ๆ (ไม่ crash) — ทดสอบได้ด้วย mock

> ⚠️ **ต้องตั้งค่าฝั่ง user ก่อนใช้จริง** (ผมสร้างโค้ด + stub ได้ แต่เชื่อมจริงไม่ได้):
> - Discord: สร้าง Incoming Webhook ในเซิร์ฟเวอร์ Discord → เอา URL ใส่ `config.json` (`DISCORD_WEBHOOK_URL`)
> - Email: ใส่ SMTP host/user/pass (เช่น Gmail App Password) ใน `config.json`

## การเงิน (ตามเคสจริงของ user)
- **บันทึกเท่านั้น ไม่โอนจริง** (Item I finance_ledger)
- เคส "เบิก 1500 รอหัวหน้าโอน" = record: `{amount:1500, direction:in, status:pending, note:"เบิก - รอหัวหน้าโอน"}` → เปลี่ยนเป็น `received` เมื่อได้จริง → notifier ยิง Discord
- ธนาคาร (กสิกร) / บัตรเครดิต = **ข้อมูลอ้างอิงที่ user กรอกเอง** ระบบไม่เชื่อม bank API จริง (ต้องใบอนุญาต + ความปลอดภัยระดับสถาบันการเงิน — นอกขอบเขต)

## Flow ตัวอย่าง (เบิกเงิน)
```
CEO/Coordinator สร้าง finance record (pending)
        │  notifier → Discord: "💰 รออนุมัติ: เบิก 1500"
        ▼
หัวหน้าโอนจริง (นอกระบบ) → user กด mark "received"
        │  notifier → Discord: "✅ รับเงินแล้ว 1500"
        ▼
ledger อัปเดต + สรุปยอดใน dev dashboard
```

## Build phases (ให้ autopilot ไล่)
1. ✅ substrate: org RBAC, job_queue (done); finance_ledger, DB layer (กำลังทำ)
2. `app/notifier.py` — Discord webhook + email (stdlib, config-driven, mock-tested)
3. job_queue: เพิ่ม field `role`/`type` + endpoint filter ตามบทบาท
4. seed 10 บทบาทเป็น role/permission preset + dev dashboard แสดงบอร์ดงานตามบทบาท
5. (ภายหลัง, ต้องออกแบบเพิ่ม) ต่อ LLM worker จริงให้แต่ละบทบาทหยิบงานทำอัตโนมัติ — เฟสนี้คือ "หลาย agent จริง" ต้องคุย cost/limit ก่อน

## นอกขอบเขต (ไม่ทำ auto)
- เชื่อม bank API จริง / โอนเงินจริง
- ควบคุมเดสก์ท็อป user
- รัน 10 LLM พร้อมกันแบบไม่มี budget guard (เฟส 5 ต้องออกแบบ cost ก่อน)
