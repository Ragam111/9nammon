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

`app/skills_store.py` · `/api/skills`, `/api/skills/update`, `/api/skills/delete` (ADMIN)

## 3) Bots — เปิด Skill เป็นบริการ

Bot = Skill ที่เปิดใช้งาน แล้วให้ยิงข้อความเข้ามา — เหมาะกับ n8n/เว็บ/มือถือ

```bash
curl -X POST http://127.0.0.1:8420/api/bots/run \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"id":"bot-xxxx","input":"ช่วยสรุปโค้ดนี้ให้หน่อย"}'
# → {"result":{"bot":"...","skill":"...","output":"..."}}
```

`app/bots.py` · `/api/bots`, `/api/bots/update`, `/api/bots/delete` (ADMIN),
`/api/bots/run` (USER+)

**ต้องเปิดฟีเจอร์ "Connections + Bots" ที่ `/dev` ก่อน** (default ปิด — กัน bot ยิงออก
เน็ต/ใช้ token โดยไม่ตั้งใจ) สวิตช์อยู่ใน Server features (`CONNECTIONS_ENABLED`)

---

## ทำไมออกแบบแบบนี้

- **เต้ารับมาตรฐาน:** connection แค่จำค่าที่ต้องใช้ แล้วส่งต่อให้ `model_backend` ที่มีอยู่
  จัดการ — runtime ใหม่ (vLLM/cloud/ของปี 2030) เสียบผ่าน kind `openai` ได้โดยไม่แก้แอป
- **แยกชั้นชัด:** Connection (ต่อสมอง) ≠ Skill (ความรู้/คำสั่ง) ≠ Bot (บริการ) —
  เปลี่ยนสมองทีหลังได้โดยไม่แตะ skill/bot
- **ปลอดภัยโดยดีฟอลต์:** จัดการต้อง ADMIN, รัน bot ต้องเปิดฟีเจอร์ก่อน, key ไม่รั่วออก API

## ยังไม่ได้ทำ (รอบถัดไป)

- bot แบบ **agent (ReAct + tools)** — ตอนนี้ bot รันเป็น chat ตรง (system+user → คำตอบ);
  ต่อเข้า `app/agent/core.py` เพื่อให้ bot เรียก tools/approval ได้ เป็นก้าวถัดไป
- **streaming** คำตอบของ bot/playground (ตอนนี้ตอบทีเดียว)
- **usage metering** ต่อ connection (นับ token/ราคา) — ต่อกับ `app/usage_store.py` ได้
