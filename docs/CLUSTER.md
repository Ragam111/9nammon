# LCA — Cluster & Netbook Guide

> รวมจาก: CLUSTER_FORWARD.md, NETBOOK_NETWORKING.md, NETBOOK_SOFTWARE_STACK.md, LCA_NETBOOK_HPC.md

---

## CLUSTER_FORWARD

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

---

## NETBOOK_NETWORKING

# Netbook Networking Plan + Claude TODO — เข้าใจฮาร์ดแวร์เครือข่ายจริงก่อนวางแผน

> เครื่อง: HP 14-bs043TX (i3-6006U / 8GB / HDD) + NIC ออนบอร์ด + WiFi การ์ด
> หลัก 9arm: วางแผนจากฮาร์ดแวร์จริงที่วัดได้ ไม่ใช่จากคำว่า "High Performance"

---

## 0. ความจริงข้อเดียวที่เปลี่ยนทั้งแผน

**network ไม่ใช่คอขวดของการ serve LLM บนเครื่องนี้ — CPU ต่างหาก**

| | ตัวเลข |
|---|---|
| gen คำตอบ 200 token | ~12 วินาที (CPU 100%) |
| ขนาดข้อมูลที่ต้องส่งผ่านเน็ต | ~1–5 KB |
| เวลาส่ง 5KB บน WiFi ช้าสุด (72 Mbps) | < 0.001 วินาที |
| เน็ต Gigabit รับ request ได้ | หลายพัน/วินาที |
| CPU ตอบได้จริงพร้อมกัน | **1–2 request** |

→ **คอขวดคือ CPU gen speed** เน็ตเหลือเฟือเสมอ ลงทุนอัปเน็ต = เสียเงินเปล่า
ควรลงทุนที่ **SSD → RAM → CPU/cloud** (ตามคอขวดจริงใน BENCHMARK_RESULTS.md)

**HPC networking แท้ๆ** (InfiniBand/RDMA/100GbE) netbook ไม่มีและใส่ไม่ได้ — และงานนี้ไม่ต้องการ

---

## 1. เข้าใจฮาร์ดแวร์เครือข่ายจริง (พี่รันบนเครื่อง แล้วส่ง output ให้ Claude)

```powershell
# NIC ทั้งหมด + ความเร็ว link จริง
Get-NetAdapter | Format-Table Name,InterfaceDescription,LinkSpeed,Status

# IP ที่ถืออยู่
Get-NetIPAddress -AddressFamily IPv4 | Format-Table InterfaceAlias,IPAddress,PrefixLength

# ถ้าต่อ WiFi: ดู rate/สัญญาณจริง (เลขนี้บอกเพดานจริง ไม่ใช่สเปกกล่อง)
netsh wlan show interfaces
```

ได้ผลแล้วผมจะบอกได้ว่า เครื่องมี NIC/WiFi รุ่นอะไร, LinkSpeed เท่าไร, และยืนยันว่า "เกินพอ"
สำหรับ LCA (ซึ่งจะเป็นอย่างนั้นแทบแน่นอน)

---

## 2. สถาปัตยกรรม networking ของ LCA (ชั้น + ความปลอดภัย)

```
Client ──────────► [ reverse proxy (Caddy :443, HTTPS) ] ──► [ LCA server.py ] ──► [ Ollama :11434 ]
 LAN/WAN              ออก SSL อัตโนมัติ, หน้าด่านเดียว         bind 127.0.0.1 :8420     local เท่านั้น
                                                              + rate limit 300/60s/IP
```

**กฎความปลอดภัยที่โค้ดบังคับอยู่แล้ว (Rule 12):**
- default `bind 127.0.0.1` — เครื่องอื่นเข้าไม่ได้ (ปลอดภัยสุด)
- จะเปิดออกนอก 127.0.0.1 **ต้องใส่ `--token`** ไม่งั้น server ปฏิเสธไม่ยอมสตาร์ท
- เปิดสู่เน็ตจริง → ผ่าน reverse proxy (HTTPS) อย่าเปิดพอร์ต 8420 ตรงๆ

