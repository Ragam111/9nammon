# LCA ทั้งระบบ อธิบายแบบคอร์ส — ไฟล์ไหนทำอะไร, แอปโชว์ยังไง, เชื่อมหลังบ้านยังไง

> สำหรับนักพัฒนาที่อยากเข้าใจ LCA ตั้งแต่ศูนย์: เริ่มจาก "แอปแชท" แล้วค่อย ๆ ต่อระบบจน
> เป็นเว็บ/แอปที่มีผู้ใช้หลายคน ล็อกอิน แยกข้อมูลส่วนตัว มี AI agent ทำงานให้ และติดตั้งแจกได้.
> ปรัชญาเดิมทั้งเล่ม: **Python stdlib ล้วน** (psutil ตัวเดียวที่เป็น dep นอก), วัดก่อนเชื่อ,
> ปลอดภัยเป็นค่าเริ่มต้น, ทำทีละขั้น.

---

## 0. ภาพใหญ่: LCA คือ 3 ชั้นซ้อนกัน

```
 ┌─────────────────────────── FRONTEND (หน้าเว็บ, ไฟล์ .html) ───────────────────────────┐
 │  index.html(แชท)   login.html(ล็อกอิน)   spaces.html(พื้นที่)   dev.html(แอดมิน)  support │
 └───────────────────────────────────────┬───────────────────────────────────────────────┘
                                          │  fetch() ไป /api/...
 ┌────────────────────────────────────────▼──────────────────────────────────────────────┐
 │  server.py  = ตัวรับทุก request (HTTP) + จัดเส้นทาง (routing) + ตรวจสิทธิ์ + เรียกชั้นล่าง     │
 └───────────┬───────────────────────────────────────────────────────────┬────────────────┘
             │                                                             │
 ┌───────────▼─────────── BACKEND: โมดูลงาน (app/*.py) ──────────┐  ┌──────▼───────── MODEL ─────────┐
 │ auth/org/space/usage/finance/support/cluster/agent/...        │  │ model_backend → Ollama / cloud │
 │ แต่ละไฟล์ = 1 หน้าที่ (เก็บข้อมูล/ตรรกะของมันเอง)                    │  │ (ตัว LLM จริงที่ตอบแชท)          │
 └───────────────────────────────────────────────────────────────┘  └────────────────────────────────┘
```

**กฎที่ทำให้ทั้งระบบเข้าใจง่าย:** หน้าเว็บไม่รู้จักฐานข้อมูลเลย — มันคุยกับ `server.py` ผ่าน
`/api/...` เท่านั้น. `server.py` ก็ไม่เก็บข้อมูลเอง — มันเรียกโมดูลใน `app/` ให้ทำ. แต่ละโมดูล
ใน `app/` ดูแลเรื่องของตัวเองเรื่องเดียว (single responsibility) จึงอ่าน/แก้/เทสทีละไฟล์ได้.

---

## 1. ชีพจรของ 1 ข้อความแชท (request lifecycle) — เข้าใจอันนี้ เข้าใจทั้งระบบ

ผู้ใช้พิมพ์ในหน้าแชตแล้วเกิดอะไรขึ้นตามลำดับ:

```
1. index.html  → fetch('/api/chat/stream', {headers: auth, body: {messages}})
2. server.py   → do_POST() เห็น path = /api/chat/stream → เรียก _handle_chat_stream()
3. _require("USER")        → ตรวจว่าใครยิงมา (token/คุกกี้/local) + role พอไหม   [auth]
4. _chat_prepare()         → เช็กโควตา (org_store/usage) + เลือกโมเดลตาม RAM (resource_budget)
5. (ถ้าเปิด) cluster_forward → ส่งไปทำที่ node อื่นที่ว่าง; ไม่งั้นทำที่เครื่องนี้
6. gen_gate.slot()         → ยามคุมจำนวนงานพร้อมกัน (admission) กัน RAM ล้น
7. model_backend.generate_stream() → คุยกับ Ollama/cloud ได้คำตอบทีละ token
8. ยิงกลับเป็น SSE          → หน้าเว็บเห็นคำตอบไหลทีละคำ
9. _chat_finalize()        → หักโควตา + บันทึก usage + (ถ้าเปิด) เก็บ dataset
```

ทุกฟีเจอร์อื่นก็เดินทางแบบเดียวกัน: **หน้าเว็บ → `/api/x` → handler ใน server.py → โมดูล app/x → ตอบกลับ**

