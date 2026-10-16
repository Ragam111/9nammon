# Design Doc — Brain-Inspired Resource Manager (LCA บนเครื่อง 8GB)

> สถานะ: **แผน (ยังไม่ลงมือ)** — ร่างไว้อ่านช่วงพัก พร้อมลงมือวันจันทร์
> เป้าหมาย: ให้ LCA รันลื่นที่สุดเท่าที่ฮาร์ดแวร์ไหว บนโน้ตบุ๊ก Intel U-series + RAM 8GB
> โดย **ไม่แตะฮาร์ดแวร์** — แก้ที่ซอฟต์แวร์ล้วน

---

## 0. ที่มา (วิสัยทัศน์ของ Nammon → ชื่อจริงในวงการ)

Nammon วาดสถาปัตยกรรมเป็น "สมอง": เซลล์ประสาทหลายเซลล์เชื่อมเป็นก้อน ส่งสัญญาณ
(input/process/output) จัดการพลังงานเอง และซ่อม/อัปเกรดตัวเองได้. ไอเดียนี้ตรงกับ
concept จริงหลายอัน — doc นี้แปลงมันเป็นสถาปัตยกรรมซอฟต์แวร์ที่ลงมือสร้างได้จริง

| คำของ Nammon | ชื่อจริง | สถานะในโค้ด |
|---|---|---|
| เซลล์เชื่อมกัน ส่งสัญญาณ I/O | Message-passing / modular architecture | ✅ มีแล้ว (server + API + stores) |
| คุมพลังงานไม่ให้เกิน | Resource budgeting / working-set management | ❌ **ชิ้นที่จะสร้าง** |
| ก้อนใหญ่ แต่จุดไฟบางส่วน | Mixture-of-Experts (MoE) / sparse activation | — (concept อ้างอิง) |
| เซลล์พัง → สร้างใหม่ดีกว่า ทิ้งเก่า | Self-healing + collect→train→swap | ✅ รางวางครึ่งทาง (dataset_store) |

**ขอบเขตตามจริง (9arm honesty):** เครื่องนี้ **รัน** โมเดลเล็กได้ แต่ **เทรนไม่ได้**
(VRAM/compute ไม่พอ) — การ "สร้างเซลล์ที่ดีกว่า" (เทรนโมเดลใหม่) ต้องทำบน GPU เช่า
แล้วค่อยเอากลับมา swap. doc นี้โฟกัสที่ฝั่ง **รัน + จัดการทรัพยากร** ซึ่งทำเองในเครื่องได้

---

## 1. หลักการออกแบบ (เทียบสมอง ↔ ระบบ)

```
สมอง (metaphor)          ระบบจริง (LCA)
─────────────────        ──────────────────────────────
เซลล์ / นิวรอน       →   module (ollama / web / dataset / support ...)
กระแสไฟฟ้า/สัญญาณ    →   HTTP + JSON ระหว่าง server กับ module
พลังงาน (ไม่ให้ล้า)  →   RAM budget (8GB) — หัวใจของ doc นี้
จุดไฟเฉพาะที่ใช้     →   lazy load: เปิด module/model เมื่อใช้เท่านั้น
เซลล์พัง → ซ่อม      →   health check + graceful degradation
เซลล์ใหม่ดีกว่า      →   model versioning (collect→train บน cloud→swap)
```

**กฎเหล็ก 3 ข้อ (ยึดตอน implement):**
1. **Correctness ก่อน optimize** — ระบบต้องไม่พังก่อน ค่อยทำให้เร็ว/ประหยัด
2. **Degrade อย่าcrash** — RAM ไม่พอ → ถอยไปโมเดลเล็กลง/ปิด feature ไม่ใช่ล่มทั้งระบบ
3. **stdlib-only + psutil** — ไม่เพิ่ม dependency ใหม่ (คงคอนสเตรนต์โปรเจกต์)

---

## 2. สิ่งที่มีอยู่แล้ว (ไม่ต้องสร้างซ้ำ)

- **`sysmanager/sysinfo.py`** → `get_system_info()` : สเปกเครื่อง (RAM รวม, CPU, GPU)
- **`sysmanager/monitor/`** → `collect()`, `Analyzer`, `Report` : snapshot + วิเคราะห์ RAM/CPU/swap
- **`sysmanager/monitor/lca_context.py`** → `correlate(report)` : รู้ว่า Ollama รันไหม,
  กิน RAM เท่าไหร่ (`ollama_rss`, `ollama_mem_percent`), `memory_pressure` (bool), `note`