**3 ระดับการเปิด (เลือกตามต้องการ):**
| ระดับ | คำสั่ง | ใครเข้าได้ |
|---|---|---|
| เครื่องเดียว (default) | `python server.py . ` | เฉพาะเครื่องนี้ |
| ทั้ง LAN (บ้าน/ออฟฟิศ) | `python server.py . --host 0.0.0.0 --token SECRET` | อุปกรณ์ใน LAN เดียวกัน (มี token) |
| อินเทอร์เน็ต 24/7 | VPS + Caddy (ดู HOSTING.md) | ทุกที่ (ผ่าน HTTPS) |

---

## 3. Concurrency: ตั้งตามที่ "CPU ไหว" ไม่ใช่ "เน็ตไหว"

- เครื่องนี้ gen ได้จริง **1–2 คนพร้อมกัน** (ข้อ 0) — ThreadingHTTPServer รับ connection เยอะได้
  แต่ทุก request ไปแย่ง CPU 4 เธรดเดียวกัน → คนที่ 3 ขึ้นไปจะช้าลงเป็นเงาตามตัว
- มี **rate limit 300/60s/IP** กันยิงถี่อยู่แล้ว
- ถ้าคนเริ่มเยอะ: ไม่ใช่ปัญหาเน็ต → ย้ายโมเดลไป cloud GPU (HOSTING.md ตัวเลือก C)

---

## 4. Claude TODO — เรียงตามคุ้มค่า

| # | งาน | เจ้าของ | สถานะ |
|---|-----|--------|-------|
| N1 | รัน 3 คำสั่งข้อ 1 ส่ง output ให้ Claude → ยืนยัน NIC/LinkSpeed จริง | 👤 พี่ | ⏳ |
| N2 | ลง Ollama (P2-2) → chat จริงบน CPU | 👤 พี่ | ⏳ |
| N3 | ถ้าจะใช้ใน LAN: สตาร์ทด้วย `--host 0.0.0.0 --token` + เปิด firewall เฉพาะพอร์ต | 👤 พี่ | ⏳ |
| N4 | `/api/health` โชว์ bind host + โหมดเครือข่าย (local/LAN) + auth_required | 🤖 Claude | ✅ เสร็จ |
| N4b | **Auto-scale compute** — chat เลือกโมเดลตาม RAM อัตโนมัติ (ไม่ระบุ/`auto` → `pick_model()`) | 🤖 Claude | ✅ เสร็จ |
| N5 | เปิดสู่อินเทอร์เน็ต 24/7 → VPS + Caddy | 👤 พี่ (decision) | HOSTING.md ตัวเลือก B |
| N6 | ลงเงินที่คอขวดจริง: **SSD → RAM** ไม่ใช่ network | 👤 พี่ (decision) | — |

> N4 เป็นงานโค้ดเล็กๆ ที่ผมทำได้เลยถ้าพี่อยากได้ (โชว์ว่าตอนนี้เปิดโหมดไหน) — ที่เหลือรอเครื่องพี่/decision

---

## 5. ขอบเขต (ตรงๆ)

- ❌ ผม (cloud session) แตะเครื่องพี่ไม่ได้ → ข้อ 1/N1-N3 พี่รันเอง
- ❌ netbook ทำ HPC networking แท้ (InfiniBand/RDMA) ไม่ได้ — และไม่จำเป็น
- ✅ สิ่งที่ทำได้จริงและพอ: Gigabit/WiFi + bind ปลอดภัย + rate limit + reverse proxy (มีครบแล้ว)

*ต่อยอดจาก: HOSTING.md (เปิดสู่อินเทอร์เน็ต), NETBOOK_SOFTWARE_STACK.md (สแตกฝั่งเครื่อง), BENCHMARK_RESULTS.md (คอขวดจริง)*

---

## NETBOOK_SOFTWARE_STACK

# Netbook Software Stack — สถาปัตยกรรม software ฝั่งเครื่อง + runbook โหลดไลบรารี

> เครื่องเป้าหมาย: **HP 14-bs043TX** — i3-6006U (2C/4T), 8GB RAM, HDD จานหมุน, Intel HD520 (iGPU), AMD Radeon 520 (ไดรเวอร์ลงไม่ได้ — error 173)
> หลัก 9arm: วางบนความจริงที่ **วัดมาแล้ว** (BENCHMARK_RESULTS.md) ไม่ขายฝัน

---

## 0. ความจริงเรื่อง "HPC บน netbook" (อ่านก่อน)