---

## 2. FRONTEND — 5 หน้า (ไฟล์ .html ใน app/)

เสิร์ฟผ่านตาราง `STATIC_ROUTES` ใน `server.py` (route → ไฟล์). ทุกหน้าใช้ `app.js`/`app.css` ร่วมกัน.

| หน้า | route | ทำหน้าที่ | คุยกับ API |
|---|---|---|---|
| `index.html` | `/` | หน้าแชทหลัก (พิมพ์ → เห็นคำตอบไหลทีละคำ) | `/api/chat/stream` |
| `login.html` | `/login` | ล็อกอิน (user/pass หรือ token) | `/api/*` ผ่าน `authHeaders()` |
| `spaces.html` | `/spaces` | พื้นที่ส่วนตัว/บริษัท — แยกข้อความต่อคน/ทีม | `/api/spaces*` |
| `dev.html` | `/dev` | แดชบอร์ดแอดมิน: มอนิเตอร์ + เปิด/ปิดฟีเจอร์ + cluster + rollback | `/api/admin/*` |
| `support.html` | `/support` | ลูกค้าแจ้งปัญหา/บั๊ก | `/api/support/ticket` |

> หน้าเว็บทั้งหมดเป็น HTML/JS ล้วน (ไม่มี framework) โหลดเร็ว รันบนเครื่องสเปกต่ำได้ และ
> escape ข้อความผู้ใช้กัน XSS. "เป็นแอป" = เปิดหน้านี้ในเบราว์เซอร์ หรือห่อด้วย WebView/PWA ภายหลัง.

---

## 3. ตัวกลาง — `server.py` (หัวใจ)

ไฟล์เดียวที่เชื่อมทุกอย่าง หน้าที่:
- **รับ HTTP** (`ThreadingHTTPServer` — stdlib) ตอบได้หลาย request พร้อมกัน
- **routing**: `do_GET`/`do_POST` ดู path แล้วเรียก `_handle_*` ที่ตรงกัน
- **`_require(role)`**: ด่านตรวจสิทธิ์ (ดูข้อ 4) — ทุก endpoint ที่ไม่ public เรียกตัวนี้ก่อน
- **`resolve_server_config()`**: อ่าน `$PORT/LCA_HOST/LCA_TOKEN` + บังคับความปลอดภัย (Rule 12)
- **สร้างของกลางครั้งเดียว**: admission gate, watchdog ฯลฯ ใช้ร่วมทุก request

อยากรู้ว่า endpoint ไหนทำอะไร: หาใน `server.py` ว่า `elif parsed.path == "/api/..."` → ชี้ไป `_handle_*`.

---

## 4. ล็อกอิน + แยกข้อมูลส่วนบุคคล (โจทย์สำคัญของพี่)

**"ผู้ใช้ใช้ฟรีได้ แต่ข้อมูลแต่ละคนแยกกัน ล็อกอินแล้วบันทึกไว้"** ทำด้วย 3 ไฟล์:

- **`org_store.py`** — ทะเบียนผู้ใช้ + บทบาท (RBAC): `CEO > ADMIN > USER`. เก็บ user/รหัส(แฮช)/
  API key/โควตา. "รหัสไททัน" (master token) = CEO. เปิดเครื่องใหม่ยังไม่มีใคร → สร้าง CEO คนแรกได้.
- **`auth_backend.py`** — เต้ารับตรวจตัวตน (ปลั๊กอินได้) ที่ `_require()` ใน server.py เรียกใช้.
- **การแยกข้อมูล**: ทุกโมดูลที่เก็บข้อมูลผู้ใช้ **ผูกข้อมูลกับตัวตนที่ผ่าน `_require` แล้ว** ไม่ใช่ค่าที่
  หน้าเว็บส่งมา → ผู้ใช้ A อ่าน/ลบได้เฉพาะของตัวเอง. ตัวอย่างชัดสุดคือ `space_store.py`
  (พื้นที่ private = เจ้าของ/สมาชิกเท่านั้น, shared = ทั้งทีม) และ `usage_store.py` (นับใช้งานต่อ key).

**กฎทองของการแยกข้อมูล:** key ของข้อมูล = ตัวตนจาก session ที่ตรวจแล้ว ไม่เคยเชื่อ client.

---

## 5. BACKEND — โมดูลใน `app/` จัดกลุ่มตามหน้าที่

