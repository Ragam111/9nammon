# แผนสร้าง AI Agent สายเทค (coding + devops) — สเกล 3,000 งาน/วัน

> เอกสารออกแบบ ไม่ใช่โค้ด — วางแผนก่อนลงมือ (ปรัชญาเดิม: วัดก่อนเชื่อ, ทำทีละขั้น, ซื่อตรง)
> อัปเดต: 2026-10-24

## 1. เป้าหมาย
Agent ที่ "ลงมือทำงานเทคได้เอง" 2 สาย รวมกัน:
- **Coding**: อ่าน repo → วางแผน → แก้/เขียนโค้ด → รันเทส → สรุป/เปิด PR
- **DevOps**: ตอบคำถามระบบ → รันคำสั่งตรวจสอบ (allowlist) → อ่าน log/เมตริก → แจ้งเตือน

เป้าหมายปริมาณ: **รองรับ 3,000 งาน/วัน** อย่างเสถียร ปลอดภัย และวัดผลได้

---

## 2. วิเคราะห์สเกล 3,000 งาน/วัน (ทำก่อน — ตัวเลขกำหนดสถาปัตยกรรม)

### 2.1 อัตราเฉลี่ย
- 3,000 งาน ÷ 24 ชม. = **125 งาน/ชม. = ~1 งานทุก 29 วินาที** (เฉลี่ย)
- แต่จริงมักกระจุก (เวลางาน) — ออกแบบเผื่อ **peak ~3-5 เท่า = ~6-10 งาน/นาที**

### 2.2 เวลาต่องาน (ประมาณการ — ต้องวัดจริงภายหลัง)
งาน agent 1 งาน = หลาย step (คิด→เรียก tool→คิดต่อ). สมมติ:
- งานเล็ก (ตอบ/ตรวจ): ~30 วิ, 2-3 step
- งานกลาง (แก้โค้ด+เทส): ~3-8 นาที, 5-15 step
- งานใหญ่ (ฟีเจอร์): ~15-30 นาที, 20+ step

ถ้าเฉลี่ย **5 นาที/งาน**: 3,000 × 5 = **15,000 นาที-งาน/วัน = 250 ชม.-งาน/วัน**
→ ต้องมี **ความขนาน (concurrency) อย่างน้อย ~10-11 งานพร้อมกัน** ตลอด 24 ชม.
   (250 ชม.-งาน ÷ 24 ชม. ≈ 10.4) — และเผื่อ peak ต้องได้ ~20-30 พร้อมกัน

### 2.3 คอขวดจริงอยู่ที่ไหน (ซื่อตรง)
1. **LLM throughput (คอขวดหลัก)** — เครื่องเดียว ~10 tok/s ทำงานขนาน 10-30 ตัว *ไม่ไหว*
   (RAM ไม่พอ + swap ลง HDD = ค้าง ตามที่พิสูจน์มาแล้ว). นี่คือเหตุผลที่ต้องมี **cluster
   + cloud LLM backend** (ทำ adapter ไว้แล้ว: model_backend + cluster_forward)
2. **เน็ต** — ถ้าใช้ cloud LLM: 3,000 งาน × หลาย call × หลาย KB = ปริมาณพอควร แต่ไม่ใช่คอขวด
   เท่า latency ต่อ call (ตอบช้า = งานค้างคิว). วัด round-trip ก่อนเลือก provider
3. **Disk/IO ของ workspace** — 3,000 งานโคลน/อ่านไฟล์ ถ้าใช้ HDD จะช้า → ควร SSD หรือ tmpfs
4. **คิว + admission** — ต้องมีคิวจริง (ไม่ใช่รับทุกงานพร้อมกันจนล่ม) — ของนี้มี job_queue + admission แล้ว

### 2.4 สรุปสถาปัตยกรรมที่ตัวเลขบังคับ
> งานเดียว 3,000/วัน = **ต้องเป็นระบบคิว + หลาย worker + หลาย node/cloud** ตั้งแต่ออกแบบ
> ไม่ใช่ agent loop เดี่ยวๆ. โชคดีที่ LCA วางฐานไว้ครบแล้ว (queue, cluster, admission, adapter)

---

## 3. สถาปัตยกรรม

```
                         ┌─────────────────────────────┐
  งานเข้า (API/นัดเวลา) → │  Job Queue (SQLite, มีแล้ว)   │
                         └───────────────┬─────────────┘
                                         │ dispatcher ดึงงาน (ตาม admission)
                         ┌───────────────▼─────────────┐
                         │  Agent Workers (N ตัวขนาน)   │  ← concurrency gate
                         │  แต่ละตัวรัน agent loop       │
                         └───────┬───────────────┬──────┘
                        coding   │               │  devops
                         ┌───────▼──────┐  ┌─────▼───────┐
                         │ Tool Registry│  │ Tool Registry│  (sandbox + allowlist)
                         └───────┬──────┘  └─────┬───────┘
                                 │ LLM call       │
                         ┌───────▼────────────────▼──────┐
                         │ model_backend (adapter, มีแล้ว)│
                         │  local Ollama / cloud / cluster│ ← cluster_forward (มีแล้ว)
                         └────────────────────────────────┘
```

องค์ประกอบใหม่ที่ต้องสร้าง (ตัวหนา = ยังไม่มี):
- **`app/agent/core.py`** — agent loop (think→tool→observe→วน, จำกัด max_steps, log ทุก step)
- **`app/agent/tools.py`** — tool registry + sandbox (read_file/list_dir/run_command allowlist/web_search)
- **`app/agent/worker.py`** — ดึงงานจาก job_queue → รัน agent loop → เก็บผล (เชื่อม admission เดิม)
- **`app/agent/profiles.py`** — บุคลิก/ชุด tool ต่อสาย (coding vs devops)
- endpoint: `POST /api/agent/jobs` (สร้างงาน), `GET /api/agent/jobs/<id>` (ผล+log)

