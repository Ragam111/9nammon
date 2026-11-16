# HPC Server Architecture — LCA (สถาปัตยกรรมละเอียด, อิงของจริง)

> วิธีคิดแบบ 9arm: **วัดก่อน → ใช้งานจริง → เจอปัญหา → แก้ → สรุปความต้องการ →
> วางสถาปัตยกรรม → ระบุข้อจำกัด** เอกสารนี้ไม่เดาอนาคต ไม่ขายฝัน ทุกตัวเลข
> มาจากที่วัดจริงบนเครื่องจริงในโปรเจกต์นี้ (ดู BENCHMARK_RESULTS.md,
> HETEROGENEOUS_COMPUTE.md, ROADMAP.md ประกอบ)

คำว่า "HPC" ในที่นี้ **ไม่ใช่** supercomputer — มันคือ "การรีดประสิทธิภาพสูงสุด
ออกจากฮาร์ดแวร์ที่มีจริง + ต่อหลายเครื่องให้ทำงานร่วมกันอย่างคุ้มค่า" ซึ่งเป็น
นิยาม HPC ที่ใช้ได้จริงกับงบของเรา

---

## 1. วัดก่อน (Measured baseline — ตัวเลขจริง)

### 1.1 ฮาร์ดแวร์ที่มีจริง
| เครื่อง | สเปกที่วัดได้ | บทบาท |
|--------|--------------|-------|
| HP 14-bs043TX (netbook) | i3-6006U 2C/4T @2.0GHz, RAM 8GB (ว่าง ~2.6GB ตอนรัน), HDD, Intel HD520 | node inference หลัก |
| — GPU ในเครื่อง | Intel HD520 (iGPU), AMD Radeon 520 (ไดรเวอร์ error 173 = ใช้ไม่ได้) | — |
| Windows box (Hello) | Win10 22H2 (build 19045), ดิสก์ว่าง ~451GB | node/เครื่องทดสอบ |
| — GPU | **Quadro K600** — Kepler (2013), CUDA 11.4, driver 475.14, **VRAM 1GB**, compute 3.0 | display/CUDA เบา เท่านั้น |

### 1.2 ผลวัดประสิทธิภาพ (ของจริง ไม่ใช่สเปกกล่อง)
- **CPU vs iGPU (tg128):** CPU = **19.70 t/s** ชนะ iGPU = 16.67 t/s (~+18%)
  → บน netbook นี้ **CPU เร็วกว่า GPU** เพราะ iGPU แชร์ RAM เดียวกัน + bandwidth ต่ำ
- **คอขวดจริง:** HDD (โหลดโมเดลช้า) + RAM (จำกัดขนาดโมเดล) — **ไม่ใช่ CPU, ไม่ใช่ GPU**
- **Agent quality (วัดด้วย agent_eval_live):**
  - qwen2.5-coder:0.5b = **10/11** (ตก edit — ตอบ code fence เปล่า ไม่มี SEARCH/REPLACE)
  - qwen2.5-coder:1.5b = **11/11** (แก้โค้ดได้จริง) — model จริง 986MB, รันไหวที่ RAM ว่าง 2.6GB

### 1.3 ข้อสรุปจากการวัด (ไม่ใช่ความเชื่อ)
1. **GPU ทุกตัวที่มี = จบ** — iGPU ช้ากว่า CPU; Radeon 520 ไดรเวอร์พัง; K600 VRAM 1GB + Kepler เก่าเกิน llama.cpp CUDA ใหม่
2. **คอขวด = RAM + ดิสก์** ไม่ใช่หน่วยคำนวณ → เงินลงทุนที่คุ้มสุดคือ **RAM/SSD** ไม่ใช่ GPU
3. **1.5b คือพื้นเชิงคุณภาพ** — เล็กกว่านี้แก้โค้ดไม่ได้; ใหญ่กว่านี้ RAM ไม่พอ

---

## 2. ใช้งานจริง (Real-world usage)