- **`app/config_manager.py`** → `get_key()`/`set_key()` : อ่าน/เขียน config.json ต่อโปรเจกต์
- **`server.py`** → `call_ollama()`, `/api/metrics` (ADMIN) ส่ง snapshot+verdict+findings+lca สด
- **`app/dataset_store.py`** → เก็บตัวอย่างไว้เทรน (= ฝั่ง self-improve)
- **ตรรกะเลือกโมเดลตาม RAM** — ตอนนี้อยู่ใน `install.ps1`/`install.sh` (ฝังตอนติดตั้ง
  ครั้งเดียว) ยังไม่ได้ตัดสินใจ "ตอนรัน" ตาม RAM ว่างจริง ← จุดที่ต้องยกมาทำใหม่

**สรุป: เรามีตา (monitor) และสมองรับรู้ (lca_context) แล้ว — ขาด "ก้านสมอง" ที่เอา
ข้อมูลพวกนี้มาตัดสินใจอัตโนมัติ**

---

## 3. ชิ้นที่จะสร้าง (3 โมดูล)

### 3.1 `app/resource_budget.py` — ตัวคุมพลังงาน (แกนหลัก) 🧠

หน้าที่: ดู RAM ว่างจริง ณ ตอนนั้น แล้วบอกว่า "เครื่องนี้ไหวโมเดลขนาดไหน"

```python
# ขนาดโดยประมาณของโมเดล quantized (bytes) — ปรับได้
MODEL_FOOTPRINT = {
    "qwen2.5-coder:0.5b": 0.6 * GB,
    "qwen2.5-coder:1.5b": 1.2 * GB,
    "qwen2.5-coder:7b":   5.0 * GB,
}
HEADROOM = 1.5 * GB   # กันไว้ให้ OS + เบราว์เซอร์ + web server

def available_ram() -> int:
    """RAM ว่างจริง (bytes) — ใช้ psutil.virtual_memory().available"""

def pick_model(preferred: str | None = None) -> dict:
    """เลือกโมเดลใหญ่สุดที่ 'footprint + HEADROOM <= available_ram'
    - ถ้า preferred ใส่ได้ → ใช้ preferred
    - ไม่งั้นถอยลงทีละขั้น (7b → 1.5b → 0.5b)
    คืน {model, reason, available_ram, fits}"""

def budget_report() -> dict:
    """ภาพรวมงบ RAM: ว่างเท่าไหร่, โมเดลไหนใส่ได้/ไม่ได้, แนะนำตัวไหน
    (เอาไปโชว์หน้า /dev ได้)"""
```

- **ไม่โหลดโมเดลเอง** — แค่ "ตัดสินใจ/แนะนำ" (เบา ปลอดภัย เทสง่าย)
- เทสต์: mock `available_ram()` คืนค่าต่างๆ แล้วเช็ก `pick_model` เลือกถูกชั้น

### 3.2 Health check + graceful degradation — ตัวซ่อมตัวเอง

หน้าที่: ถ้า "เซลล์" (module/service) พัง ให้ระบบถอยอย่างนุ่มนวล ไม่ล่มทั้งก้อน

- **Ollama ตาย** → `/api/chat` ตอบ 503 + ข้อความชัด ("เครื่องยนต์ยังไม่เปิด — รัน
  `ollama serve`") แทนที่จะ error ยาวเหยียด (บางส่วนมีแล้วใน `call_ollama` — ทำให้
  คมขึ้น + เช็กก่อนเรียกด้วย `lca_context`/ping `localhost:11434`)
- **RAM pressure** (`lca_context.correlate().memory_pressure == True`) → `/api/chat`
  แนบ `warning` ใน response ว่า "RAM กำลังตึง แนะนำสลับโมเดลเล็กลง" + ลิงก์วิธี
- **module ใด error** → isolate ที่ route นั้น (ตอนนี้ server จับ `ValueError`/`OSError`
  ราย handler อยู่แล้ว — เพิ่ม health endpoint รวม)

