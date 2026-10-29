# LCA Console — ต่อสมอง AI ภายนอก + Skills + Bots

หน้า **`/console`** คือคอนโซลแบบเดียวกับ TokenMe: ที่เดียวจบตั้งแต่ "ต่อสมอง AI" →
ห่อเป็นคำสั่งสำเร็จรูป → เปิดเป็นบริการให้ automation (เช่น n8n) เรียก

```
Connections (สมอง)  →  Skills (prompt+สมอง)  →  Bots (เปิดเป็นบริการ)  →  POST /api/bots/run
```

ทั้งหมด **stdlib ล้วน** ยืนบนของเดิมที่พิสูจน์แล้ว (`app/model_backend.py` —
OpenAI-compatible + Ollama adapter)

---

## 1) Connections — "ต่อแอป/เซิร์ฟเวอร์ AI อื่น ๆ"

สมองหนึ่งตัว = หนึ่ง connection. รองรับ 2 ชนิด (kind):

| kind | ใช้ต่ออะไร | ต้องมี |
|---|---|---|
| `openai` | OpenAI-compatible endpoint — **TokenMe**, vLLM, llama.cpp server, LM Studio, cloud, Ollama `/v1` | `base_url` (ลงท้าย `/v1`) + `api_key` |
| `ollama` | Ollama ในเครื่อง (ฟรี ใช้วันนี้) | — |

ตัวอย่างต่อ TokenMe (จากภาพที่โชว์ในสตรีม):
- kind `openai`
- base_url `https://api.tokenme.limited/api/v1`
- model `nvidia/Gemma-4-26B-A4B-NVFP4`
- api_key = key ที่สร้างในคอนโซล TokenMe

**ความปลอดภัย (Rule 23):** `api_key` ถูกเก็บใน `connections.json` (อยู่ใน `.gitignore`
ไม่ถูก commit) และ **ไม่เคยถูกส่งกลับออก API** — คืนแค่ `api_key_set: true/false`

เก็บไว้ที่ `app/connections.py` · endpoints:

| method | path | สิทธิ์ | ทำอะไร |
|---|---|---|---|
| GET | `/api/connections` | ADMIN | ลิสต์ (redacted) |
| POST | `/api/connections` | ADMIN | เพิ่ม |
| POST | `/api/connections/update` | ADMIN | แก้ (api_key ว่าง = ไม่ทับ) |
| POST | `/api/connections/delete` | ADMIN | ลบ |
| POST | `/api/connections/test` | ADMIN | เช็ก "ต่อติดไหม" (ไม่กิน token) |
| POST | `/api/connections/chat` | ADMIN | Playground — ยิงข้อความตรงถึงสมอง |

## 2) Skills — คำสั่งสำเร็จรูป

Skill = system prompt + ผูก connection (สมอง) + model + temperature. สร้างครั้งเดียว
ใช้ซ้ำได้ (เช่น "สรุปโค้ด", "ตอบลูกค้าสุภาพ", "แปลไทย→อังกฤษ")

**2 โหมด (`mode`):**

| mode | ทำงานยังไง | ใช้เมื่อ |
|---|---|---|
| `chat` (ดีฟอลต์) | system + user → คำตอบทีเดียว | ถาม-ตอบ/สรุป/แปล |
| `agent` | **ReAct loop** — คิด → เรียก tool → เห็นผล → วนจนจบ (เรียก `app/agent/core.py`) | งานที่ต้องอ่านไฟล์/รันคำสั่ง/ลงมือหลายขั้น |

โหมด `agent` เพิ่ม:
- `max_steps` (1–20, ดีฟอลต์ 6) — กันลูปยาวเกิน
- `tools_write` (bool) — เปิด tool **เสนอ** เขียนไฟล์/รันคำสั่ง (P6): agent เสนอได้ แต่
  **ไม่ลงมือจริงจนกว่าคนจะกดอนุมัติที่ `/dev`** (ดู `docs/` P6)

**sandbox ของ agent:** จำกัดอยู่ใต้ `agent_workspace/` (ใต้ project root) เท่านั้น —
bot ที่ automation ยิงเข้ามา **อ่าน repo/`config.json` (secret) ไม่ได้**. tools อ่าน-อย่างเดียว
ในชุดพื้นฐาน (`read_file`, `list_dir`, `run_command` เฉพาะ allowlist); เขียน/รันที่เปลี่ยนระบบ
ต้องผ่าน approval

`app/skills_store.py` · `/api/skills`, `/api/skills/update`, `/api/skills/delete` (ADMIN)

## 3) Bots — เปิด Skill เป็นบริการ

Bot = Skill ที่เปิดใช้งาน แล้วให้ยิงข้อความเข้ามา — เหมาะกับ n8n/เว็บ/มือถือ