### 5.1 แกนโมเดล/ทรัพยากร (ทำให้แชทตอบได้ บนเครื่องเล็กก็ไหว)
| ไฟล์ | หน้าที่ |
|---|---|
| `model_backend.py` | เต้ารับ LLM — สลับ Ollama / OpenAI-compatible (cloud) ด้วย config ตัวเดียว |
| `resource_budget.py` | ดู RAM ว่าง → เลือกโมเดลใหญ่สุดที่ไหว (auto-scale) |
| `admission.py` | ยามคุมจำนวน generation พร้อมกัน — กัน RAM thrash/เครื่องค้าง |
| `hw_profile.py` | จัดระดับเครื่อง (netbook/workstation/server) + แนะนำ config |
| `mem_hierarchy.py` | วัดคอขวด RAM/ดิสก์/เน็ต (พิสูจน์ว่า "data movement คือคอขวด") |
| `context_manager.py` | ตัด/จัดประวัติสนทนาให้พอดี context ของโมเดล |

### 5.2 ผู้ใช้ / สิทธิ์ / การคิดเงิน
`org_store`(ผู้ใช้+RBAC) · `auth_backend`(ตรวจตัวตน) · `usage_store`(นับใช้งานต่อ key) ·
`finance_ledger`(บันทึกเงิน record-only) · `rate_limit`(จำกัด request ต่อ IP) · `folder_trust`(ขออนุญาตก่อนแตะโฟลเดอร์)

### 5.3 ข้อมูล/เนื้อหาของผู้ใช้
`space_store`(พื้นที่ส่วนตัว/บริษัท) · `todo_store`(งานที่ต้องทำ) · `history_store`(snapshot+error log) ·
`support_store`(ตั๋วปัญหา) · `dataset_store`(เก็บคู่สนทนาไว้เทรน — ปิดเป็นค่าเริ่มต้น) · `storage_backend`(เต้ารับที่เก็บ)

### 5.4 ตั้งค่า / กัน incident
`config_manager`(อ่าน/เขียน config.json ที่ gitignored) · `config_versions`(snapshot+rollback config) ·
`feature_flags`(เปิด/ปิดฟีเจอร์ศูนย์กลาง) · `notifier`(แจ้งเตือน Discord/Email) · `watchdog`(เฝ้า 24/7 เตือนเมื่อผิด)

### 5.5 คลัสเตอร์ (หลายเครื่องช่วยกัน → สู่ data center)
`cluster_store`(ทะเบียน+health ทุก node) · `cluster_router`(เลือก node ที่พร้อม) ·
`cluster_forward`(ส่งงานไปทำที่ node นั้นจริง + fallback local)

### 5.6 เครื่องมือเสริม
`web_search`/`tavily_search`(ค้นเว็บ) · `linear_connector`(ต่อ Linear) ·
`desktop_archive`/`build_production_package.py`(แพ็กไฟล์แจก) · `sysmanager/`(อ่านสเปกเครื่องให้ /dev)

---

## 6. AI AGENT — `app/agent/` (ให้ระบบ "ทำงานเอง")

| ไฟล์ | หน้าที่ |
|---|---|
| `personas.py` | "คนเก่ง" หลายมุม (ceo/elon/jobs/…) แต่ละคนมี skills + วิธีคิด |
| `harness.py` | ที่ปรึกษา: `ask`(ถามคนเดียว) / `council`(หลายมุม→ประธานสังเคราะห์) |
| `tools.py` | **Sandbox** + เครื่องมือ (read_file/list_dir/run_command allowlist) — คุมขอบเขตความปลอดภัย |
| `core.py` | ReAct loop: คิด→เรียก tool→เห็นผล→วนจนจบ (ลงมือทำงานจริง) |
| `worker.py` | ทำงานเอง 24/7: ดึงงานจากคิว→รัน→บันทึกผล |
| `jobs.py` | คิวงาน (ให้ n8n/automation ป้อนงานเข้า: enqueue→claim→done) |
| `stats.py` | วัดผล: สำเร็จ %, เฉลี่ยเวลา/step, est งาน/วันต่อ worker |

เส้นทางสเกล: n8n → `POST /api/agent/jobs` → `jobs` คิว → `worker` หลายตัว → `stats` วัด →
เพิ่ม worker/node ตามตัวเลข (ดู `docs/AGENT_TECH_PLAN.md`, `docs/N8N_INTEGRATION.md`).

