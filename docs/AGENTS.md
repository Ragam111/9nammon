# LCA — Agent & Org Design

> รวมจาก: AGENT_ORG.md, AGENT_TECH_PLAN.md, ORG_SYSTEM.md

---

## AGENT_ORG

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

> ⚠️ **ต้องตั้งค่าฝั่ง user ก่อนใช้จริง** (โค้ดพร้อมแล้ว แต่ผมสร้าง webhook/ใส่รหัสแทนไม่ได้):
> - Discord: Server Settings → Integrations → Webhooks → New Webhook → Copy URL → ใส่ `config.json` คีย์ `DISCORD_WEBHOOK_URL`
> - Email: ใส่ `SMTP_HOST`, `SMTP_PORT` (ดีฟอลต์ 587), `SMTP_USER`, `SMTP_PASS` (เช่น Gmail App Password), `SMTP_FROM`, `SMTP_TO` ใน `config.json`
> - `config.json` อยู่ใน `.gitignore` แล้ว (Rule 23) — secret ไม่หลุดขึ้น git
> - ทดสอบ: `POST /api/admin/notify {"event":"test","text":"hello"}` (header ADMIN) — ไม่มี config ช่องไหน = `skipped (no config)`, ตั้งครบ = `sent`

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
1. ✅ substrate: org RBAC, job_queue, finance_ledger, DB layer, usage metering (done)
2. ✅ `app/notifier.py` — Discord webhook + email (stdlib, config-driven, mock-tested) + endpoint `POST /api/admin/notify` (ADMIN) ไว้ทดสอบ/ยิงแจ้งเตือน. **ต้องตั้ง config ก่อนใช้จริง** (ดูด้านล่าง)
3. job_queue: เพิ่ม field `role`/`type` + endpoint filter ตามบทบาท
4. seed 10 บทบาทเป็น role/permission preset + dev dashboard แสดงบอร์ดงานตามบทบาท
5. (ภายหลัง, ต้องออกแบบเพิ่ม) ต่อ LLM worker จริงให้แต่ละบทบาทหยิบงานทำอัตโนมัติ — เฟสนี้คือ "หลาย agent จริง" ต้องคุย cost/limit ก่อน

## นอกขอบเขต (ไม่ทำ auto)
- เชื่อม bank API จริง / โอนเงินจริง
- ควบคุมเดสก์ท็อป user
- รัน 10 LLM พร้อมกันแบบไม่มี budget guard (เฟส 5 ต้องออกแบบ cost ก่อน)

---

## AGENT_TECH_PLAN

# แผนสร้าง AI Agent สายเทค (coding + devops) — สเกล 3,000 งาน/วัน

> เอกสารออกแบบ ไม่ใช่โค้ด — วางแผนก่อนลงมือ (ปรัชญาเดิม: วัดก่อนเชื่อ, ทำทีละขั้น, ซื่อตรง)
> อัปเดต: 2026-10-24

## 1. เป้าหมาย
Agent ที่ "ลงมือทำงานเทคได้เอง" 2 สาย รวมกัน:
- **Coding**: อ่าน repo → วางแผน → แก้/เขียนโค้ด → รันเทส → สรุป/เปิด PR
- **DevOps**: ตอบคำถามระบบ → รันคำสั่งตรวจสอบ (allowlist) → อ่าน log/เมตริก → แจ้งเตือน

เป้าหมายปริมาณ: **รองรับ 3,000 งาน/วัน** อย่างเสถียร ปลอดภัย และวัดผลได้

---

## 2. วิเคราะห์สเกล 3,000 งาน/วัน (ทำก่อน — ตัวเลขกำหนดสถาปัตยกรรม)

### 2.1 อัตราเฉลี่ย
- 3,000 งาน ÷ 24 ชม. = **125 งาน/ชม. = ~1 งานทุก 29 วินาที** (เฉลี่ย)
- แต่จริงมักกระจุก (เวลางาน) — ออกแบบเผื่อ **peak ~3-5 เท่า = ~6-10 งาน/นาที**

