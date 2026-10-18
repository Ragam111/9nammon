# Design: Heterogeneous Compute Backend Selection (CPU + Intel iGPU + AMD dGPU)

> เครื่องเป้าหมาย: **HP 14-bs043TX** — i3-6006U · Intel HD 520 · AMD Radeon 520 2GB · RAM 8GB · HDD
> หลักการ: บนฮาร์ดแวร์จำกัด "high-performance" ไม่ใช่การหาชิปแรง แต่คือ **ใช้ทุกหน่วยประมวลผลที่มี
> แล้วส่งงานไปยังหน่วยที่ทำได้เร็วที่สุด — วัดจริง ไม่เดา** (heterogeneous computing)

> ต่อยอดจาก `RESOURCE_MANAGER_DESIGN.md` (เลือกขนาดโมเดลตาม RAM) และ
> `VULKAN_GPU_EXPERIMENT.md` (ทดลอง Vulkan บน Radeon 520)

---

## 0. แก้ความเข้าใจก่อน (กันออกแบบผิด)

1. **Intel HD 520 "3.9GB" ไม่ใช่ VRAM จริง** — เป็น RAM ระบบที่แบ่งมา (shared) iGPU ไม่มีหน่วยความจำของตัวเอง
   → ถ้า iGPU กิน 2GB ระบบเหลือน้อยลง 2GB **ห้ามนับซ้ำ "8GB + 3.9GB"** มันคือก้อนเดียว
2. **iGPU/dGPU พวกนี้ไม่ใช่ "high-perf"** — HD 520 ~0.38 TFLOPS, Radeon 520 ~0.7 TFLOPS, ไม่มี Tensor Core
3. **ขอบเขต: ฝั่ง inference (รัน) เท่านั้น** — เทรน/vLLM ต้องรองรับ compute 7.0+ → ยังต้องเช่า cloud GPU
   heterogeneous บนเครื่องนี้ช่วยแค่ "รันให้เร็วขึ้นเท่าที่ฮาร์ดแวร์ไหว"

---

## 1. หน่วยประมวลผลที่มี (3 ตัว) + backend

| หน่วย | สเปกคร่าวๆ | backend ใน llama.cpp | หน่วยความจำ |
|---|---|---|---|
| **CPU** i3-6006U | 2 คอร์/4 เธรด 2.0GHz | native (CPU) | RAM ระบบ |
| **Intel HD 520** | Gen9, 24 EU | **Vulkan** หรือ **SYCL** (oneAPI) | shared จาก RAM |
| **AMD Radeon 520** | GCN, 2GB | **Vulkan** | 2GB แยกจริง |

> **กุญแจสำคัญ:** llama.cpp build แบบ **Vulkan ตัวเดียว เห็นทั้ง Intel และ AMD** เป็น device แยกกัน —
> เลือกด้วย `GGML_VK_VISIBLE_DEVICES` ไม่ต้องลงหลาย binary (SYCL เป็น build แยก ไว้ลองเทียบทีหลัง)

---

## 2. สถาปัตยกรรม: วัด → เลือก → route

```
            ┌──────────────────────────────┐
            │  Benchmark ครั้งเดียวต่อเครื่อง │
            │  (วัด tokens/sec ทุก backend)  │
            └──────────────┬───────────────┘
                           │  เก็บผลลง config.json
                           ▼
          ┌────────────────────────────────────┐
          │  resource_manager                  │
          │  - เลือกขนาดโมเดล (ตาม RAM ว่าง)    │ ◄── RESOURCE_MANAGER_DESIGN.md
          │  - เลือก compute backend (ตามผลวัด) │ ◄── doc นี้
          └────────────────┬───────────────────┘
                           ▼
         route งานไป backend ที่เร็วสุดของเครื่องนี้
          CPU  │  Intel HD520 (Vulkan/SYCL)  │  AMD 520 (Vulkan)
```

