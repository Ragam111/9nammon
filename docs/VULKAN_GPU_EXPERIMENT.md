# การทดลอง: llama.cpp Vulkan offload ขึ้น AMD Radeon 520

> เครื่องเป้าหมาย: **HP 14-bs043TX** — Intel Core i3-6006U (2C/4T) · Intel HD 520 · **AMD Radeon 520 2GB** · RAM 8GB · HDD จานหมุน
> เป้าหมาย: วัดจริงว่า "ให้ GPU แบ่งเบา CPU" (layer offload) **เร็วขึ้นไหม** — ตัดสินด้วยตัวเลข ไม่ใช่ความเชื่อ

---

## 0. ตั้งความคาดหวังก่อน (9arm honesty)

- Radeon 520 มี VRAM แค่ **2GB** → offload ได้ไม่กี่ layer ของโมเดล 0.5b
- GPU อ่อน + ต้องโยกข้อมูลผ่าน bus → **อาจเร็วขึ้นนิดหน่อย หรือเท่าเดิม หรือช้าลง** เป็นไปได้ทั้งหมด
- นี่คือ **การทดลองเพื่อหาคำตอบ** ไม่ใช่การแก้ที่การันตีผล — ถ้าไม่เร็วขึ้น CPU ล้วนก็คือคำตอบที่ถูกต้อง
- ทำไมใช้ Vulkan ไม่ใช่ ROCm/CUDA: ROCm ไม่รองรับ Radeon 520 (เก่าเกิน), CUDA เป็นของ Nvidia — **Vulkan เป็นทางเดียวที่ GPU เก่านี้แตะ LLM ได้**

---

## 1. เตรียมของ (ไม่ต้อง compile อะไร)

### 1.1 อัปเดตไดรเวอร์ AMD ให้รองรับ Vulkan
- ลงไดรเวอร์ Radeon 520 จากหน้า HP support ของรุ่น **14-bs043TX** (หรือ AMD Software: Adrenalin ถ้าลงได้)
- เช็กว่ามี Vulkan: ดาวน์โหลด `vulkaninfo` (จาก Vulkan SDK) หรือข้ามไปข้อ 2 แล้วดูว่า llama.cpp เห็น device ไหม

### 1.2 โหลด llama.cpp แบบ Vulkan (prebuilt)
1. ไปที่ https://github.com/ggml-org/llama.cpp/releases (release ล่าสุด)
2. โหลดไฟล์ชื่อแนว **`llama-bXXXX-bin-win-vulkan-x64.zip`** (ต้องมีคำว่า `vulkan`)
3. แตกไปที่ `C:\llama` — จะได้ `llama-cli.exe`, `llama-bench.exe`, `llama-server.exe`