### 2.2 เวลาต่องาน (ประมาณการ — ต้องวัดจริงภายหลัง)
งาน agent 1 งาน = หลาย step (คิด→เรียก tool→คิดต่อ). สมมติ:
- งานเล็ก (ตอบ/ตรวจ): ~30 วิ, 2-3 step
- งานกลาง (แก้โค้ด+เทส): ~3-8 นาที, 5-15 step
- งานใหญ่ (ฟีเจอร์): ~15-30 นาที, 20+ step

ถ้าเฉลี่ย **5 นาที/งาน**: 3,000 × 5 = **15,000 นาที-งาน/วัน = 250 ชม.-งาน/วัน**
→ ต้องมี **ความขนาน (concurrency) อย่างน้อย ~10-11 งานพร้อมกัน** ตลอด 24 ชม.
   (250 ชม.-งาน ÷ 24 ชม. ≈ 10.4) — และเผื่อ peak ต้องได้ ~20-30 พร้อมกัน

### 2.3 คอขวดจริงอยู่ที่ไหน (ซื่อตรง)
1. **LLM throughput (คอขวดหลัก)** — เครื่องเดียว ~10 tok/s ทำงานขนาน 10-30 ตัว *ไม่ไหว*
   (RAM ไม่พอ + swap ลง HDD = ค้าง ตามที่พิสูจน์มาแล้ว). นี่คือเหตุผลที่ต้องมี **cluster
   + cloud LLM backend** (ทำ adapter ไว้แล้ว: model_backend + cluster_forward)
2. **เน็ต** — ถ้าใช้ cloud LLM: 3,000 งาน × หลาย call × หลาย KB = ปริมาณพอควร แต่ไม่ใช่คอขวด
   เท่า latency ต่อ call (ตอบช้า = งานค้างคิว). วัด round-trip ก่อนเลือก provider
3. **Disk/IO ของ workspace** — 3,000 งานโคลน/อ่านไฟล์ ถ้าใช้ HDD จะช้า → ควร SSD หรือ tmpfs
4. **คิว + admission** — ต้องมีคิวจริง (ไม่ใช่รับทุกงานพร้อมกันจนล่ม) — ของนี้มี job_queue + admission แล้ว

### 2.4 สรุปสถาปัตยกรรมที่ตัวเลขบังคับ
> งานเดียว 3,000/วัน = **ต้องเป็นระบบคิว + หลาย worker + หลาย node/cloud** ตั้งแต่ออกแบบ
> ไม่ใช่ agent loop เดี่ยวๆ. โชคดีที่ LCA วางฐานไว้ครบแล้ว (queue, cluster, admission, adapter)

---

## 3. สถาปัตยกรรม

```
                         ┌─────────────────────────────┐
  งานเข้า (API/นัดเวลา) → │  Job Queue (SQLite, มีแล้ว)   │
                         └───────────────┬─────────────┘
                                         │ dispatcher ดึงงาน (ตาม admission)
                         ┌───────────────▼─────────────┐
                         │  Agent Workers (N ตัวขนาน)   │  ← concurrency gate
                         │  แต่ละตัวรัน agent loop       │
                         └───────┬───────────────┬──────┘
                        coding   │               │  devops
                         ┌───────▼──────┐  ┌─────▼───────┐
                         │ Tool Registry│  │ Tool Registry│  (sandbox + allowlist)
                         └───────┬──────┘  └─────┬───────┘
                                 │ LLM call       │
                         ┌───────▼────────────────▼──────┐
                         │ model_backend (adapter, มีแล้ว)│
                         │  local Ollama / cloud / cluster│ ← cluster_forward (มีแล้ว)
                         └────────────────────────────────┘
```

องค์ประกอบใหม่ที่ต้องสร้าง (ตัวหนา = ยังไม่มี):
- **`app/agent/core.py`** — agent loop (think→tool→observe→วน, จำกัด max_steps, log ทุก step)
- **`app/agent/tools.py`** — tool registry + sandbox (read_file/list_dir/run_command allowlist/web_search)
- **`app/agent/worker.py`** — ดึงงานจาก job_queue → รัน agent loop → เก็บผล (เชื่อม admission เดิม)
- **`app/agent/profiles.py`** — บุคลิก/ชุด tool ต่อสาย (coding vs devops)
- endpoint: `POST /api/agent/jobs` (สร้างงาน), `GET /api/agent/jobs/<id>` (ผล+log)