**HPC แท้ๆ = หลายเครื่อง/หลาย GPU + MPI + CUDA.** เครื่องนี้ไม่ใช่แบบนั้น และลงไลบรารีสาย
cluster ลงไปก็ไม่ได้ทำให้เร็วขึ้น — มีแต่ overhead เปล่า

**แต่** "HPC เวอร์ชันเครื่องนี้" = **รีดพลัง CPU 4 เธรดให้สุดสำหรับงาน local LLM + numeric**
อันนี้ทำได้จริงและมีไลบรารีที่ช่วยจริง เอกสารนี้ว่าด้วยสิ่งนั้น — ไม่ใช่การแปลง netbook
เป็น supercomputer (ซึ่งเป็นไปไม่ได้)

ที่พิสูจน์แล้ว (Phase 1): **CPU ชนะ iGPU ~18% ในงาน generation** (19.70 vs 16.67 t/s) เพราะ
iGPU แชร์ RAM bus เดียวกัน → สถาปัตยกรรมนี้จึง **CPU-first** ตั้งแต่ราก

---

## 1. สถาปัตยกรรม (machine side) — เป็นชั้นๆ

```
┌──────────────────────────────────────────────────────────┐
│ L4  แอป       LCA (server.py + resource_budget)            │  ← เลือกโมเดล/backend ตาม RAM จริง
│               เว็บ/CLI, auth, usage, support               │
├──────────────────────────────────────────────────────────┤
│ L3  serving   Ollama (ห่อ llama.cpp + จัดการโมเดล)         │  ← API 127.0.0.1:11434
├──────────────────────────────────────────────────────────┤
│ L2  runtime   llama.cpp (CPU build)  ← runtime HPC จริง    │  ← -t 4, quantized model
│               ของเครื่องนี้ (วัดแล้วเร็วสุด)               │
├──────────────────────────────────────────────────────────┤
│ L1  math      BLAS (OpenBLAS) + NumPy  ← งาน numeric       │  ← vectorized, multi-thread
├──────────────────────────────────────────────────────────┤
│ L0  ระบบ      OS thread/affinity tuning (ใช้ 4 เธรดให้คุ้ม)│  ← OMP_NUM_THREADS, keep 1 core ให้ OS
└──────────────────────────────────────────────────────────┘
```

- **CPU-first:** L2 รันบน CPU ไม่ offload iGPU (วัดแล้วไม่คุ้ม)
- **แยกหน้าที่:** L4 (เบา, เขียนด้วย stdlib) ไม่ผูกกับ L2/L3 ที่หนัก → สลับ backend ได้ผ่าน
  `resource_budget.pick_backend()` ที่ทำไว้แล้ว
- **คอขวดจริง = HDD + RAM** ไม่ใช่ CPU → ไลบรารีช่วยได้แค่ส่วน compute; โหลดโมเดลเร็วขึ้นต้องพึ่ง **SSD** (ฮาร์ดแวร์)

---

## 2. ไลบรารี — โหลดตัวไหน / ตัดตัวไหน (ตรงๆ)

| ไลบรารี | ทำอะไร | เครื่องนี้ | เหตุผล |
|---|---|:--:|---|
| **llama.cpp** (build ที่มี) | LLM inference บน CPU/Vulkan | ✅ | runtime หลัก — วัดแล้วเร็วสุดบนเครื่องนี้ |
| **Ollama** | ห่อ llama.cpp + จัดการ/ดึงโมเดล | ✅ | โหลด zip ไว้แล้ว รอ extract (P2-2) |
| **NumPy** | เวกเตอร์/เมทริกซ์ (ผูก BLAS ในตัว) | ✅ | งาน numeric ทั่วไป; wheel บน Windows มี OpenBLAS มาแล้ว |
| **OpenBLAS** | BLAS ปรับแต่งสำหรับ CPU | ✅* | *มากับ NumPy wheel แล้ว ไม่ต้องลงแยกบน Windows |
| **OpenMP runtime** | ขนาน multi-thread บน CPU | ✅ | มากับ build ของ llama.cpp/NumPy อยู่แล้ว |
| **psutil** | อ่าน RAM/CPU จริง (ให้ resource_budget) | ✅ | dependency เดียวนอก stdlib ที่ LCA ใช้ |
| **MPI** (MS-MPI/OpenMPI) | กระจายงานหลาย process/หลายเครื่อง | ❌ | เครื่องเดียว 4 เธรด → overhead เปล่า ไม่เร็วขึ้น |
| **CUDA / cuDNN** | compute บน NVIDIA GPU | ❌ | ไม่มี NVIDIA |
| **ROCm** | compute บน AMD GPU | ❌ | Radeon 520 (GCN เก่า) ไม่รองรับ + ไดรเวอร์ลงไม่ได้ |
| **vLLM** | serving บน datacenter GPU | ❌ | ต้อง CUDA + VRAM เยอะ → ต้อง cloud GPU |