เพิ่ม route: **`GET /api/health`** (ไม่ต้อง auth) คืน
```json
{"ok": true, "ollama": "up|down", "ram_pressure": false,
 "recommended_model": "qwen2.5-coder:1.5b"}
```
= "สัญญาณชีพของสมอง" ดูได้ทันทีว่าเซลล์ไหนยังไหว

### 3.3 เชื่อมเข้า `/dev` + chat — ให้คนเห็น/ระบบใช้จริง

- **หน้า `/dev`**: การ์ดใหม่ "งบ RAM (Resource Budget)" โชว์ `budget_report()` — ว่างเท่าไหร่,
  โมเดลไหนไฟเขียว/ไฟแดง, แนะนำตัวไหน (ใช้ meter component ที่มีใน app.css แล้ว)
- **หน้า chat `/`**: dropdown เลือกโมเดล เติม badge "แนะนำ" ข้างตัวที่ `pick_model` เลือก
  + ถ้าเลือกตัวที่ใหญ่เกิน RAM ว่าง → เตือนก่อนส่ง
- ทั้งหมดดึงจาก **`GET /api/health`** + **`GET /api/metrics`** (มีอยู่แล้ว)

---

## 4. แผนลงมือวันจันทร์ (เรียงตามลำดับ แต่ละข้อ = 1 PR, auto-merge เมื่อ CI เขียว)

| # | งาน | ไฟล์ | ทำไมก่อน-หลัง |
|---|---|---|---|
| 0 | **ลง Ollama ให้จบ** (serve + pull 0.5b) | (เครื่อง Nammon) | ต้องมี "สมอง" ให้จัดการก่อน |
| 1 | `resource_budget.py` + เทสต์ | `app/resource_budget.py`, `tests/` | แกนหลัก ไม่พึ่งใคร ทำก่อน |
| 2 | `GET /api/health` ใช้ budget + lca_context | `server.py`, `tests/` | เอา #1 มาต่อเป็น endpoint |
| 3 | การ์ด Resource Budget ใน `/dev` | `app/dev.html` | ให้เห็นด้วยตา |
| 4 | badge "แนะนำ" + เตือน RAM ในหน้า chat | `app/index.html` | ให้ผู้ใช้ทั่วไปได้ประโยชน์ |
| 5 | graceful degradation ใน `call_ollama` | `server.py`, `tests/` | ทำ "ซ่อมตัวเอง" ให้คม |

> แต่ละ PR เล็ก เทสต์ครบ ผ่าน CI (unittest) ก่อน merge — ตามแพทเทิร์น autopilot เดิม
> ผม (cloud) เขียน+เทสต์+merge ให้ได้โดย Nammon ไม่ต้องเปิดเครื่อง เหลือแค่ `git pull` วันจันทร์

---

## 5. สิ่งที่ "ไม่ทำ" ใน doc นี้ (กันหลงทาง)

- ❌ ไม่ทำ MoE จริง (นั่นคือสถาปัตยกรรมภายในตัวโมเดล — เราใช้โมเดลสำเร็จจาก Ollama)
- ❌ ไม่เทรนโมเดลในเครื่อง (ฮาร์ดแวร์ไม่ไหว — เทรน = เช่า GPU แยกเฟส)
- ❌ ไม่แตะ K600/riser (คนละเรื่อง — ถ้าอยากลองเป็น learning project ค่อยแยกคุย)
- ❌ ไม่เพิ่ม dependency นอก stdlib+psutil

---

## 6. เฟสถัดไป (หลัง resource manager เสร็จ — ไว้คุยทีหลัง)

1. **collect → train → swap loop** ให้ครบวง: ปุ่ม export dataset → runbook เทรนบน
   GPU เช่า (RunPod/Vast.ai) → `ollama create` โมเดลใหม่ → เลือกในหน้า chat
   = "สร้างเซลล์ที่ดีกว่า แล้ว swap" ตามที่ Nammon วาดไว้
2. **Auto model-switch**: ถ้า RAM pressure ต่อเนื่อง ให้ระบบ "แนะนำสลับอัตโนมัติ"
   (ยังให้คนกดยืนยัน — ไม่สลับเงียบๆ กันเซอร์ไพรส์)

---

*doc นี้เป็นแผน ไม่ใช่โค้ดที่รันแล้ว — ตัวเลข footprint/HEADROOM เป็นค่าเริ่มต้นสำหรับ
จูนจริงตอน implement วันจันทร์*