### 1.3 โหลดโมเดล GGUF ตัวเล็ก (0.5b)
llama.cpp ใช้ไฟล์ `.gguf` โดยตรง (คนละที่กับ Ollama) — โหลดมาวางที่ `C:\llama\models\`
- รุ่นแนะนำ: **Qwen2.5-Coder-0.5B-Instruct** quant `Q4_K_M`
- แหล่ง: ค้น HuggingFace `Qwen2.5-Coder-0.5B-Instruct-GGUF` → โหลดไฟล์ `*q4_k_m.gguf` (~400MB)
- (วางบน SSD จะโหลดเร็วกว่า HDD มาก — ถ้ายังไม่มี SSD ก็วางบน HDD ได้ แค่โหลดช้าหน่อย)

---

## 2. เช็กว่า llama.cpp เห็น GPU ไหน

เปิด PowerShell ที่ `C:\llama` แล้วรัน:
```powershell
.\llama-cli.exe --list-devices
```
ควรเห็นรายการ Vulkan device เช่น:
```
Vulkan0: Intel(R) HD Graphics 520
Vulkan1: AMD Radeon (TM) 520
```
จำเลขตัว **AMD** ไว้ (สมมติ `Vulkan1`) — เราจะบังคับใช้ตัวนี้

> ถ้าไม่เห็น AMD เลย = ไดรเวอร์ Vulkan ของ Radeon 520 ยังไม่พร้อม → กลับไปข้อ 1.1

---

## 3. วัดผล (หัวใจของการทดลอง)

ใช้ `llama-bench` วัด **tokens/sec** 3 แบบ เทียบกัน — รันทีละคำสั่ง จดเลข `tg` (text generation t/s) ที่มันพิมพ์ออกมา

### 3.1 CPU ล้วน (ฐานอ้างอิง)
```powershell
.\llama-bench.exe -m .\models\qwen2.5-coder-0.5b-instruct-q4_k_m.gguf -ngl 0
```
`-ngl 0` = ไม่ offload ขึ้น GPU เลย → นี่คือความเร็ว CPU ล้วน **จดค่า tg ไว้**

### 3.2 Offload บางส่วนขึ้น AMD Radeon 520
```powershell
$env:GGML_VK_VISIBLE_DEVICES = "1"   # เลข AMD จากข้อ 2 (ถ้า AMD = Vulkan1)
.\llama-bench.exe -m .\models\qwen2.5-coder-0.5b-instruct-q4_k_m.gguf -ngl 15
```
`-ngl 15` = ยก 15 layer ขึ้น GPU (0.5b มี ~24 layer) — 2GB น่าจะรับไหวราวนี้ **จดค่า tg**

### 3.3 Offload เยอะสุดเท่าที่ 2GB ไหว
```powershell
.\llama-bench.exe -m .\models\qwen2.5-coder-0.5b-instruct-q4_k_m.gguf -ngl 24
```
ถ้าขึ้น error `out of memory` = 2GB ไม่พอทั้งโมเดล → ลดเลข `-ngl` ลง (ลอง 20, 18, 16…) จนไม่ error **จดค่า tg ที่ดีสุด**

---

## 4. อ่านผล → ตัดสินใจ

เทียบ `tg` (t/s) ของ 3.1 กับ 3.2/3.3:

| ผล | แปลว่า | ทำไง |
|---|---|---|
| GPU **เร็วกว่า** CPU ชัดเจน (เช่น +30%↑) | offload ช่วยจริง | ใช้ `-ngl N` ตัวที่ดีสุดเป็นค่าตั้งต้น |
| **พอๆ กัน** (±10%) | ไม่ต่าง | ใช้ CPU ล้วนง่ายกว่า ไม่ต้องยุ่ง GPU |
| GPU **ช้ากว่า** | GPU อ่อนเกิน/bus เป็นคอขวด | CPU ล้วนคือคำตอบ — ปิดเรื่องนี้ได้ |

> จดตัวเลขจริงมาให้ผมดูได้ เดี๋ยวช่วยวิเคราะห์ว่าค่าที่ได้ perfectหรือมีอะไรปรับได้อีก

---

## 5. ถ้าอยากใช้งานจริง (ไม่ใช่แค่ bench)

ถ้าผลข้อ 4 บอกว่า GPU ช่วย → เปิดใช้งานแบบแชตได้ด้วย `llama-server` (API เข้ากันได้กับ OpenAI/บางส่วนของ Ollama):
```powershell
$env:GGML_VK_VISIBLE_DEVICES = "1"
.\llama-server.exe -m .\models\qwen2.5-coder-0.5b-instruct-q4_k_m.gguf -ngl 15 --port 11500
```
เปิด `http://127.0.0.1:11500` — เป็นหน้าแชตของ llama.cpp เอง (คนละตัวกับ LCA server 8420)

> หมายเหตุ: LCA (`server.py`) ตอนนี้ต่อกับ **Ollama** ที่ port 11434 — ถ้าจะให้ LCA ใช้ llama.cpp แทน เป็นงานต่อยอด (เปลี่ยน endpoint ใน `call_ollama`) ไว้คุยทีหลังถ้าผลคุ้ม

---

## 6. ตัวช่วยจำ (ของที่อาจพลาด)

- **ลืม `-ngl`** → ไม่ offload เลย (เท่า CPU)
- **`out of memory`** → ลด`-ngl` ลง (2GB เล็ก)
- **ไม่เห็น AMD ใน `--list-devices`** → ไดรเวอร์ Vulkan ยังไม่พร้อม
- **เผลอใช้ Intel HD 520 แทน AMD** → เช็ก `GGML_VK_VISIBLE_DEVICES` ให้ตรงเลข AMD
- **HDD ช้าตอนโหลด** → ปกติของจานหมุน ไม่ใช่ error (SSD แก้ได้)

---

## สรุป

llama.cpp Vulkan = ทางเดียวที่ Radeon 520 แตะ LLM ได้ — แต่ **ต้องวัดก่อนถึงจะรู้ว่าคุ้มไหม**
ทำข้อ 3 (bench 3 แบบ) แล้วเอาตัวเลขมาคุยกัน จะได้ตัดสินด้วยข้อมูลจริง ไม่ใช่เดา

*ภาคผนวกของ RESOURCE_MANAGER_DESIGN.md — ส่วนทดลอง GPU สำหรับเครื่องสเปกต่ำ*