> กฎง่ายๆ: ไลบรารี **CPU/BLAS = ลง**, ไลบรารี **GPU datacenter = ข้าม** (จนกว่าจะมี GPU จริง/เช่า cloud)

---

## 3. Runbook — โหลด/ติดตั้งบนเครื่อง (พี่รันเอง, Windows PowerShell)

cloud session โหลดลงเครื่องพี่ไม่ได้ → ทำตามนี้บนเครื่องจริง

### 3.1 L3 serving — Ollama (ปลดล็อก chat จริง + agent_eval_live)
```powershell
Expand-Archive C:\Ollama\ollama.zip -DestinationPath C:\Ollama   # แตก zip ที่โหลดไว้
C:\Ollama\ollama.exe serve                                        # เปิดค้างไว้ 1 หน้าต่าง
# เปิดอีกหน้าต่าง:
C:\Ollama\ollama.exe pull qwen2.5-coder:0.5b                      # โมเดลเล็กสุด (RAM 8GB ไหว)
```

### 3.2 L1 math — NumPy (มาพร้อม OpenBLAS ในตัว)
```powershell
python -m pip install --upgrade pip
python -m pip install numpy        # wheel มี OpenBLAS + ขนานหลายเธรดในตัวแล้ว
# ตรวจว่าใช้ BLAS กี่เธรด:
python -c "import numpy; numpy.show_config()"
```

### 3.3 L0 tuning — ใช้ 4 เธรดให้คุ้ม (เก็บ 1 core ให้ OS)
```powershell
setx OMP_NUM_THREADS 4             # งาน BLAS/OpenMP
# llama.cpp โดยตรง: ใส่ -t 4  (get_tuning_options ของ LCA ตั้ง num_thread ให้แล้ว)
```

### 3.4 ตรวจว่าสแตกพร้อม
```powershell
cd C:\Users\Hello\9nammon
python server.py . --host 127.0.0.1 --port 8420
# เปิด http://127.0.0.1:8420/api/health  -> ควรเห็น ollama: "up", recommended_model, backend: cpu
python -m app.agent_eval_live        # ได้คะแนนคุณภาพ agent จริง (ต้องมี Ollama รันอยู่)
```

---

## 4. ของที่ "ช่วยจริง" vs "ไม่ช่วย" บนเครื่องนี้

**ช่วยจริง (ทำได้เลย):**
- โมเดล quantized ตัวเล็ก (0.5b/1.5b) — เลือกตาม RAM ด้วย `resource_budget.pick_model()`
- CPU threads ครบ 4 + keep_alive สั้น (คืน RAM) — `get_tuning_options()` ทำแล้ว
- NumPy+OpenBLAS สำหรับงานคำนวณ

**ไม่ช่วย / เสียเวลา:**
- ลง MPI/CUDA/ROCm/vLLM — เครื่องไม่รองรับ (ข้อ 2)
- offload layer ไป iGPU — วัดแล้วช้ากว่า CPU (BENCHMARK_RESULTS.md)

**คอขวดจริงที่ต้องแก้ด้วยฮาร์ดแวร์ (ไม่ใช่ไลบรารี):**
1. **SSD** แทน HDD — โหลดโมเดลเร็วขึ้นมาก + เครื่องลื่น (คุ้มสุด, P2-3)
2. **RAM 8→16GB** — รันโมเดลใหญ่ขึ้น/หลาย request

---

## 5. ผมทำอะไรได้ / ไม่ได้

