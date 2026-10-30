# LCA ทั้งระบบ อธิบายแบบคอร์ส — ไฟล์ไหนทำอะไร, แอปโชว์ยังไง, เชื่อมหลังบ้านยังไง

> สำหรับนักพัฒนาที่อยากเข้าใจ LCA ตั้งแต่ศูนย์: เริ่มจาก "แอปแชท" แล้วค่อย ๆ ต่อระบบจน
> เป็นเว็บ/แอปที่มีผู้ใช้หลายคน ล็อกอิน แยกข้อมูลส่วนตัว มี AI agent ทำงานให้ มี Console
> ต่อสมอง AI ภายนอกได้หลายตัว และมีแอปเดสก์ท็อป .exe ติดตั้งแจกได้.
> ปรัชญาเดิมทั้งเล่ม: **Python stdlib ล้วน** (psutil ตัวเดียวที่เป็น dep นอก), วัดก่อนเชื่อ,
> ปลอดภัยเป็นค่าเริ่มต้น, ทำทีละขั้น.

---

## 0. ภาพใหญ่: LCA คือ 3 ชั้นซ้อนกัน

```
 ┌──────────── DESKTOP APP (lca_app.py → LCA-Desktop.exe) ────────────┐
 │  ดับเบิลคลิก .exe → เปิดหน้าต่างแอป + เซิร์ฟเวอร์ในตัว (bind 127.0.0.1)  │
 └──────────────────────────────┬────────────────────────────────────┘
                                │ เปิด browser --app หรือ webbrowser
 ┌──────────────────────────────▼─── FRONTEND (หน้าเว็บ, .html ใน app/) ─────────────────┐
 │  index.html(แชท)  login.html  spaces.html  dev.html  support  console.html(Console) │
 └───────────────────────────────────────┬───────────────────────────────────────────────┘
                                          │  fetch() ไป /api/...
 ┌────────────────────────────────────────▼──────────────────────────────────────────────┐
 │  server.py  = ตัวรับทุก request (HTTP) + จัดเส้นทาง (routing) + ตรวจสิทธิ์ + เรียกชั้นล่าง     │
 └───────────┬────────────────────────────────────┬──────────────────────┬────────────────┘
             │                                     │                      │
 ┌───────────▼── BACKEND: โมดูลงาน (app/*.py) ──┐  │  ┌──────────────────▼───── MODEL ──────┐
 │ auth/org/space/usage/cluster/agent/...       │  │  │ model_backend → Ollama / cloud      │
 │ connections/skills/bots/conn_usage           │  │  │ connections → OpenAI/Ollama ภายนอก   │
 │ แต่ละไฟล์ = 1 หน้าที่                             │  │  │ (ตัว LLM จริงที่ตอบแชท)                │
 └──────────────────────────────────────────────┘  │  └─────────────────────────────────────┘
                                                    │
 ┌──────────────────────────────────────────────────▼─────────────────────────────────────┐
 │  store_schema.py = versioning + migration framework (JSON stores ทุกตัวใช้ร่วมกัน)        │
 └───────────────────────────────────────────────────────────────────────────────────────┘
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
| **`console.html`** | **`/console`** | **Console Platform: Connections/Skills/Bots/Playground/Usage** | **`/api/connections/*`, `/api/skills/*`, `/api/bots/*`** |

> หน้าเว็บทั้งหมดเป็น HTML/JS ล้วน (ไม่มี framework) โหลดเร็ว รันบนเครื่องสเปกต่ำได้ และ
> escape ข้อความผู้ใช้กัน XSS (`esc()` function). "เป็นแอป" = เปิดหน้านี้ในเบราว์เซอร์,
> เปิดเป็น app-mode ด้วย `lca-desktop.bat`, หรือดับเบิลคลิก `LCA-Desktop.exe`.

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
`desktop_archive`(sync ข้อมูลเดสก์ท็อป) · `sysmanager/`(อ่านสเปกเครื่องให้ /dev)

---

## 6. Console Platform — `/console` (ต่อสมอง AI ภายนอก)

ระบบ 4 ชั้นที่ทำให้ LCA เป็น **gateway** ต่อ AI ได้หลายตัว (เหมือน TokenMe):

```
Connections (สมอง)  →  Skills (prompt สำเร็จรูป)  →  Bots (service)  →  Playground / Usage
```

### 6.1 Connections (`app/connections.py`)
ทะเบียนสมอง AI ภายนอก — แต่ละตัวมี: `id, name, kind(openai|ollama), base_url, model, api_key, enabled`

- **CRUD**: `list_connections()`, `add_connection()`, `update_connection()`, `remove_connection()`
- **ความปลอดภัย**: api_key **ไม่เคยถูกส่งกลับ** ใน API → ส่งแค่ `api_key_set: true/false` (Rule 23)
- **ใช้งาน**: `test_connection()` (ทดสอบ), `chat()` (ถามครั้งเดียว), `chat_stream()` (SSE สตรีม)
- **`_backend_for(rec)`**: สร้าง adapter ตาม kind → `OpenAICompatBackend` หรือ `OllamaBackend`
- **`make_generate_fn()`**: สร้างฟังก์ชัน generate ส่งให้ agent ใช้เป็นสมอง

### 6.2 Skills (`app/skills_store.py`)
Prompt สำเร็จรูป ผูกกับ connection: `{id, name, description, system_prompt, connection_id, model, temperature, mode(chat|agent), max_steps, tools_write, tools_net}`

- **2 โหมด**: `chat` (ส่ง prompt ตรง) / `agent` (ReAct loop — คิด→ใช้เครื่องมือ→วนจนจบ)
- **agent settings**: `max_steps(1-20)`, `tools_write` (อนุญาต write_file/run_command + P6 approval),
  `tools_net` (อนุญาต http_get/call_connection)
- **`build_messages()`** + **`options_for()`**: เตรียม messages + temperature ส่งให้ connection

### 6.3 Bots (`app/bots.py`)
Bot = Skill ที่เปิดเป็น service ให้เรียกจากภายนอก (n8n `POST /api/bots/run`):

- **chat mode**: ส่งต่อให้ `connections.chat()` / `connections.chat_stream()`
- **agent mode**: เรียก `agent_core.run()` พร้อม generate_fn จาก connection, workspace ถูกขังใต้
  `agent_workspace/` (bot อ่าน config.json/repo ไม่ได้)
- **run_stream()**: SSE สำหรับ chat mode (agent mode ยังไม่สตรีม — ส่ง error ชัดเจน)

### 6.4 Usage Metering (`app/conn_usage.py`)
SQLite (`conn_usage.db`) นับ token/ค่าใช้จ่าย per-connection:

- `estimate_tokens()`: นับตัวอักษร ÷ 4 (**ค่าประมาณ** ไม่ใช่ billing จริง — ซื่อตรง)
- `record_usage()`: บันทึกทุกครั้งที่ `chat()`/`chat_stream()` สำเร็จ
- `summary()`: สรุป requests/tokens/est_cost ต่อ connection (แสดงใน `/console` → Usage)

### 6.5 Store Schema + Migration (`app/store_schema.py`)
Framework กลางที่ JSON store ทุกตัวใช้ (connections, skills, ...):

- **envelope**: `{"schema_version": N, "records": [...]}` (bare list = v1 เดิม, อ่านได้ทั้งแบบ)
- **migration**: อัปรุ่นอัตโนมัติเมื่อโหลด (additive, ไม่ downgrade)
- **ตัวอย่าง**: skills v1→v2 (backfill mode/max_steps) → v2→v3 (backfill tools_net)
- **ปลอดภัย**: ถ้า version ในไฟล์ > code → ไม่แตะ (ป้องกัน downgrade ลบข้อมูล)

---

## 7. AI AGENT — `app/agent/` (ให้ระบบ "ทำงานเอง")

| ไฟล์ | หน้าที่ |
|---|---|
| `personas.py` | "คนเก่ง" หลายมุม (ceo/elon/jobs/…) แต่ละคนมี skills + วิธีคิด |
| `harness.py` | ที่ปรึกษา: `ask`(ถามคนเดียว) / `council`(หลายมุม→ประธานสังเคราะห์) |
| `tools.py` | **Sandbox** + เครื่องมือ: read_file/list_dir/run_command(allowlist) + **http_get**(กัน SSRF) + **call_connection**(ใช้สมองภายนอก) |
| `core.py` | ReAct loop: คิด→เรียก tool→เห็นผล→วนจนจบ (รับ generate_fn จาก connection / extra_system / net_ctx) |
| `worker.py` | ทำงานเอง 24/7: ดึงงานจากคิว→รัน→บันทึกผล |
| `jobs.py` | คิวงาน (ให้ n8n/automation ป้อนงานเข้า: enqueue→claim→done) |
| `stats.py` | วัดผล: สำเร็จ %, เฉลี่ยเวลา/step, est งาน/วันต่อ worker |

เส้นทางสเกล: n8n → `POST /api/agent/jobs` → `jobs` คิว → `worker` หลายตัว → `stats` วัด →
เพิ่ม worker/node ตามตัวเลข (ดู `docs/AGENT_TECH_PLAN.md`, `docs/N8N_INTEGRATION.md`).

---

## 8. "เป็นแอป" + ติดตั้ง/เปิดตัว

### 8.1 แอปเดสก์ท็อป — `LCA-Desktop.exe` (ใหม่!)
`lca_app.py` → pyinstaller แพ็กเป็น .exe ไฟล์เดียว (เหมือน ChatGPT.exe / Claude.exe):

- `data_dir()` → `%LOCALAPPDATA%\LocalCodeAssistant\data` (ข้อมูลส่วนตัว ไม่หลุด)
- `build_server()` → สร้าง HTTP server bind `127.0.0.1` (CEO mode ไม่ต้อง auth)
- `open_app_window()` → เปิดเป็น app-mode (Edge/Chrome `--app`; fallback เบราว์เซอร์ปกติ)
- `server.py._resource_root()` → อ่าน asset จาก `sys._MEIPASS` ตอนเป็น .exe (frozen detection)

Build อัตโนมัติ: `.github/workflows/build-exe.yml` (Windows runner + pyinstaller) → artifacts / Releases

### 8.2 ไฟล์ติดตั้งอื่น

| ไฟล์ | หน้าที่ |
|---|---|
| `local_coder.py` | ตัว CLI (`lca`) — ผู้ช่วยโค้ดในเทอร์มินัล |
| `server.py` | เปิดหน้าเว็บ (`start-lca.bat`) — Chat UI ที่ `127.0.0.1:8420` |
| `installer_gui.py` | ตัวติดตั้ง GUI (`TokenLCAlimit.exe`) — แถบเขียว + Desktop icon |
| `lca_app.py` | **แอปเดสก์ท็อป** (`LCA-Desktop.exe`) — ฝัง Python + server แล้ว เปิดใช้ได้เลย |
| `install.ps1` | ติดตั้งบน Windows (ก๊อป app/+sysmanager, สร้างคำสั่ง lca, ตั้ง tray) |
| `update.ps1` | อัปเดต (recursive, ไม่แตะ config.json/db/agent_workspace ของผู้ใช้) |
| `uninstall.ps1` | ถอน (ลบเฉพาะไฟล์โปรแกรม) |
| `Dockerfile` | รันที่ไหนก็ได้ (คลาวด์/เซิร์ฟเวอร์) |

ขึ้นเน็ตให้คนอื่นใช้: `docs/GO_ONLINE_FREE.md` (Cloudflare Tunnel ฟรี / Oracle Always Free / WSL).

---

## 9. ถ้าจะสร้างใหม่จากศูนย์ — ลำดับที่แนะนำ (คอร์ส step by step)

1. **แชทให้ได้ก่อน**: `server.py` (รับ HTTP + route เดียว `/api/chat`) + `index.html` + `model_backend` → คุย Ollama ได้
2. **สตรีมคำตอบ**: เพิ่ม `/api/chat/stream` (SSE) ให้คำตอบไหลทีละคำ
3. **เลือกโมเดลอัตโนมัติ + ยามคุมงาน**: `resource_budget` + `admission` (เครื่องเล็กไม่ค้าง)
4. **ผู้ใช้ + ล็อกอิน + แยกข้อมูล**: `org_store` + `auth_backend` + `_require()` → แล้วค่อยเก็บข้อมูลต่อผู้ใช้
5. **พื้นที่/ประวัติ/ตั๋ว**: `space_store` / `history_store` / `support_store` (ทุกอันผูก key กับตัวตน)
6. **แอดมิน + ตั้งค่า + กัน incident**: `dev.html` + `feature_flags` + `config_versions`(rollback) + `watchdog`
7. **คลัสเตอร์**: `cluster_store` → `cluster_router` → `cluster_forward` (หลายเครื่องช่วยกัน)
8. **agent ทำงานเอง**: `agent/tools`(sandbox+SSRF guard) → `core`(ReAct loop) → `worker`(24/7) → `jobs`(คิว) → `stats`(วัด)
9. **Console Platform (ต่อสมองภายนอก)**: `connections`(ทะเบียน AI) → `skills`(prompt สำเร็จรูป) → `bots`(service) → `conn_usage`(นับ token) + `store_schema`(migration)
10. **แอปเดสก์ท็อป .exe**: `lca_app.py` → pyinstaller bundle → ดับเบิลคลิกเปิดแชตเลย
11. **แพ็ก + ติดตั้ง + ขึ้นเน็ต**: `install*.ps1/sh` + `Dockerfile` + `.github/workflows/build-exe.yml` (CI build)

แต่ละขั้น **มีเทสของตัวเอง** (โฟลเดอร์ `tests/` — รัน `python -m unittest discover -s tests`,
ตอนนี้ **489 เทส**). นี่คือวิธี "ทำทีละขั้น + วัดผล" ที่ทำให้ต่อระบบใหญ่ได้โดยไม่พัง.

---

## 10. แผนที่ไว ๆ — "อยากแก้เรื่องนี้ ดูไฟล์ไหน"
- แชทตอบผิด/ช้า → `model_backend`, `resource_budget`, `context_manager`
- ล็อกอิน/สิทธิ์/ข้อมูลรั่ว → `org_store`, `auth_backend`, `_require()` ใน `server.py`, `space_store`
- เพิ่ม endpoint ใหม่ → `server.py` (เพิ่ม route + `_handle_*`) + โมดูล `app/` ใหม่ + เทส
- ต่อสมอง AI ใหม่ / แก้ connection → `connections.py` + `console.html`
- สร้าง skill/bot ใหม่ → `skills_store.py` / `bots.py` + ดู `CONSOLE_PLATFORM.md`
- ดูค่าใช้จ่าย/token → `conn_usage.py` (SQLite) + `/console` → Usage tab
- migration / เปลี่ยน schema → `store_schema.py` + เพิ่ม migration function ใน store ที่เกี่ยว
- เปิด/ปิดฟีเจอร์ → `feature_flags` + หน้า `/dev`
- หลายเครื่อง/สเกล → `cluster_*`, `agent/worker`, `agent/stats`
- หน้าตาเว็บ → ไฟล์ `.html` ใน `app/` + `app.css`
- .exe / build / deploy → `lca_app.py`, `.github/workflows/build-exe.yml`, `docs/INSTALLER_EXE.md`

> เอกสารพี่น้อง: `ARCHITECTURE.md`(ภาพรวมเดิม) · `CONSOLE_PLATFORM.md`(ระบบ Console) ·
> `INSTALLER_EXE.md`(แอป .exe) · `AGENT_TECH_PLAN.md`(สเกล agent) ·
> `CLUSTER_FORWARD.md` · `N8N_INTEGRATION.md` · `GO_ONLINE_FREE.md` · `learn/`(พื้นฐาน GPU/ภาษา)
