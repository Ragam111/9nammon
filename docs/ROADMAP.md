# LCA (9nammon) — Roadmap / TODO

Source of truth เดียวสำหรับงานพัฒนา LCA ทั้ง user และ autopilot ใช้ไฟล์นี้ร่วมกัน
สไตล์ทีม: **stdlib ล้วน, unittest (ไม่ใช่ pytest), ทุกการเปลี่ยนผ่าน branch → PR → CI → merge, ไม่ขายฝัน**

อัปเดตล่าสุด: 2026-10-19 — **ปิด Phase 1** (ดูสรุปด้านล่าง)

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
| B | Phase 2 — bottleneck analyzer + `/api/metrics` (live) + ตรวจ Ollama correlate RAM/swap | #16 |
| DS | Design system กลาง `app/app.css` เน้น perf เครื่องอ่อน (8GB/iGPU, ฟอนต์ระบบ, ไม่มี GPU effect) | #17 |
| R | Resource dashboard — มิเตอร์ live RAM/CPU/swap/disk ใน `/dev` ดึงจาก `/api/metrics` + LCA note | #18 |
| GL | Go-live launcher `scripts/serve.sh` + runbook `GO_LIVE.md` | #19 |
| DT | Dataset collection (collect→train later) — `dataset_store` + auto-capture (opt-in) | #20 |
| IF | **Installer fix** — ก๊อปไฟล์ผิดที่ (folder_trust) + ตก sysmanager/psutil/app.css | #21 |
| WS | **ระบบหน้าเว็บทั้งระบบ** — page-routing backbone + หน้า login + หน้า support | #22 |

สถานะ main: unittest 137 เคสผ่าน, CI เขียวทุก PR, smoke test server จริงผ่านทุก endpoint

## 🏁 Phase 1 — ปิดแล้ว (Local Runtime Foundation)

**ขอบเขต Phase 1:** สร้างระบบ LCA ให้ครบ + **พิสูจน์เส้นทางการรันบนฮาร์ดแวร์จริง** (ไม่เดา)

**ส่งมอบแล้ว (เอกสารออกแบบ + ผลวัด, #23–26):**
| doc | PR | สาระ |
|---|---|---|
| `RESOURCE_MANAGER_DESIGN.md` | #23 | เลือกขนาดโมเดลตาม RAM ว่าง + health/degrade |
| `VULKAN_GPU_EXPERIMENT.md` | #24 | runbook ทดลอง llama.cpp Vulkan |
| `HETEROGENEOUS_COMPUTE.md` | #25 | ใช้ CPU+iGPU+dGPU วัดแล้วเลือก (ไม่ hardcode) |
| `BENCHMARK_RESULTS.md` | #26 | **ผลวัดจริง** |

**ข้อสรุป Phase 1 (ตัดสินด้วยข้อมูลจริงบน HP 14-bs043TX = i3-6006U/8GB/HDD):**
1. **รัน LLM ด้วย CPU ล้วน** — CPU เร็วกว่า Intel HD520 (iGPU) ~18% ในงาน generation (19.70 vs 16.67 t/s); iGPU/dGPU แชร์ RAM bus เดียวกัน offload ไม่คุ้ม
2. **คอขวดจริง = HDD + RAM** — Disk 100% ตอน idle (HDD จานหมุน), RAM 8GB ตึง → **SSD คือ upgrade ที่คุ้มสุด**
3. **AMD Radeon 520** — ลงไดรเวอร์ไม่ได้ (error 173), Vulkan เห็นแต่ Intel → พักไว้
4. **vLLM / เทรน** — ทำบนเครื่องนี้ไม่ได้ (ยืนยันซ้ำด้วยการวัด) → ต้อง cloud GPU
5. หลัก 9arm ที่ได้: **"มี GPU ไม่ได้แปลว่าเร็วกว่า CPU เสมอ — วัดก่อนตัดสิน"**

**ค้างจาก Phase 1 (ทำบนเครื่อง user, ไม่บล็อก repo):** ลง Ollama → ใช้แชตจริงบน CPU

## 🚀 Phase 2 — คิวถัดไป
**ธีม Phase 2:** เอาผล Phase 1 มาทำให้ "ใช้จริงได้ลื่น" + ต่อยอด compute

| ลำดับ | งาน | หมายเหตุ |
|------|-----|---------|
| P2-1 | **Resource Manager (code)** — `app/resource_budget.py` + `GET /api/health` + `pick_backend()` คืน CPU ตามผลวัด #26 | ต่อจาก design #23/#25 |
| P2-2 | Ollama บนเครื่อง user → แชตจริงบน CPU (ค้างจาก Phase 1) | งานฝั่ง user |
| P2-3 | SSD upgrade — แก้คอขวด HDD (โหลดโมเดลเร็วขึ้น + เครื่องลื่น) | ตัดสินจากข้อมูล Phase 1 |
| S2 | Support dashboard ใน `/dev` — แสดง ticket + เปลี่ยนสถานะผ่าน UI | ต่อจาก Item S |
| Q | 9arm agent quality — ปรับ system prompt / context handling | ต้องมีเกณฑ์วัดก่อน |
| CL | (option) Cloud runbook — vLLM + LoRA เทรนบน GPU เช่า | เมื่อพร้อมเทรนจริง |

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