| | |
|---|---|
| ✅ ทำได้ (ใน repo) | design/architecture, โค้ด (resource_budget, agent_eval), runbook, วัดผล |
| ❌ ทำไม่ได้ (cloud session) | โหลด/ลงไลบรารีลงเครื่องพี่, รัน Ollama บนเครื่องพี่, แตะไฟล์ในเครื่องพี่ |

→ ไลบรารีทั้งหมดในข้อ 3 **พี่รันเอง** แล้วผลลัพธ์ (`/api/health`, คะแนน `agent_eval_live`)
เอามาให้ผมดูต่อได้ เราจะปรับจูนจากข้อมูลจริง

*ต่อยอดจาก: HETEROGENEOUS_COMPUTE.md (วัดแล้วเลือก), BENCHMARK_RESULTS.md (ผลวัด), RESOURCE_MANAGER_DESIGN.md (เลือกโมเดล/backend)*

---

## LCA_NETBOOK_HPC

# LCA บน Netbook = เครื่อง "HPC" ของเรา — เอกสารรวบ (Capstone)

> เล่าครบตั้งแต่ปัญหาที่เจอ → แก้ยังไง → ข้อสรุปที่พิสูจน์ด้วยข้อมูล
> เครื่อง: HP 14-bs043TX (i3-6006U 2C/4T, 8GB RAM, HDD จานหมุน, Intel HD520, AMD Radeon 520)
> หลัก 9arm: ไม่ขายฝัน — วัดก่อนตัดสิน (รายละเอียดหลักคิดใน `9ARM_PRINCIPLES.md`)

---

## 0. "HPC บน Netbook" แปลว่าอะไร (นิยามที่ซื่อสัตย์)

**ไม่ใช่** supercomputer/cluster/CUDA — เครื่องนี้ทำไม่ได้ และลงไลบรารีสายนั้นก็เปล่าประโยชน์
**คือ** "รีดพลัง CPU 4 เธรด + RAM 8GB ให้สุด เพื่อรัน LLM ในเครื่องตัวเอง ฟรี 100%" — ซึ่ง
**ทำได้จริงและพิสูจน์แล้ว** เอกสารนี้คือบันทึกว่าเราเปลี่ยน netbook เครื่องเดียวให้เป็น
personal AI coding assistant ที่วัดคุณภาพได้ **100%** ได้ยังไง

---

## 1. ปัญหาทั้งหมดที่เจอ → แก้ยังไง (ไล่จริงตามที่ทำ)

| # | ปัญหา | สาเหตุจริง | วิธีแก้ | PR |
|---|------|-----------|--------|-|
| 1 | `install.bat` ล้มที่ folder_trust | ก๊อปไฟล์ผิดที่ + ตก dependency | installer fix | #21 |
| 2 | ต้องการระบบหน้าเว็บครบ | — | page-routing + login + support | #22 |
| 3 | เปิดเว็บไม่ได้ ERR_CONNECTION_REFUSED | **Windows proxy ดัก localhost** | ปิด ProxyEnable | (ฝั่ง user) |
| 4 | `OllamaSetup.exe` error 448 mount point | installer ชนกับ security | ใช้ **zip แทน** | (ฝั่ง user) |
| 5 | AMD ไดรเวอร์ error 173 | GPU สวิตช์เก่า ไดรเวอร์ไม่เห็น | **พัก GPU, ไป CPU** | (ตัดสินจากผลวัด) |
| 6 | แตก zip ด้วย Expand-Archive ช้าชั่วโมง | PowerShell แตกทีละไฟล์บน HDD | ใช้ `tar -xf` | (ฝั่ง user) |
| 7 | แชตจริงไม่ได้ | ยังไม่ลง Ollama | ลง Ollama → chat ได้ | #36 |
| 8 | ไม่รู้คุณภาพ agent ดีแค่ไหน | ไม่มีเกณฑ์วัด | eval harness 2 ชั้น | #31,#32 |
| 9 | eval วัดแล้วเลขไม่นิ่ง | 0.5b non-deterministic | **temp=0** + โชว์ raw | #38 |
| 10 | เคส edit ตก | 0.5b ให้ข้อมูลไม่ครบ (ไม่มี SEARCH) | **ใช้ 1.5b → 100%** | #40 |

---

## 2. สถาปัตยกรรมสุดท้าย (machine side)