---

## 7. "เป็นแอป" + ติดตั้ง/เปิดตัว (ไฟล์ติดตั้ง)

| ไฟล์ | หน้าที่ |
|---|---|
| `local_coder.py` | ตัว CLI (`lca`) — ผู้ช่วยโค้ดในเทอร์มินัล |
| `server.py` | เปิดหน้าเว็บ (`lca-web`) — Chat UI ที่ `127.0.0.1:8420` |
| `install.ps1` / `install.sh` | ติดตั้งบน Windows / Linux-macOS-WSL (ก๊อป app/+sysmanager, สร้างคำสั่ง lca) |
| `install_online.ps1` | ติดตั้งออนไลน์บรรทัดเดียว (ดึง main.zip จาก GitHub) |
| `Dockerfile` | รันที่ไหนก็ได้ (คลาวด์/เซิร์ฟเวอร์) |
| `update.ps1` / `uninstall.ps1` | อัปเดต / ถอน (ไม่แตะไฟล์งานผู้ใช้) |

ขึ้นเน็ตให้คนอื่นใช้: `docs/GO_ONLINE_FREE.md` (Cloudflare Tunnel ฟรี / Oracle Always Free / WSL).

---

## 8. ถ้าจะสร้างใหม่จากศูนย์ — ลำดับที่แนะนำ (คอร์ส step by step)

1. **แชทให้ได้ก่อน**: `server.py` (รับ HTTP + route เดียว `/api/chat`) + `index.html` + `model_backend` → คุย Ollama ได้
2. **สตรีมคำตอบ**: เพิ่ม `/api/chat/stream` (SSE) ให้คำตอบไหลทีละคำ
3. **เลือกโมเดลอัตโนมัติ + ยามคุมงาน**: `resource_budget` + `admission` (เครื่องเล็กไม่ค้าง)
4. **ผู้ใช้ + ล็อกอิน + แยกข้อมูล**: `org_store` + `auth_backend` + `_require()` → แล้วค่อยเก็บข้อมูลต่อผู้ใช้
5. **พื้นที่/ประวัติ/ตั๋ว**: `space_store` / `history_store` / `support_store` (ทุกอันผูก key กับตัวตน)
6. **แอดมิน + ตั้งค่า + กัน incident**: `dev.html` + `feature_flags` + `config_versions`(rollback) + `watchdog`
7. **คลัสเตอร์**: `cluster_store` → `cluster_router` → `cluster_forward` (หลายเครื่องช่วยกัน)
8. **agent ทำงานเอง**: `agent/tools`(sandbox) → `core`(loop) → `worker`(24/7) → `jobs`(คิว) → `stats`(วัด)
9. **แพ็ก + ติดตั้ง + ขึ้นเน็ต**: `install*.ps1/sh` + `Dockerfile` + คู่มือ deploy

แต่ละขั้น **มีเทสของตัวเอง** (โฟลเดอร์ `tests/` — รัน `python -m unittest discover -s tests`,
ตอนนี้ 394 เทส). นี่คือวิธี "ทำทีละขั้น + วัดผล" ที่ทำให้ต่อระบบใหญ่ได้โดยไม่พัง.

---

## 9. แผนที่ไว ๆ — "อยากแก้เรื่องนี้ ดูไฟล์ไหน"
- แชทตอบผิด/ช้า → `model_backend`, `resource_budget`, `context_manager`
- ล็อกอิน/สิทธิ์/ข้อมูลรั่ว → `org_store`, `auth_backend`, `_require()` ใน `server.py`, `space_store`
- เพิ่ม endpoint ใหม่ → `server.py` (เพิ่ม route + `_handle_*`) + โมดูล `app/` ใหม่ + เทส
- เปิด/ปิดฟีเจอร์ → `feature_flags` + หน้า `/dev`
- หลายเครื่อง/สเกล → `cluster_*`, `agent/worker`, `agent/stats`
- หน้าตาเว็บ → ไฟล์ `.html` ใน `app/` + `app.css`

> เอกสารพี่น้อง: `ARCHITECTURE.md`(ภาพรวมเดิม) · `AGENT_TECH_PLAN.md`(สเกล agent) ·
> `CLUSTER_FORWARD.md` · `N8N_INTEGRATION.md` · `GO_ONLINE_FREE.md` · `learn/`(พื้นฐาน GPU/ภาษา)