ของเดิมที่ reuse (ไม่สร้างใหม่): `job_queue`, `admission`, `model_backend`, `cluster_forward`,
`org_store` (RBAC), `space_store`, `config_versions`, `notifier`, `usage_store`

---

## 4. ความปลอดภัย (สำคัญสุด — 3,000 งาน/วันที่ทำผิดได้ = ความเสี่ยงสูง)
1. **Sandbox tool `run_command`**: allowlist คำสั่ง, timeout ต่อคำสั่ง, จำกัด cwd ใน workspace
   ของงานนั้น, ห้าม network เว้นแต่ tool `web_search` ที่คุมไว้, ห้ามลบนอก workspace
2. **ขออนุมัติก่อนทำสิ่งย้อนไม่ได้**: push/ลบ/deploy → ค้างรอคนกดยืนยัน (ไม่ auto) — ตามที่พี่ย้ำ
3. **RBAC**: สร้างงาน = USER+, ดูงานคนอื่น = ADMIN+, ตั้งค่าระบบ = CEO (master token/ไททัน)
4. **แยก workspace ต่องาน**: งานละโฟลเดอร์ ลบทิ้งเมื่อจบ (กันข้อมูลปนข้ามงาน/ข้ามคน)
5. **test + rollback ก่อนปล่อย**: ใช้ config_versions ที่มี — snapshot ก่อน, ย้อนได้ถ้าพัง
   (จำกัดความเสียหายจาก zero-day/incident)
6. **budget/quota ต่อผู้ใช้**: 3,000 งานต้องมีเพดานต่อ key กัน abuse (usage_store มีฐานแล้ว)
7. **log ทุก step ตรวจสอบย้อนหลังได้** (history_store) — รู้ว่า agent ทำอะไรไปบ้าง

---

## 5. Phases (ทำทีละขั้น วัดผลทุกขั้น)

| Phase | สิ่งที่ได้ | เกณฑ์ผ่าน |
|---|---|---|
| **P1 แกน loop** | `agent/core.py` + tool registry + 3 tool พื้นฐาน (read/list/run allowlist) + เทส | agent คิดเป็นขั้น เรียก tool ได้ จบใน max_steps (echo backend ก็เทสได้) |
| **P2 สาย coding** | tool: patch file, run tests, git diff; profile coding | ทำโจทย์แก้บั๊กจิ๋วใน repo ตัวอย่างได้จริง 1 งาน |
| **P3 สาย devops** | tool: ตรวจระบบ (sysinfo มีแล้ว), อ่าน log, แจ้งเตือน; profile devops | ตอบ+ตรวจระบบจริง 1 งาน |
| **P4 คิว+worker** | `agent/worker.py` ต่อ job_queue + admission + endpoint | รันงานจากคิวขนานได้ N ตัว ไม่ล่ม |
| **P5 สเกล+cluster** | ต่อ cluster_forward/cloud backend + budget/quota | **วัด throughput จริง**: ไต่ถึงเป้า/เห็นคอขวด |
| **P6 approval+rollback** | gate อนุมัติงานย้อนไม่ได้ + snapshot/rollback | push/deploy ต้องคนยืนยัน, ย้อนได้ |

---

## 6. วัดผล (benchmark — ซื่อตรงแบบ BENCHMARK_RESULTS.md)
วัดจริงก่อนเคลม ไม่เดา:
- **เวลา/งาน** เฉลี่ย + p95 (แยกตามสายและขนาดงาน)
- **concurrency สูงสุดที่เครื่อง/คลัสเตอร์รับไหว** ก่อน RAM thrash (ไต่ทีละขั้น)
- **throughput จริง/วัน** = concurrency × (86400 ÷ เวลาต่องาน) → เทียบเป้า 3,000
- **อัตราสำเร็จ** (งานจบถูกต้อง ÷ งานทั้งหมด) + สาเหตุที่ fail
- จากตัวเลขนี้ค่อยตอบว่า "ต้องกี่ node / cloud quota เท่าไร" ถึงจะได้ 3,000/วันจริง

