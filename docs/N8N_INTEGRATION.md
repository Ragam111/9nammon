# ต่อ n8n เข้ากับ AI Agent ของ LCA (ป้อนงานอัตโนมัติ → agent ทำ → เช็กผล)

> **ภาพรวม:** n8n = ตัว orchestrate/trigger (ปาก) — ยิง webhook มา enqueue งานเข้าคิว agent
> แล้ว worker 24/7 หยิบไปทำ, n8n เช็กผลกลับได้. LCA เป็น stdlib ล้วน ไม่ต้องลงอะไรเพิ่ม
>
> **ซื่อตรงเรื่องสเกล (10,000 งาน/วัน):** n8n *ไม่ได้* ทำให้ LLM เร็วขึ้น — มันช่วย **ป้อน/
> กระจายงานอัตโนมัติ** เข้าคิว. งานจะเสร็จเร็วแค่ไหน = จำนวน worker × node × (งาน/วันต่อ
> worker ที่ `stats` วัด). อยากได้ 10,000/วัน → ดู est_per_day จาก `/api/agent/jobs` summary
> แล้วเพิ่ม worker/node ให้พอ (นี่คือเส้นทางสู่ data center)

## สถาปัตยกรรม
```
 n8n (trigger: ตารางเวลา/เว็บฮุค/อีเวนต์)
   │  HTTP POST /api/agent/jobs   {task, workspace}
   ▼
 LCA job queue (agent_jobs.json)  ← enqueue
   │  worker หยิบ (claim) หลายตัวช่วยกันได้
   ▼
 agent worker 24/7 (python -m app.agent worker --store)  → รัน + บันทึกผล
   │
   ▼
 n8n poll  GET /api/agent/jobs?id=<job>  → เห็น status done/error + result
```

## ขั้นตอนตั้ง (ฝั่ง LCA)
1. เปิดฟีเจอร์ agent: หน้า `/dev` → **Server features** → เปิด "AI Agent" (หรือ API ด้านล่าง)
2. รัน worker 24/7 ที่หยิบงานจากคิว:
   ```bash
   python -m app.agent worker --store          # 24/7
   # เพิ่ม worker ขนานได้ (หลาย terminal/หลายเครื่อง) ให้เสร็จเร็วขึ้น
   ```
3. เปิด server ให้ n8n เรียกถึง (ตั้ง `LCA_TOKEN` เสมอเมื่อออกนอกเครื่อง)

## ตั้งใน n8n (ฝั่ง automation)
**Node: HTTP Request — enqueue งาน**
- Method: `POST`
- URL: `https://<LCA>/api/agent/jobs`
- Headers: `X-Auth-Token: <LCA_TOKEN>`, `Content-Type: application/json`
- Body (JSON): `{ "task": "สรุปว่าไฟล์ X ทำอะไร", "workspace": ".", "source": "n8n" }`
- Response: `{ "job": { "id": "job-xxxx", "status": "queued" } }` → เก็บ `id`

**Node: HTTP Request — เช็กผล (poll / รอ)**
- Method: `GET`
- URL: `https://<LCA>/api/agent/jobs?id={{ $json.job.id }}`
- Headers: `X-Auth-Token: <LCA_TOKEN>`
- วน (n8n Wait + loop) จน `status` = `done` หรือ `error` แล้วอ่าน `result.final`

**ป้อนงานเป็นพัน:** ใช้ n8n Split/Loop อ่านรายการงาน (จาก Google Sheet/DB/ไฟล์) แล้ว POST
ทีละงานเข้าคิว — worker หลายตัวช่วยกันเคลียร์

## API ย่อ
| method | path | สิทธิ์ | ใช้ทำอะไร |
|---|---|---|---|
| POST | `/api/agent/jobs` | USER + ฟีเจอร์ agent เปิด | enqueue งาน (n8n ยิงมา) |
| GET | `/api/agent/jobs?id=<job>` | USER | เช็กสถานะ/ผลงานเดียว |
| GET | `/api/agent/jobs` | USER | สรุปคิว (queued/running/done/error) + งานล่าสุด |

## ความปลอดภัย (ซื่อตรง)
- ต้องมี `X-Auth-Token` ตรง (เมื่อเปิดออกนอกเครื่อง) — n8n เก็บเป็น credential
- agent ทำงานในโหมด **sandbox อ่าน/ตรวจ** (ยังไม่เขียน/ลบ/เน็ต) → ปลอดภัยรับงานจาก n8n
  งานที่ต้องแก้ไฟล์/push จริงต้องรอ **P6 (approval gate)** ให้คนยืนยันก่อน
