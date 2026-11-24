# V1: โมเดลในเครื่องฟรี (Ollama) ก่อน

สถานะ: ร่างสำหรับตรวจ ยังไม่มีการชำระเงิน ยังไม่มีแพ็กโทเคน และยังไม่เก็บ key ของลูกค้า

## เป้าหมาย v1
- ลูกค้าคุยกับโมเดลในเครื่องได้ฟรี โดยไม่ต้องมี API key และไม่มีค่าใช้จ่าย cloud
- โมเดลรันบน Ollama ที่ `127.0.0.1` เท่านั้น ตาม [backend/app/local_provider.py](backend/app/local_provider.py)
- โควตาโมเดลในเครื่องแยกจาก cloud (`local_five_hour`, `local_weekly`) ตาม [backend/app/quota.py](backend/app/quota.py)

## สิ่งที่มีอยู่แล้วในโค้ด
- Catalog: `qwen2.5-coder:1.5b` (RAM ที่ต้องใช้ 2.0 GB เป็นค่าตั้งต้น ยังไม่ได้วัด)
- สถานะโมเดล: `ready`, `not_installed`, `not_enough_memory`, `unreachable`, `not_configured`
- `GET /api/chat/local/health` บอกว่า Ollama ตอบหรือไม่ มีโมเดลอะไร และ RAM ว่างเท่าไร
- ส่งข้อความแบบ local ไม่ใช้ cloud key และไม่ตัดโควตา cloud
- ปิดอยู่ตามค่าเริ่มต้น: `LOCAL_MODELS_ENABLED` ค่าเริ่มต้นคือ `false`

## วิธีเปิดสำหรับทดสอบ (เครื่องเดียว)
```powershell
ollama pull qwen2.5-coder:1.5b
$env:LOCAL_MODELS_ENABLED = "true"
```
ตั้งค่าใน `backend/.env` ได้ด้วย ห้ามใส่ key จริงลงไฟล์ที่ commit

## นอกขอบเขต v1
- แพ็กโทเคนซื้อเพิ่ม การชำระเงิน และการคืนเงิน
- LCA coder ที่ลูกค้าใส่ API key ของตัวเอง
- การเปิดให้คนนอก LAN เข้าถึง (ตกลงไว้ว่าต้องอยู่ LAN ก่อน)

## ข้อที่ยังต้องตัดสิน
1. แพ็กโทเคน: ขนาดแพ็ก ราคา อายุของแพ็ก
2. ผู้ให้บริการชำระเงินและนโยบายคืนเงิน
3. LCA coder key: เป็นของผู้ใช้แต่ละคน (เข้ารหัส แยกต่อผู้ใช้) หรือของ server ทั้งระบบ
4. การใช้ key ของลูกค้าเอง นับโควตาหรือไม่

## งานค้างที่ทราบจาก review รอบ P6 (ยังไม่แก้)
- คำอธิบาย provider บอกว่า base URL คงที่ แต่ port ถูกรับจาก constructor
- `_installed_tags` ไม่มีเพดานขนาดและไม่มี cache
- turn ของโมเดลในเครื่องถูก log ด้วยค่าใช้จ่ายประมาณการของ cloud (`COST_PER_1K_TOKENS` ค่าเริ่มต้น 0)
- `reasonFor()` แสดงข้อความของ cloud API key กับแถว local ที่สถานะ `not_configured`
- `onboardingLocal` แสดง "Ollama not found" ทั้งที่ฟีเจอร์ปิดอยู่
- `LOCAL_MODELS_ENABLED` ยังไม่อยู่ใน `.env.example`

## เกณฑ์ว่า v1 ใช้ได้จริง
- เทสต์ local ทั้งชุดผ่าน (`test_local_provider`, `test_local_routes`, `test_local_send`, `test_local_health`)
- เปิด Ollama แล้วโมเดลขึ้นสถานะ `ready` และตอบได้ 1 ข้อความจบ
- ปิด Ollama แล้วโมเดลขึ้นสถานะ `unreachable` และไม่ทำให้หน้าแชตพัง
- ยังไม่วัดเวลาตอบจริงและ RAM ที่ใช้จริง จึงยังไม่มีตัวเลขยืนยัน
