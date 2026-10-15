# LCA (9nammon) — Roadmap / TODO

Source of truth เดียวสำหรับงานพัฒนา LCA ทั้ง user และ autopilot ใช้ไฟล์นี้ร่วมกัน
สไตล์ทีม: **stdlib ล้วน, unittest (ไม่ใช่ pytest), ทุกการเปลี่ยนผ่าน branch → PR → CI → merge, ไม่ขายฝัน**

อัปเดตล่าสุด: 2026-10-15

## ✅ เสร็จแล้ว (merged เข้า main)
| # | งาน | PR |
|---|-----|-----|
| 1 | Phase A — Org system (CEO/Admin/User RBAC + API key free/paid + quota) + ซ่อม repo (กู้ app/) | #1 |
| 2 | GitHub Actions CI (รัน unittest ทุก push/PR) | #2 |
| 3 | Todo delete (route + ปุ่ม UI) | #3 |
| 4 | System basics — sysinfo (CPU/RAM/storage/GPU detect, แยก integrated/compute) | #4 |
| 5 | Dev view — `/dev` dashboard + `/api/sysinfo` (gate ADMIN) | #5 |

สถานะ main: unittest 53 เคสผ่าน, CI เขียวทุก PR

## 🔜 กำลังทำ / คิว (autopilot ไล่อัตโนมัติ)
| ลำดับ | งาน | หมายเหตุ |
|------|-----|---------|
| B / Phase 2 | Bottleneck analyzer + `/api/metrics` (เชื่อม sysmanager monitor เข้า LCA, รู้จัก Ollama RAM/swap) | scheduled ~ตี 1 ไทย |
| D | Job queue (server คิวงาน) — stdlib + SQLite | |
| E | Database layer — SQLite (history/log, query ย้อนหลัง) | |
| H | Paid serving + usage metering — นับ usage/key ลง SQLite + สรุปค่าใช้จ่ายต่อ tier | **ledger เท่านั้น** — payment จริงรอ decision |
| F | WebUI/GUI/UX polish — loading/error state, mobile responsive | |
| G | Security hardening — gate GET /api/todos เมื่อมี token, rate-limit, input validation | |

หลัง backlog หมด → **maintenance mode**: เปิดใช้จริง หาบั๊กจริง, เช็ก security/dependency, เพิ่ม test coverage (ไม่ยัดฟีเจอร์ speculative)

## ⏸️ รอ decision จาก user (ไม่บล็อกงานอื่น)
1. **Payment provider** (สำหรับ Item H ส่วนตัดเงินจริง): Stripe / Omise / PromptPay / อื่น ๆ?
   → autopilot ทำ usage ledger + proposal รอไว้; **ไม่เชื่อม gateway จริงจนกว่าจะเลือก + ใส่ key**
2. **Daily autopilot mode**: (ก) push branch + user merge เช้า [ปลอดภัยกว่า] หรือ (ข) ผูก connector ให้ auto merge เต็ม (ต้องสร้าง routine จาก claude.ai UI)
3. **คลิป 9arm** (YouTube): cloud เข้า YouTube ไม่ได้ (network บล็อก) — ถ้ามีเทคนิคเฉพาะ สรุปมาเป็นข้อความ

## ❌ นอกขอบเขต / ทำไม่ได้จริง (intellectual honesty)
- **GPU HD520 = Intel iGPU** → monitor/แสดงผลได้ แต่ **train/vLLM/compute ไม่ได้** (ไม่มี CUDA/ROCm)
- **Payment charging จริง** → ต้องมี provider + key + เป็น outward-facing; autopilot ทำได้แค่ ledger + proposal
- **รันไฟล์/สคริปต์บนเครื่อง user (`G:\...`)** → cloud session ทำไม่ได้; ต้องเปิด Claude desktop + ผูกเครื่องฝั่ง user
- **`/bio-research:nextflow-development`** → คนละโดเมน (bioinformatics) ไม่เกี่ยวกับ LCA

## ⚙️ Automation ที่ตั้งไว้
- **Phase 2 trigger** — ยิงครั้งเดียว ~ตี 1 ไทย (bottleneck analyzer)
- **Autopilot improvement rounds** — คืนนี้ ทุก ~3 ชม. จนถึง ~ตี 1:30 ไทย (ไล่ backlog D→G)
- **Daily autopilot** — ทุกวัน ~08:52 ไทย (fresh session; ดูข้อจำกัด connector ใน decision #2)

## กติกาถาวร
- แตะเฉพาะ repo `9nammon` เท่านั้น ห้ามยุ่ง project/ไฟล์อื่น
- ติด 403/permission หรือเรื่องต้อง user ตัดสินใจ → รายงานแล้วหยุด อย่าเดา
- Secret (config.json/org.json/*.db) ห้าม commit (อยู่ใน .gitignore)