LCA ถูกใช้เป็น **coding assistant บน terminal + web** ที่รันโมเดล local (ฟรี ไม่มีค่า API)
และเปิดขาย **API key** (WebLCA) ให้คนอื่นยิงเข้ามาใช้โมเดลของเรา

รูปแบบการใช้จริง 3 แบบ:
1. **เจ้าของเครื่องใช้เอง** — chat/แก้โค้ดผ่าน `/` (index.html) หรือ terminal (local_coder)
2. **ลูกค้ายิงผ่าน API key** — POST /api/chat พร้อม X-API-Key (มี quota/tier, บันทึก usage ต่อ key)
3. **หลายเครื่องรวมเป็นคลัสเตอร์** — แต่ละ node รัน server เอง, hub รวม health มาดูที่เดียว

---

## 3. ปัญหาที่เจอจริง (Problems)

| # | ปัญหา | หลักฐาน (วัด/สังเกตจริง) |
|---|-------|------------------------|
| P1 | เครื่องอ่อน รันโมเดลใหญ่ไม่ไหว | RAM ว่าง 2.6GB, 7b ต้อง ~5GB+ |
| P2 | GPU ที่มีช่วยไม่ได้ | CPU ชนะ iGPU 18%, K600 VRAM 1GB ล้นทันที |
| P3 | โมเดลเล็ก (0.5b) แก้โค้ดไม่เป็น | agent_eval 10/11 ตก edit |
| P4 | ถ้าผูกกับ Ollama ตัวเดียว ย้าย runtime ทีหลังยาก | - |
| P5 | ขาย API แต่ไม่รู้ใครใช้เท่าไหร่ | ไม่มี usage ต่อ key |
| P6 | มีหลายเครื่องแต่ไม่รู้สถานะรวม | ต้อง ssh เข้าทีละเครื่อง |
| P7 | เพิ่มเครื่องเข้าคลัสเตอร์ต้องตั้งเองที่ hub | manual, ไม่ scale |

---

## 4. แก้ปัญหา (Solutions — ที่ทำไปแล้วในโปรเจกต์)

| ปัญหา | วิธีแก้ (merged) | PR |
|-------|-----------------|-----|
| P1 | `resource_budget.pick_model()` auto-scale ตาม RAM ว่างจริง | — |
| P2 | `pick_backend()` default = **cpu/ngl 0** (ตามผล benchmark) ไม่ใช้ GPU | — |
| P3 | 1.5b เป็น default เมื่อ RAM ไหว + negative example ใน prompt | #48, #49 |
| P4 | **Model Backend Adapter** (Ollama / OpenAI-compatible สลับด้วย config) | #45 |
| P5 | **Usage / API-key monitor** (units/cost/events ต่อ key) | #46 |
| P6 | **Cluster monitor** (รวม /api/health ทุก node) | #50 |
| P7 | **Ecosystem settings** (node ตั้งค่าตัวเอง + join hub เอง) | #51 |

หลักการร่วม: **stdlib ล้วน** (psutil ตัวเดียวนอก stdlib), **config-driven** ไม่ hardcode,
**degrade graceful** (ส่วนหนึ่งล่มไม่ทำให้ทั้งระบบพัง), **วัดได้** (มี eval/scorecard)

---

## 5. ความต้องการ Server HPC (Requirements)

### 5.1 Functional
- F1 เสิร์ฟ inference ได้ทั้ง local (ฟรี) และผ่าน API key (มี quota/tier/usage)
- F2 เลือกโมเดลอัตโนมัติตามทรัพยากรจริงของแต่ละเครื่อง
- F3 สลับ compute backend / model runtime ได้ด้วย config ไม่แก้โค้ดแอป
- F4 หลาย node รวมเป็นคลัสเตอร์ — เห็น health รวม, node join เองได้
- F5 มองเห็นทุกอย่างที่ขาย (usage ต่อ key) และทุกเครื่อง (health ต่อ node)

