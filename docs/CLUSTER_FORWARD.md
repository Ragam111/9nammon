# Cluster Forward — ส่งงานไปทำที่ node อื่นจริง (HPC ขั้น 3+)

ก่อนหน้านี้คลัสเตอร์ทำได้ถึง "มองเห็น" (health aggregator) + "ตัดสินใจ" (`cluster_router`
เลือก node ที่พร้อม). ขั้นนี้คือ **"ลงมือจริง"**: hub รับ `/api/chat` แล้ว *forward* งานไป
generate ที่ node ที่ router เลือก แล้วเอาคำตอบกลับมาให้ผู้ใช้

## หลักการ (สไตล์เดิม)
- **opt-in**: ปิดเป็นค่าเริ่มต้น ไม่เปิด = ทำงานที่เครื่องนี้เองเหมือนเดิมทุกประการ
- **degrade graceful**: node ปลายทางล่ม/ต่อไม่ติด → hub ทำ local แทน (งานผู้ใช้ไม่หาย)
  - blocking (`/api/chat`): fallback ได้เสมอ
  - stream (`/api/chat/stream`): fallback ได้ก่อน chunk แรกเท่านั้น (หลังเริ่มส่งคำตอบแล้วเปลี่ยนไม่ได้)
- **ปลอดภัย**: hub ต้องมี token ไว้ยืนยันตัวกับ node (node เปิดนอก localhost บังคับ auth)
- **เน็ตคือคอขวด**: timeout งาน generate กว้างกว่า health check (default 300s)

## เปิดใช้ (บน hub — เครื่องที่รับงานเข้า)
ตั้งใน `config.json` (gitignored):
```
CLUSTER_FORWARD_ENABLED = true
CLUSTER_FORWARD_TOKEN   = <master token ของ node ปลายทาง>   # X-Auth-Token
CLUSTER_FORWARD_STRATEGY = prefer_free        # หรือ round_robin
CLUSTER_FORWARD_TIMEOUT  = 300
```
แล้วลงทะเบียน node ปลายทาง (มีอยู่แล้ว): `POST /api/admin/cluster/nodes {name, url}`

## ไหลงานยังไง
```
ผู้ใช้ → hub /api/chat
          │  cluster_forward.is_enabled? + มี token?
          ▼
   cluster_store.cluster_health()  (ดู node ไหนพร้อม)
          │
   cluster_router.pick_node()      (เลือก node ว่างสุด / round-robin)
          │  node != None
          ▼
   forward_chat(node) ──success──→ reply {reply, served_by: <node>}
          │ fail (ForwardError)
          ▼
   ทำ local (model_backend.generate) ← เหมือนไม่มี forward
```
- hub เป็นคน **meter โควตา/usage** ของ API key ที่ยิงเข้ามา (node แค่คำนวณให้)
- งาน generate ไปกินแรงที่ node ปลายทาง → hub ไม่ถือ admission slot ของ local ตอน forward
- ดูปลายทางปัจจุบันได้ที่ `GET /api/admin/cluster/route` (มี `forward_enabled` ด้วย)

## ยังไม่ทำ (ซื่อตรง)
- retry หลาย node เมื่อตัวแรก fail (ตอนนี้ fallback local เลย)
- load จริงแบบวัด latency/คิวของแต่ละ node (ตอนนี้ดู RAM pressure + reachable พอ)
- forward endpoint อื่นนอกจาก chat