```
┌───────────────────────────────────────────────────────────────┐
│ L4  LCA (server.py, stdlib)  — เว็บ 4 หน้า, auth RBAC, usage,  │
│      support dashboard, resource manager, /api/health          │
├───────────────────────────────────────────────────────────────┤
│ L3  Ollama (127.0.0.1:11434) — จัดการ/เสิร์ฟโมเดล              │
├───────────────────────────────────────────────────────────────┤
│ L2  llama.cpp (CPU)  ← runtime HPC จริงของเครื่องนี้           │
├───────────────────────────────────────────────────────────────┤
│ L1  BLAS/NumPy (CPU math)   L0  thread tuning (4 เธรด)         │
└───────────────────────────────────────────────────────────────┘
       resource_budget: ดู RAM จริง → เลือกโมเดล/ backend อัตโนมัติ
```

ดูเจาะ: `NETBOOK_SOFTWARE_STACK.md` (ไลบรารีลง/ตัด), `NETBOOK_NETWORKING.md` (เครือข่าย),
`RESOURCE_MANAGER_DESIGN.md` (ก้านสมองจัดทรัพยากร)

---

## 3. ข้อสรุปที่พิสูจน์ด้วยข้อมูลจริง (ไม่ใช่ความเชื่อ)

| คำถาม | วัดอะไร | ผลจริง | สรุป |
|-------|---------|--------|------|
| CPU vs iGPU? | tg128 (gen speed) | 19.70 vs 16.67 t/s | **CPU ชนะ ~18%** → รัน CPU ล้วน |
| คอขวดความเร็ว? | Task Manager | Disk 100% idle, RAM ตึง | **HDD + RAM** |
| 0.5b พอไหม? | golden-prompt (temp0) | 10/11 — edit ตก | เล็กไปสำหรับแก้โค้ด |
| 1.5b ดีกว่าไหม? | golden-prompt (temp0) | **11/11** รันที่ RAM ว่าง 2.6GB | **โมเดลใหญ่แก้ได้ แต่กิน RAM** |

→ **ทั้งความเร็วและคุณภาพ ชี้จุดเดียวกัน: RAM คือคอขวด** (SSD เสริมเรื่องโหลด/ลื่น)

---

## 4. ของที่ "ทำได้จริง" vs "ทำไม่ได้บนเครื่องนี้" (intellectual honesty)

**✅ ทำได้จริง (ฟรี, พิสูจน์แล้ว):** chat/ถาม concept/เขียนโค้ด (0.5b), แก้โค้ดแม่น 100% (1.5b),
เว็บ+auth+usage+support, วัดคุณภาพ agent, auto-scale โมเดลตาม RAM

**❌ ทำไม่ได้บนเครื่องนี้ (ต้อง cloud/ฮาร์ดแวร์แยก):** vLLM, เทรน/fine-tune, รองรับ 1,000 คนพร้อมกัน,
offload iGPU/dGPU ให้คุ้ม, HPC cluster จริง (MPI/CUDA/ROCm) — ดู `HOSTING.md` สำหรับ go-live

---

## 5. เส้นทางอัปเกรด (เรียงตามคุ้มค่า — ตัดสินจากข้อมูลข้อ 3)

1. **SSD** แทน HDD → โหลดโมเดลเร็วขึ้นมาก + เครื่องลื่น (คอขวดที่ชัดสุด)
2. **RAM 8→16GB** → รัน 1.5b/7b เป็น default สบาย = coding assistant คุณภาพเต็ม + รับคนได้มากขึ้น
3. **เปิดบริการ 24/7** → เช่า VPS (HOSTING.md ตัวเลือก B) เมื่อมีลูกค้าจ่ายจริง
4. **เทรน/vLLM** → cloud GPU เช่า เมื่อพร้อมจริง

> วิธีตัดสินใจซื้อของแบบ 9arm: ให้ `/api/metrics` + `/api/health` + eval บอกคอขวดจริง แล้วค่อยลงเงินตรงนั้น

---

## สรุปบรรทัดเดียว

**เราเปลี่ยน netbook i3/8GB เครื่องเดียว → AI coding assistant ที่รันในเครื่อง ฟรี 100%
แก้โค้ดแม่น 100% (ด้วย 1.5b) ทุกการตัดสินใจพิสูจน์ด้วยข้อมูลจริง ไม่ใช่ความเชื่อ**

---