**หลักการ:** ไม่ hardcode ว่า "GPU เร็วกว่า CPU" — เพราะบน iGPU/dGPU อ่อนที่แชร์ bus เดียวกัน
บางที CPU เร็วกว่าด้วยซ้ำ **ให้ตัวเลขตัดสิน**

---

## 3. เตรียม backend (Windows, ไม่ compile)

### 3.1 Vulkan (ครอบทั้ง Intel + AMD) — ตัวหลัก
- โหลด `llama-bXXXX-bin-win-vulkan-x64.zip` จาก github.com/ggml-org/llama.cpp/releases
- แตกที่ `C:\llama` (ถ้าทำ VULKAN_GPU_EXPERIMENT.md แล้วมีอยู่แล้ว)
- ต้องลงไดรเวอร์ให้ครบ: **Intel Graphics + AMD Radeon** (ดู `VULKAN_GPU_EXPERIMENT.md` ข้อ 1.1)

### 3.2 SYCL (เฉพาะ Intel — ไว้เทียบว่าชนะ Vulkan ไหม)
- โหลด `llama-bXXXX-bin-win-sycl-x64.zip` (ต้องมี Intel oneAPI runtime)
- แตกที่ `C:\llama-sycl`
- *ทำทีหลังได้ — เริ่มที่ Vulkan ก่อน*

### 3.3 โมเดล
- ใช้ GGUF เดิมจาก VULKAN_GPU_EXPERIMENT.md: `qwen2.5-coder-0.5b-instruct-q4_k_m.gguf`

---

## 4. Benchmark matrix (หัวใจ — วัดให้ครบ)

รัน `llama-bench` แล้วจดค่า **tg** (generation t/s) และ **pp** (prompt t/s) ทุกแถว:

| # | backend | คำสั่ง (ที่ `C:\llama`) |
|---|---|---|
| 1 | **CPU ล้วน** | `.\llama-bench.exe -m <model> -ngl 0` |
| 2 | **Intel HD520 (Vulkan)** | `$env:GGML_VK_VISIBLE_DEVICES="0"` แล้ว `.\llama-bench.exe -m <model> -ngl 99` |
| 3 | **AMD 520 (Vulkan)** | `$env:GGML_VK_VISIBLE_DEVICES="1"` แล้ว `.\llama-bench.exe -m <model> -ngl 99` |
| 4 | **ทั้งคู่พร้อมกัน** | `$env:GGML_VK_VISIBLE_DEVICES="0,1"` แล้ว `.\llama-bench.exe -m <model> -ngl 99 -sm layer` |
| 5 | *(option)* Intel SYCL | ที่ `C:\llama-sycl`: `.\llama-bench.exe -m <model> -ngl 99` |

> เลข device (0=Intel, 1=AMD) ดูจาก `.\llama-cli.exe --list-devices` — อาจสลับ ให้เช็กก่อน
> `-sm layer` = split-mode แบ่ง layer ข้าม 2 GPU (ทดลอง "ใช้ทั้งสอง" ตามที่ Nammon อยากได้)
> ถ้า `out of memory` ที่ตัวไหน ลด `-ngl` (เช่น 15/20) เฉพาะตัวนั้น

**บันทึกผลเป็นตาราง** (จันทร์เอามาคุยกัน):
```
backend            | pp t/s | tg t/s | หมายเหตุ
CPU (-ngl 0)       |        |        |
Intel HD520 vulkan |        |        |
AMD 520 vulkan     |        |        |
ทั้งคู่ (0,1 layer) |        |        |
Intel SYCL (option)|        |        |
```

---

## 5. อ่านผล → ตั้งค่า resource_manager

เลือก backend ที่ **tg สูงสุด** เป็นค่า default ของเครื่องนี้ เก็บลง `config.json`:
```json
{
  "COMPUTE_BACKEND": "vulkan",
  "COMPUTE_DEVICE": "1",
  "COMPUTE_NGL": "99"
}
```