```bash
curl -X POST http://127.0.0.1:8420/api/bots/run \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"id":"bot-xxxx","input":"ช่วยสรุปโค้ดนี้ให้หน่อย"}'
# chat → {"result":{"bot":"...","skill":"...","mode":"chat","output":"..."}}
# agent → {"result":{...,"mode":"agent","output":"ผลสรุป","steps":[...],"stopped_reason":"final"}}
```

bot ที่ skill เป็นโหมด `agent` จะคืน `steps[]` (log ทุกขั้น: thought/tool/args/observation)
มาให้ด้วย — หน้า Console โชว์เป็น trace. ส่ง `workspace` (relative ใต้ `agent_workspace/`)
ใน body ได้ถ้าอยากแยกโฟลเดอร์งาน

`app/bots.py` · `/api/bots`, `/api/bots/update`, `/api/bots/delete` (ADMIN),
`/api/bots/run` (USER+)

**ต้องเปิดฟีเจอร์ "Connections + Bots" ที่ `/dev` ก่อน** (default ปิด — กัน bot ยิงออก
เน็ต/ใช้ token โดยไม่ตั้งใจ) สวิตช์อยู่ใน Server features (`CONNECTIONS_ENABLED`)

---

## Schema versioning + migration (upgrade ปลอดภัย)

ไฟล์ store (`connections.json` / `skills.json` / `bots.json`) ถูกห่อใน envelope มีเลขเวอร์ชัน:

```json
{ "schema_version": 2, "records": [ ... ] }
```

`app/store_schema.py` (ใช้ซ้ำได้ทุก store) จัดการ upgrade ให้อัตโนมัติ:
- ไฟล์เก่าที่เป็น **list เปล่า ๆ** (ก่อนมี framework) = baseline **v1** — อ่านได้ปกติ
- ตอนโหลด: detect เวอร์ชัน → รัน migration ทีละสเต็ปจนถึง current → ถ้าอัปเกรดก็เขียนกลับ (persist)
- **ไม่ downgrade** ไฟล์ที่เขียนด้วยโค้ดใหม่กว่า (กันข้อมูลหาย)
- ไฟล์พัง → degrade เป็นว่าง ไม่ crash

ตัวอย่างจริง: `skills.json` อยู่ที่ **v2** — migration `v1→v2` เติม field โหมด agent
(`mode`/`max_steps`/`tools_write`) ให้ record เก่าที่สร้างก่อนมีโหมด agent โดยไม่ต้องแก้มือ

**เพิ่ม migration ใหม่:** เขียนฟังก์ชัน `records -> records` ต่อท้าย `MIGRATIONS` แล้วบวก
`SCHEMA_VERSION` ของ store นั้น — index 0 = v1→v2, index 1 = v2→v3, ... (รองรับ **เพิ่ม/ตัด/
เปลี่ยนชื่อ field** ได้จริง ไม่ใช่แค่ `.get(default)` ตอนอ่าน)

## ทำไมออกแบบแบบนี้

- **เต้ารับมาตรฐาน:** connection แค่จำค่าที่ต้องใช้ แล้วส่งต่อให้ `model_backend` ที่มีอยู่
  จัดการ — runtime ใหม่ (vLLM/cloud/ของปี 2030) เสียบผ่าน kind `openai` ได้โดยไม่แก้แอป
- **แยกชั้นชัด:** Connection (ต่อสมอง) ≠ Skill (ความรู้/คำสั่ง) ≠ Bot (บริการ) —
  เปลี่ยนสมองทีหลังได้โดยไม่แตะ skill/bot
- **ปลอดภัยโดยดีฟอลต์:** จัดการต้อง ADMIN, รัน bot ต้องเปิดฟีเจอร์ก่อน, key ไม่รั่วออก API

## ยังไม่ได้ทำ (รอบถัดไป)

- **streaming** คำตอบของ bot/playground (ตอนนี้ตอบทีเดียว) — `model_backend` มี
  `generate_stream` อยู่แล้ว ต่อเข้า SSE ได้
- **usage metering** ต่อ connection (นับ token/ราคาแบบที่ TokenMe โชว์) — ต่อกับ `app/usage_store.py`
- tool ชุดกว้างขึ้นสำหรับ agent (ค้นเว็บ/เรียก connection อื่นเป็น sub-tool)

> ✅ **ทำแล้ว:** bot แบบ **agent (ReAct + tools)** — ตั้ง skill `mode=agent` แล้ว bot จะวิ่ง
> ReAct ผ่าน `app/agent/core.py` โดยใช้ connection เป็น "สมอง", sandbox ที่ `agent_workspace/`,
> และเสียบ P6 approval ได้ด้วย `tools_write`