---

## 7. ความเสี่ยง + สิ่งที่ยังไม่ทำ (ซื่อตรง)
- **เครื่องเดียวไม่พอแน่** สำหรับ 3,000/วัน — ต้องมี node เพิ่ม หรือ cloud LLM (ต้นทุน $)
  → P5 จะวัดให้เห็นตัวเลขจริงก่อนตัดสินใจลงเงิน
- agent ยังพลาดได้ (hallucination) → ความปลอดภัย P1,P6 คือกันความเสียหาย ไม่ใช่กันพลาด
- ตัวเลขเวลา/งานในเอกสารนี้เป็น **ประมาณการ** — P1-P4 จะได้ตัวเลขจริงมาแทน
- ยังไม่รวม: multi-agent (หลาย agent คุยกัน), fine-tune โมเดลเฉพาะงาน — ไว้หลังพิสูจน์ P1-P5

---

## 8. ขั้นถัดไปทันที
เริ่ม **P1** (agent loop + tool registry + sandbox + เทส) — echo backend ก่อน ยังไม่ต้องมี LLM จริง
ก็เห็น agent คิดเป็นขั้นและเรียก tool ได้ พอ P1 ผ่านค่อยต่อ P2

---

## ORG_SYSTEM

# LCA — Org System (CEO / Admin / User + API Key)

ระบบองค์กรที่เพิ่มเข้า LCA เพื่อรองรับหลายผู้ใช้/หลายสิทธิ์ + จัดการ API key แบบ free/paid
ยึดสไตล์เดิมของโปรเจกต์: **stdlib ล้วน, JSON store ต่อโปรเจกต์, unittest (ไม่ใช้ pytest)**

## ทำไมต้องมี
`server.py` เดิมใช้ token เดี่ยวตัวเดียว — ใครมี token ก็ทำได้ทุกอย่าง ไม่พอสำหรับองค์กร
โมดูลนี้เพิ่ม 3 อย่าง: **ใครเป็นใคร** (user), **ทำอะไรได้** (role), **ใช้ API ได้เท่าไร** (quota)

## บทบาท (สูง → ต่ำ)
| Role | ทำได้ |
|------|-------|
| **CEO** | ทุกอย่าง + ตั้ง ADMIN + ดูภาพรวมทั้งองค์กร |
| **ADMIN** | ของ USER + สร้าง/ปิด user ระดับ USER + ออก/ยกเลิก API key |
| **USER** | แชท/ใช้งาน AI (กินโควตาตาม tier ของ key) |

- ADMIN สร้าง role ที่ ≥ ตัวเองไม่ได้ (สร้าง ADMIN/CEO ไม่ได้), ปิดบัญชี CEO ไม่ได้
- **user คนแรกต้องเป็น CEO** (bootstrap) — สร้างได้โดยไม่ต้อง auth ตอนระบบยังว่าง

## API Key & Quota
| Tier | โควตา/วัน | ใช้กับ |
|------|-----------|--------|
| `free` | 100 requests | ผู้ใช้ทั่วไป / ทดลอง |
| `paid` | ไม่จำกัด | ซื้อ API / ลูกค้าจ่ายเงิน |

- key สุ่มด้วย `secrets`, รูปแบบ `lca_<f|p>_<random>` — **โชว์ค่าเต็มครั้งเดียวตอนสร้าง** หลังจากนั้นเก็บแค่ sha256 hash
- โควตารีเซ็ตอัตโนมัติเมื่อข้ามวัน

