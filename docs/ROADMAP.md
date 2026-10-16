# LCA (9nammon) — Roadmap / TODO

Source of truth เดียวสำหรับงานพัฒนา LCA ทั้ง user และ autopilot ใช้ไฟล์นี้ร่วมกัน
สไตล์ทีม: **stdlib ล้วน, unittest (ไม่ใช่ pytest), ทุกการเปลี่ยนผ่าน branch → PR → CI → merge, ไม่ขายฝัน**

อัปเดตล่าสุด: 2026-10-15

## ✅ เสร็จแล้ว (merged เข้า main)
| # | งาน | PR |
|---|-----|-----|
| 1 | Phase A — Org system (CEO/Admin/User RBAC + API key free/paid + quota) + กู้ repo | #1 |
| 2 | GitHub Actions CI | #2 |
| 3 | Todo delete | #3 |
| 4 | System basics — sysinfo (CPU/RAM/storage/GPU detect, แยก integrated/compute) | #4 |
| 5 | Dev view — `/dev` + `/api/sysinfo` (ADMIN) | #5 |
| E | Database layer — SQLite history/log (snapshot + error log) | #9 |
| I | Finance ledger — บันทึกเงินเข้า/ออก record-only + summary | #10 |
| H | Usage metering — นับ usage/key ลง SQLite + สรุป cost ต่อ tier | #11 |
| G | Security — rate limit ต่อ IP + ปิด GET /api/todos | #12 |
| F | WebUI/UX — มือถือ responsive + visible error states | #13 |
| N | Notifier — Discord webhook + email (config-driven) + `POST /api/admin/notify` | #14 |
| S | Support tickets — ลูกค้าแจ้งปัญหา/ขอฟีเจอร์ + ยิงแจ้งเตือนทีม | #15 |
| B | Phase 2 — bottleneck analyzer + `/api/metrics` (live) + ตรวจ Ollama correlate RAM/swap | (PR เปิด รอ merge) |

สถานะ main: unittest 114 เคสผ่าน, CI เขียวทุก PR, smoke test server จริงผ่านทุก endpoint

## 🔜 คิวถัดไป (autopilot ไล่อัตโนมัติ)
| ลำดับ | งาน | หมายเหตุ |
|------|-----|---------|
| R | **Resource management dashboard** — หน้าจอ live RAM/CPU/disk/swap + ตัวช่วยบอก "เครื่อง 8GB รับโมเดลไหนไหว" (ต่อยอดจาก Phase 2) | ชิ้นที่ user เน้น |
| S2 | Support dashboard ใน `/dev` — แสดง ticket + เปลี่ยนสถานะผ่าน UI | ต่อจาก Item S |
| Q | 9arm agent quality — ปรับ system prompt / context handling ให้ตอบดีขึ้น | ต้องมีเกณฑ์วัดก่อน |

หลัง backlog หมด → **maintenance mode**: เปิดใช้จริง หาบั๊กจริง, เพิ่ม coverage, เช็ก security/dependency

## 💰 โมเดลธุรกิจ (ตามที่ user เลือก: tier เดียว)
- **1 paid tier** (+ free tier กันคนลองใช้): ใช้มาก = จ่ายมาก (metered ด้วย usage_store ที่ทำแล้ว)
- รายได้ → เอาไปอัป **RAM** (คอขวดหลักตอนนี้ — เครื่อง 8GB)
- ปัจจุบัน storage: HDD ภายใน ~932GB + HDD นอก ~250GB (backup แยก)
- **วิธีตัดสินใจซื้อของแบบ 9arm**: อย่าเดา — ให้ resource dashboard + usage metering บอกว่าคอขวดจริงอยู่ที่ RAM/CPU/disk ตรงไหน แล้วค่อยลงเงินตรงนั้น

## ⏸️ รอ decision/ของจาก user (ไม่บล็อกงานอื่น)
1. **Discord webhook + SMTP** → ใส่ `config.json` บนเครื่อง (`DISCORD_WEBHOOK_URL`, `SMTP_*`) เพื่อเปิดแจ้งเตือนจริง — โค้ดพร้อมแล้ว
2. **Payment provider** (ตัดเงินจริง tier เดียว): PromptPay / Stripe / Omise? → ตอนนี้มี usage ledger + proposal; ไม่เชื่อม gateway จนกว่าจะเลือก + ใส่ key
3. **Daily autopilot mode**: push + user merge [ปลอดภัย] หรือ auto-merge เต็ม (ต้องสร้าง routine จาก claude.ai UI)

## ❌ นอกขอบเขต / ทำไม่ได้จริงบนฮาร์ดแวร์ตอนนี้ (intellectual honesty)
- **vLLM / serving บน 8GB RAM + Intel HD520** → **ทำไม่ได้จริง**. vLLM ออกแบบมาสำหรับ GPU datacenter (CUDA + VRAM เยอะ); HD520 เป็น iGPU ไม่มี CUDA/ROCm และ RAM 8GB ไม่พอโหลด weight. serving layer ที่เหมาะกับเครื่องนี้คือ **Ollama/llama.cpp + โมเดล quantized ตัวเล็ก** (ที่ LCA ใช้อยู่แล้ว). ถ้าจะใช้ vLLM จริงต้องมีกล่อง GPU แยก (ซื้อเอง/เช่า cloud) → เราทำ **model adapter** ให้สลับ backend ได้ แต่ตัว vLLM ต้องรันบนเครื่องที่มี GPU
- **Payment charging จริง** → ต้องมี provider + key + ความปลอดภัยระดับการเงิน; autopilot ทำได้แค่ ledger + order record + proposal
- **รับ email/Discord "ขาเข้า" อัตโนมัติ** → ต้องมี IMAP inbox / Discord bot + creds; ตอนนี้ทำ **ขาออก** (แจ้งเตือน) + ให้ลูกค้า submit ผ่าน `POST /api/support/ticket` ได้ก่อน
- **รันไฟล์บนเครื่อง user / เข้า YouTube** → cloud session ทำไม่ได้

## ⚙️ Automation ที่ตั้งไว้ (ไล่พัฒนา + แก้บั๊กต่อเนื่องทั้งปี ตามที่ user สั่ง)
- **Phase 2 trigger** — ~ตี 1 ไทย (bottleneck analyzer)
- **Autopilot improvement rounds** — ทุก ~3 ชม. ไล่ backlog
- **Daily autopilot** — ทุกวัน ~08:52 ไทย (fresh session)
- **PR autofix** — subscribe PR → CI แดง/รีวิว → แก้ → merge อัตโนมัติ

## กติกาถาวร
- แตะเฉพาะ repo `9nammon` เท่านั้น
- ติด 403/permission หรือเรื่องต้อง user ตัดสินใจ → รายงานแล้วหยุด อย่าเดา
- Secret (config.json/org.json/*.db) ห้าม commit (อยู่ใน .gitignore)