### 5.2 Non-functional (วัดได้)
- N1 รันได้บนเครื่องอ่อน (RAM ว่าง ~2GB ขึ้นไป) — ไม่ OOM
- N2 ไม่พึ่ง GPU (CPU-first ตามผลวัด)
- N3 ไม่เพิ่ม dependency เกิน stdlib + psutil (ติดตั้งง่าย พกพาได้)
- N4 secret (token/key) ไม่หลุด git, ไม่ print เต็ม
- N5 ส่วนประกอบใด ๆ ล่ม → ระบบที่เหลือยังทำงาน (degrade)

---

## 6. สถาปัตยกรรมละเอียด (Detailed architecture)

### 6.1 ภาพรวมคลัสเตอร์
```
                    ┌─────────────────────────────┐
                    │   HUB node (จอรวม)          │
                    │   server.py + /dev          │
                    │   - Cluster monitor         │
                    │   - Usage / API-key monitor │
                    └──────────────┬──────────────┘
         register (POST /cluster/nodes, X-Auth-Token)  ▲
         + hub ดึง health (GET /api/health)            │
          ┌──────────────────────┬─────────────────────┤
          │                      │                      │
   ┌──────┴──────┐        ┌──────┴──────┐        ┌──────┴──────┐
   │  node: arm  │        │ node: เพื่อน │        │ node: สาขา  │
   │  server.py  │        │  server.py  │        │  server.py  │
   │ Ollama(CPU) │        │ Ollama(CPU) │        │ OpenAI-compat│
   │ 1.5b/0.5b   │        │ 1.5b        │        │ (cloud GPU) │
   └─────────────┘        └─────────────┘        └─────────────┘
   แต่ละ node ตัดสินใจเอง (pick_model/pick_backend ตาม RAM ตัวเอง)
```

### 6.2 ชั้นภายใน 1 node (server.py)
```
HTTP (ThreadingHTTPServer, stdlib)
├── auth layer        : X-Auth-Token (master=CEO) / X-API-Key (org_store) / localhost=CEO
│                       + rate limit ต่อ IP (300/60s)
├── resource_budget   : "ก้านสมอง" — available_ram() → pick_model() / pick_backend()
│                       (PREFERRED_MODEL=1.5b เมื่อไหว, ถอย 0.5b ตอนตึง, backend=cpu)
├── model_backend     : adapter — OllamaBackend | OpenAICompatBackend (เลือกด้วย config)
│                       BackendError → 502 (ไม่ฆ่าโปรเซส)
├── stores (SQLite/JSON, per-project, conn ต่อ call — ปลอดภัยกับ threads)
│   ├── org_store      : user/role (CEO>ADMIN>USER) / api key (hash) / quota
│   ├── usage_store    : units/cost/events ต่อ key  → Usage monitor
│   ├── cluster_store  : ทะเบียน node + health aggregator + ecosystem settings
│   ├── support/finance/history/dataset/todo ...
└── adapters (ตระกูลเดียวกัน, 2 impl ต่อตัว, เลือกด้วย config)
    ├── storage_backend : Local | Memory
    ├── auth_backend    : Local | Static
    └── notifier        : MultiChannel(Discord/email) | Null
```

### 6.3 การตัดสินใจเลือกโมเดล (ต่อ node, วัดจริง)
```
available_ram()  ─┐
                  ├─► pick_model(project_root)
PREFERRED_MODEL ──┤      1. preferred (default 1.5b) fits?  → ใช้ 1.5b
(config)          │      2. ไม่ไหว → ใหญ่สุดที่ fits        → 0.5b
                  │      3. ไม่ทราบ RAM                      → เล็กสุด (safe)
footprint (วัด):  │   fits = footprint + HEADROOM(1.2GB) ≤ avail
 0.5b=0.6 1.5b=1.0 7b=5.0 GB
```