## Module Contract — `app/org_store.py`
- **Dependencies**: stdlib เท่านั้น (`hashlib`, `hmac`, `secrets`, `json`, `datetime`, `pathlib`)
- **Store**: `org.json` ที่ project_root (อยู่ใน `.gitignore` — Rule 23)
- **Security**:
  - รหัสผ่าน = `pbkdf2_hmac(sha256)` + salt สุ่ม 200k iterations (ไม่เคยเก็บ plaintext)
  - API key เก็บแค่ sha256 hash + prefix 12 ตัวแรกไว้โชว์ระบุตัว
  - เทียบค่าด้วย `hmac.compare_digest` (กัน timing attack)
  - `list_*` ไม่คืน hash/key เต็ม
- **Error Handling**: `org.json` เสีย → warn แล้วถือว่าว่าง (ไม่ crash); input/สิทธิ์ผิด → `ValueError` ให้ caller แปลงเป็น HTTP error

## HTTP API (เพิ่มใน `server.py`)
Auth 2 ทาง: `X-Auth-Token` (master = CEO, bootstrap/ดูแลระบบ) หรือ `X-API-Key` (resolve เป็น user/role/tier)

| Method | Path | สิทธิ์ขั้นต่ำ | หน้าที่ |
|--------|------|--------------|--------|
| POST | `/api/admin/users` | ADMIN* | สร้าง user (*ตอน bootstrap สร้าง CEO คนแรกได้โดยไม่ต้อง auth) |
| GET | `/api/admin/users` | ADMIN | รายชื่อ user (ไม่มี hash) |
| POST | `/api/admin/users/active` | ADMIN | เปิด/ปิด user |
| POST | `/api/admin/apikeys` | ADMIN | ออก API key (คืน key เต็มครั้งเดียว) |
| GET | `/api/admin/apikeys` | ADMIN | รายการ key (prefix เท่านั้น) |
| POST | `/api/admin/apikeys/revoke` | ADMIN | ยกเลิก key |
| GET | `/api/me` | USER | ดูตัวตน/role/tier ของตัวเอง |
| POST | `/api/chat` | USER | แชท — กินโควตาถ้าเข้ามาด้วย API key (เกิน → 429) |

> โหมด local ล้วน (ไม่ตั้ง `--token`, bind 127.0.0.1): ถือเป็น CEO เหมือนพฤติกรรมเดิม — ใช้พัฒนา/ใช้คนเดียวได้สะดวก

## ตัวอย่างใช้งาน (curl)
```bash
# 1) bootstrap CEO คนแรก (ระบบยังว่าง ไม่ต้อง auth)
curl -X POST localhost:8420/api/admin/users \
  -d '{"username":"boss","password":"password123","role":"CEO"}'

# 2) CEO สร้าง USER แล้วออก free key (ใช้ master token)
curl -X POST localhost:8420/api/admin/users -H "X-Auth-Token: $TOKEN" \
  -d '{"username":"dev","password":"password123","role":"USER"}'
curl -X POST localhost:8420/api/admin/apikeys -H "X-Auth-Token: $TOKEN" \
  -d '{"owner":"dev","tier":"free"}'      # << เก็บ key ที่คืนมาไว้เลย

# 3) dev ใช้ key แชท
curl -X POST localhost:8420/api/chat -H "X-API-Key: lca_f_xxxx" \
  -d '{"messages":[{"role":"user","content":"hi"}]}'
```

## Tests
`tests/test_org_store.py` (21 เคส — logic) + `tests/test_server_org.py` (2 เคส — HTTP/RBAC/quota)
```bash
python3 -m unittest discover -s tests
```

## ยังไม่ทำ / ข้อจำกัด (ไม่ปิดบัง ตามหลัก 9arm)
- ยังไม่มี **admin UI** บนหน้าเว็บ (`index.html`) — ตอนนี้จัดการผ่าน API/curl เท่านั้น
- ยังไม่มี **session/login cookie** — client ต้องแนบ header ทุก request (เหมาะกับ API, ยังไม่เหมาะกับ UI คนทั่วไป)
- quota เป็นแบบ **รายวันต่อ key** เท่านั้น ยังไม่มี rate-limit รายวินาที/รายเดือน
- ยังไม่ทดสอบบน Windows จริง (แซนด์บ็อกซ์เป็น Linux)

---
