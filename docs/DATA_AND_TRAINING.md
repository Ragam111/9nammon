# LCA — เก็บข้อมูล แล้วเทรน (Collect → Train)

เป้าหมาย: ทำให้ LCA เก่งขึ้นด้วยข้อมูลการใช้งานจริง **แบบที่ทำได้จริงบนเครื่อง 8GB**

## ความจริงก่อน (สไตล์ 9arm — ไม่ขายฝัน)
**เทรน/fine-tune โมเดลภาษาบน HP 8GB + iGPU นี้ "ทำไม่ได้"** — RAM ไม่พอโหลด weight
ด้วยซ้ำ, ไม่มี CUDA/ROCm. เหมือนจะเข็นรถบรรทุกขึ้นเขาด้วยมอเตอร์ไซค์

เพราะงั้นแยกเป็น **2 เฟส**:

```
[เฟส 1: เก็บ — บนเครื่องนี้ ✓]           [เฟส 2: เทรน — บน cloud GPU เช่าชั่วโมง]
chat/ฟีดแบ็กดี ๆ -> dataset.db   --export-->   lca_dataset.jsonl -> fine-tune -> GGUF -> ollama create
```

## เฟส 1 — เก็บ (ทำได้เลยบนเครื่อง)
มีแล้วใน repo: `app/dataset_store.py` + endpoint (gate ADMIN)

**เก็บอัตโนมัติจากการแชต** (ปิดเป็นค่าเริ่มต้นเพื่อความเป็นส่วนตัว):
- เปิดโดยใส่ใน `config.json`: `"COLLECT_TRAINING_DATA": "1"`
- ⚠️ เก็บบทสนทนาผู้ใช้ไปเทรน **ต้องขอความยินยอม** ก่อน (บอกผู้ใช้ให้ชัด) — อย่าเปิดเงียบ ๆ

**เก็บ/จัดการด้วยมือ** (เลือกเฉพาะตัวอย่างดี ๆ — คุณภาพสำคัญกว่าปริมาณ):
```bash
# เพิ่มตัวอย่างดี ๆ เอง (ให้ rating 1-5)
curl -X POST $URL/api/admin/dataset -H "X-Auth-Token: $TOK" \
  -d '{"prompt":"เขียน for loop","response":"for i in range(10): ...","rating":5}'

# ดูจำนวน/รายการ
curl $URL/api/admin/dataset -H "X-Auth-Token: $TOK"

# export เป็น JSONL พร้อม fine-tune (กรองเอาเฉพาะ rating สูง)
curl "$URL/api/admin/dataset/export?fmt=messages&min_rating=4" -H "X-Auth-Token: $TOK" -o lca_dataset.jsonl
```
รูปแบบ export: `messages` (chat `{"messages":[{user},{assistant}]}`) หรือ `alpaca` (`{instruction,input,output}`)

## เฟส 2 — เทรน (บน cloud GPU ไม่ใช่เครื่องนี้)
พอได้ `lca_dataset.jsonl` มาพอ (เอาคุณภาพ ~หลายร้อย–พันตัวอย่างที่ดีจริง) ค่อยเช่า GPU:
1. เช่า cloud GPU เป็นชั่วโมง (เช่น 1x GPU 24GB) — ถูกกว่าซื้อการ์ด
2. **LoRA/QLoRA fine-tune** โมเดลฐานตัวเล็ก (เช่น Qwen2.5-Coder 1.5B/3B) ด้วย jsonl นี้ —
   LoRA ใช้ VRAM น้อย เทรนไม่กี่ชั่วโมงก็เห็นผล
3. แปลงผลเป็น **GGUF** (llama.cpp) แล้วเอากลับมาที่เครื่อง
4. `ollama create my-lca -f Modelfile` (ชี้ไป GGUF) → เสิร์ฟผ่าน LCA เหมือนเดิม

## ทางเลือกที่ "ไม่ต้องเทรน" แต่ได้ผลเร็วบน 8GB (แนะนำเริ่มจากอันนี้)
เทรนแพง/ช้า — ก่อนจะถึงจุดนั้น ใช้ข้อมูลที่เก็บแบบนี้ก่อน ได้ผลทันทีบนเครื่องนี้:
- **Few-shot / system prompt**: เอาตัวอย่างดี ๆ 5-10 อัน ยัดเป็นตัวอย่างใน system prompt
- **RAG**: เก็บโค้ด/เอกสารของเราเป็นฐานความรู้ แล้วดึงมาแปะ context ตอนถาม (ยังไม่ได้ทำ — เป็น backlog ได้)
ส่วนใหญ่ "ทำให้ตอบตรงงานเรา" ได้จาก 2 อันนี้ โดยไม่ต้องเทรนเลย

## สรุปเส้นทาง
1. เปิดเก็บข้อมูล (auto แบบ consent หรือคัดมือ) → สะสม dataset คุณภาพ
2. เริ่มจาก few-shot/RAG ก่อน (ฟรี เร็ว บน 8GB)
3. พอข้อมูลเยอะ + มีงบ → เช่า GPU fine-tune (LoRA) → GGUF → ollama → เสิร์ฟ
4. วัดผลก่อน-หลังด้วยการใช้จริง (อย่าเทรนเพราะ "อยากเทรน" — เทรนเมื่อ few-shot/RAG ไม่พอ)