ของเดิมที่ reuse (ไม่สร้างใหม่): `job_queue`, `admission`, `model_backend`, `cluster_forward`,
`org_store` (RBAC), `space_store`, `config_versions`, `notifier`, `usage_store`

---

## 4. ความปลอดภัย (สำคัญสุด — 3,000 งาน/วันที่ทำผิดได้ = ความเสี่ยงสูง)
1. **Sandbox tool `run_command`**: allowlist คำสั่ง, timeout ต่อคำสั่ง, จำกัด cwd ใน workspace
   ของงานนั้น, ห้าม network เว้นแต่ tool `web_search` ที่คุมไว้, ห้ามลบนอก workspace
2. **ขออนุมัติก่อนทำสิ่งย้อนไม่ได้**: push/ลบ/deploy → ค้างรอคนกดยืนยัน (ไม่ auto) — ตามที่พี่ย้ำ
3. **RBAC**: สร้างงาน = USER+, ดูงานคนอื่น = ADMIN+, ตั้งค่าระบบ = CEO (master token/ไททัน)
4. **แยก workspace ต่องาน**: งานละโฟลเดอร์ ลบทิ้งเมื่อจบ (กันข้อมูลปนข้ามงาน/ข้ามคน)
5. **test + rollback ก่อนปล่อย**: ใช้ config_versions ที่มี — snapshot ก่อน, ย้อนได้ถ้าพัง
   (จำกัดความเสียหายจาก zero-day/incident)
6. **budget/quota ต่อผู้ใช้**: 3,000 งานต้องมีเพดานต่อ key กัน abuse (usage_store มีฐานแล้ว)
7. **log ทุก step ตรวจสอบย้อนหลังได้** (history_store) — รู้ว่า agent ทำอะไรไปบ้าง

---

## 5. Phases (ทำทีละขั้น วัดผลทุกขั้น)

| Phase | สิ่งที่ได้ | เกณฑ์ผ่าน |
|---|---|---|
| **P1 แกน loop** | `agent/core.py` + tool registry + 3 tool พื้นฐาน (read/list/run allowlist) + เทส | agent คิดเป็นขั้น เรียก tool ได้ จบใน max_steps (echo backend ก็เทสได้) |
| **P2 สาย coding** | tool: patch file, run tests, git diff; profile coding | ทำโจทย์แก้บั๊กจิ๋วใน repo ตัวอย่างได้จริง 1 งาน |
| **P3 สาย devops** | tool: ตรวจระบบ (sysinfo มีแล้ว), อ่าน log, แจ้งเตือน; profile devops | ตอบ+ตรวจระบบจริง 1 งาน |
| **P4 คิว+worker** | `agent/worker.py` ต่อ job_queue + admission + endpoint | รันงานจากคิวขนานได้ N ตัว ไม่ล่ม |
| **P5 สเกล+cluster** | ต่อ cluster_forward/cloud backend + budget/quota | **วัด throughput จริง**: ไต่ถึงเป้า/เห็นคอขวด |
| **P6 approval+rollback** | gate อนุมัติงานย้อนไม่ได้ + snapshot/rollback | push/deploy ต้องคนยืนยัน, ย้อนได้ |

---

## 6. วัดผล (benchmark — ซื่อตรงแบบ BENCHMARK_RESULTS.md)
วัดจริงก่อนเคลม ไม่เดา:
- **เวลา/งาน** เฉลี่ย + p95 (แยกตามสายและขนาดงาน)
- **concurrency สูงสุดที่เครื่อง/คลัสเตอร์รับไหว** ก่อน RAM thrash (ไต่ทีละขั้น)
- **throughput จริง/วัน** = concurrency × (86400 ÷ เวลาต่องาน) → เทียบเป้า 3,000
- **อัตราสำเร็จ** (งานจบถูกต้อง ÷ งานทั้งหมด) + สาเหตุที่ fail
- จากตัวเลขนี้ค่อยตอบว่า "ต้องกี่ node / cloud quota เท่าไร" ถึงจะได้ 3,000/วันจริง

---

## 7. ความเสี่ยง + สิ่งที่ยังไม่ทำ (ซื่อตรง)
- **เครื่องเดียวไม่พอแน่** สำหรับ 3,000/วัน — ต้องมี node เพิ่ม หรือ cloud LLM (ต้นทุน $)
  → P5 จะวัดให้เห็นตัวเลขจริงก่อนตัดสินใจลงเงิน
- agent ยังพลาดได้ (hallucination) → ความปลอดภัย P1,P6 คือกันความเสียหาย ไม่ใช่กันพลาด
- ตัวเลขเวลา/งานในเอกสารนี้เป็น **ประมาณการ** — P1-P4 จะได้ตัวเลขจริงมาแทน
- ยังไม่รวม: multi-agent (หลาย agent คุยกัน), fine-tune โมเดลเฉพาะงาน — ไว้หลังพิสูจน์ P1-P5

---

## 8. ขั้นถัดไปทันที
เริ่ม **P1** (agent loop + tool registry + sandbox + เทส) — echo backend ก่อน ยังไม่ต้องมี LLM จริง
ก็เห็น agent คิดเป็นขั้นและเรียก tool ได้ พอ P1 ผ่านค่อยต่อ P2