ตรรกะใน `resource_budget.py` (ต่อยอด):
```python
def pick_backend() -> dict:
    """อ่านผล benchmark ที่เก็บไว้ (config.json) แล้วคืน backend+device+ngl ที่เร็วสุด
    ถ้ายังไม่เคย benchmark -> default CPU (ปลอดภัยสุด)
    คืน {backend, device, ngl, source: 'measured'|'default'}"""
```

> ไม่สลับ backend เองเงียบๆ ตอนรัน — เลือกจากผลวัดที่เก็บไว้ + ให้คนเห็นในหน้า /dev

**สิ่งที่คาดหวังตามจริง (prediction ก่อนวัด):**
- น่าจะ **CPU ชนะ หรือพอๆ กัน** สำหรับ tg (generation = memory-bound, iGPU/dGPU แชร์ bus เดียวกับ CPU)
- iGPU/dGPU **อาจช่วย pp (prefill)** ได้บ้าง เพราะเป็นงานขนาน
- "ทั้งคู่พร้อมกัน" (#4) **น่าจะไม่คุ้ม** — overhead การ sync ข้าม 2 GPU อ่อนบน bus ช้า มักแพ้ตัวเดียว
- **แต่ทั้งหมดนี้คือสมมติฐาน — ข้อ 4 (วัด) คือตัวตัดสิน**

---

## 6. ทำไมออกแบบแบบนี้ (ไม่ hardcode)

- **ย้ายไป cloud/เครื่องใหม่ได้ทันที** — ถ้าวันหน้าได้ RTX 2060S โค้ดเดิมใช้ต่อ แค่ backend ที่ชนะเปลี่ยนเป็น CUDA
- **ซื่อสัตย์กับฮาร์ดแวร์** — ไม่หลอกตัวเองว่า "มี GPU = ต้องเร็วกว่า" ปล่อยให้ข้อมูลพูด
- **เป็นหลัก HPC จริง** — heterogeneous scheduling คือการ map งานกับหน่วยที่เหมาะสุด (เหมือน CPU+GPU
  ใน supercomputer แค่สเกลเล็กลงมาก)

---

## 7. ต่อเข้า LCA (เฟสถัดไป หลังรู้ backend ที่ชนะ)

- ตอนนี้ `server.py` → `call_ollama()` ยิงไป Ollama (port 11434)
- ถ้าผลวัดบอกว่า llama.cpp (backend X) เร็วกว่า Ollama → เพิ่มทางเลือกให้ LCA ยิงไป `llama-server`
  (OpenAI-compatible endpoint) แทน โดยเลือกจาก `config.json`
- งานนี้แตะ `call_ollama` นิดเดียว ทำเป็น PR แยกตอนมีผลวัดแล้ว

---

## 8. แผนลงมือ (จันทร์)

1. ลง Ollama CPU → แชตตอบได้ (ฐาน)
2. ลงไดรเวอร์ Intel + AMD ให้ครบ (Task Manager เห็น GPU 0 + GPU 1)
3. โหลด llama.cpp Vulkan + GGUF 0.5b
4. รัน **benchmark matrix ข้อ 4** (5 แถว) จดตัวเลข
5. เอาตัวเลขมาคุย → เลือก backend ที่ชนะ → ตั้งใน config
6. (เฟสถัดไป) ต่อยอด `resource_budget.py` ให้ `pick_backend()` + โชว์ใน /dev

---

## สรุป

"High-performance บนเครื่องอ่อน" ที่ถูกต้อง = **heterogeneous computing**: มี CPU + Intel iGPU + AMD dGPU
ก็ใช้ให้ครบ แต่ **วัดก่อนว่าตัวไหนเร็วสุด แล้วให้ระบบเลือกเอง** — ไม่เดา ไม่ hardcode
บนเครื่องนี้ผลอาจออกมาว่า CPU ชนะ (ก็คือคำตอบที่ถูก) แต่สถาปัตยกรรมนี้ scale ไปเครื่องแรงกว่าได้ทันที

*ภาคต่อของ RESOURCE_MANAGER_DESIGN.md + VULKAN_GPU_EXPERIMENT.md*
