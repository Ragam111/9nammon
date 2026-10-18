# ผลการทดลอง: CPU vs Intel HD 520 (llama.cpp Vulkan)

> วันที่วัด: 2026-10-18 · เครื่อง: **HP 14-bs043TX** (i3-6006U · RAM 8GB · HDD)
> เครื่องมือ: llama.cpp build `b11721` (Vulkan) · โมเดล: **Qwen2.5-Coder-0.5B-Instruct Q4_K_M** (373 MiB)
> นี่คือผลวัดจริงตามแผน `HETEROGENEOUS_COMPUTE.md` — ตัดสินด้วยข้อมูล ไม่ใช่เดา

---

## สภาพแวดล้อม

- **Vulkan เห็น GPU ตัวเดียว:** Intel(R) HD Graphics 520 (uma:1, fp16:1, **matrix cores: none**)
- **AMD Radeon 520 ไม่พร้อมใช้** — ตัวติดตั้งไดรเวอร์ AMD error 173 ("ไม่พบฮาร์ดแวร์ AMD")
  → Vulkan จึง offload ขึ้น Intel iGPU ได้เท่านั้น (AMD เป็นงานค้างไว้แก้ทีหลัง)

---

## ผลการวัด (tokens/sec)

| backend | ngl | pp512 (prefill) | tg128 (generate) |
|---|---:|---:|---:|
| **CPU** | 0 | 93.90 ± 0.73 | **19.70 ± 1.16** 🏆 |
| **Intel HD 520 (Vulkan)** | 99 | 95.99 ± 1.37 | 16.67 ± 0.46 |

---

## วิเคราะห์

1. **Prefill (pp512): เสมอกัน** — iGPU เร็วกว่าแค่ ~2% (ไม่มีนัยสำคัญ อยู่ในช่วง error)
2. **Generation (tg128): CPU เร็วกว่า ~18%** (19.70 vs 16.67)

**เหตุผล:** Intel HD 520 เป็น iGPU ที่แชร์ RAM และ memory bus เดียวกับ CPU งาน token
generation เป็น **memory-bound** → iGPU ไม่ได้เพิ่ม bandwidth แถมมี overhead การโยกข้อมูล
ระหว่าง CPU↔iGPU → **ช้าลง** ไม่มี matrix cores (Tensor) ช่วยด้วย

> ตรงกับ prediction ใน `HETEROGENEOUS_COMPUTE.md` ข้อ 5: "CPU น่าชนะ generation (memory-bound),
> iGPU อาจช่วย prefill" — ผลจริงยืนยันทั้งสองข้อ

---

## การตัดสินใจ (ด้วยข้อมูล)

**เครื่อง HP 14-bs043TX → ใช้ CPU ล้วน (`-ngl 0`) สำหรับ inference**

- iGPU offload ทำให้ generation **ช้าลง** → ไม่ใช้
- `resource_budget.pick_backend()` ควรคืน `{backend: "cpu", ngl: 0}` สำหรับสเปกนี้
- config: `COMPUTE_BACKEND=cpu`

---

## บทเรียน (หลัก 9arm)

**"มี GPU ไม่ได้แปลว่าเร็วกว่า CPU เสมอ"** — บน iGPU อ่อนที่แชร์ bus การวัดจริงพิสูจน์ว่า
CPU ชนะ สถาปัตยกรรม "วัดแล้วเลือก" (ไม่ hardcode) ทำให้เราได้คำตอบที่ถูกต้อง ไม่ใช่ความเชื่อ

---

## งานต่อ

| เรื่อง | สถานะ |
|---|---|
| ใช้ CPU เป็น backend หลัก | ✅ ตัดสินแล้วด้วยข้อมูล |
| AMD Radeon 520 (Vulkan) | ⏳ ค้าง — ไดรเวอร์ยังลงไม่ได้ (error 173) ถ้าแก้ได้ค่อยวัดเพิ่ม |
| SSD | 💡 แก้คอขวดโหลดโมเดล (HDD 100%) — คุ้มสุด |
| เทรน / vLLM | ☁️ ต้อง cloud GPU (compute ≥ 7.0) |

*ผลวัดจริงประกอบ `HETEROGENEOUS_COMPUTE.md` + `VULKAN_GPU_EXPERIMENT.md`*