### 6.4 Data flow: ลูกค้ายิง API
```
client ──X-API-Key──► /api/chat
  → auth_backend: key ถูกไหม + org_store.has_quota?  (ไม่พอ → 429)
  → pick_model (ถ้าไม่ระบุ model)
  → model_backend.generate (Ollama CPU / cloud)
  → usage_store.record (units/cost ต่อ key)
  → reply  (+ บันทึกไว้โชว์บน Usage monitor)
```

### 6.5 Data flow: node เข้าร่วมคลัสเตอร์
```
node /dev → ตั้งค่า NODE_NAME/NODE_URL/HUB_URL/HUB_TOKEN (เก็บ config.json)
  → กด "เข้าร่วม hub" → register_with_hub()
     POST HUB_URL/api/admin/cluster/nodes  (X-Auth-Token=HUB_TOKEN, body {name,url})
  → hub: cluster_store.add_node
  → hub /dev Cluster monitor: cluster_health() ดึง GET node/api/health ทุกตัว
     (degrade: node ล่ม = offline ไม่พังทั้งจอ)
```

---

## 7. ข้อจำกัด (Constraints — ตรงไปตรงมา)

### 7.1 ฮาร์ดแวร์ (วัดแล้ว แก้ด้วยโค้ดไม่ได้)
- **RAM 8GB** = เพดานโมเดล ~1.5b; 7b ขึ้นไปไม่ไหวบน netbook
- **ไม่มี GPU ใช้ได้** = inference เป็น CPU-only ตลอด (K600 1GB/Kepler, iGPU ช้ากว่า CPU)
- **HDD** = โหลดโมเดลช้า (SSD จะช่วยตรงนี้มากกว่าเปลี่ยน CPU/GPU)
- **บ้าน/เน็ตบ้าน** = ไม่มี IP public คงที่ → ขาย API สู่อินเทอร์เน็ตตรง ๆ ต้องมี tunnel/reverse proxy (ดู HOSTING.md)

### 7.2 สถาปัตยกรรม (ขอบเขตที่ "ยังไม่ทำ" โดยตั้งใจ)
- คลัสเตอร์เป็น **health aggregator** ไม่ใช่ scheduler — **ยังไม่มี** load-balance / สั่งงานข้าม node
- register เป็น **manual push** (กดปุ่ม) — ยังไม่ auto-register ตอน start, ยังไม่ heartbeat ถอน node ที่หาย
- cluster_health ดึงแบบ **sequential** — node เยอะ ๆ (หลายสิบ) จะช้า, ต้องทำ parallel ก่อน
- ไม่มี auth ระหว่าง node แบบ mutual TLS — พึ่ง X-Auth-Token (พอสำหรับ LAN/เครื่องตัวเอง)

### 7.3 เส้นทางขยายที่ "คุ้ม" (ถ้าจะลงทุน — เรียงตาม ROI ที่วัดได้)
1. **SSD + RAM upgrade** บน node → แก้คอขวดจริง (HDD/RAM) ได้โมเดลใหญ่ขึ้น + โหลดเร็วขึ้น
2. **เช่าคลาวด์ GPU ชั่วโมง** (vLLM/OpenAI-compatible) เป็น node หนึ่งในคลัสเตอร์ → เสียบผ่าน
   `OpenAICompatBackend` ที่มีอยู่แล้ว ไม่แก้แอป (จ่ายเฉพาะตอนใช้)
3. **parallel cluster_health + auto-register + heartbeat** → เมื่อ node เกิน ~10 ตัว
4. **load-balance จริง** (hub กระจาย request ไป node ที่ว่างสุด) → เมื่อมีลูกค้า API จริงจัง

> หลักคิดปิดท้าย (9arm): เราไม่ซื้อ GPU แพงเพราะ "ดูเท่" — เราวัดแล้วรู้ว่าคอขวดคือ
> RAM/ดิสก์ และทางที่ถูกคือ interface ที่สะอาด (adapter) ให้เสียบของแรง (คลาวด์)
> เข้ามาเมื่อ *มีเงินจากลูกค้าจริง* ไม่ใช่ลงทุนล่วงหน้ากับการ์ดที่รันไม่ไหว
