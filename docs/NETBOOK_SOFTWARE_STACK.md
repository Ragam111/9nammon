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
