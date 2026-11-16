# LCA v0.0.2 — Test Plan & Results

รันด้วย: `python3 -m unittest discover -s tests -v` (จาก root ของ `windows-package/`)
**ผลล่าสุด: 34/34 PASS, 0 FAIL, 0 error (0.569s)**

## Test Matrix

| Area | Test File | Input | Expected Result | Actual Result | PASS/FAIL |
|---|---|---|---|---|---|
| Config | `test_config.py` | ไม่มี config.json/env var | คืน `None` | `None` | PASS |
| Config | `test_config.py` | set_key แล้ว get_key | ค่าตรงกัน | ตรงกัน | PASS |
| Config | `test_config.py` | มีทั้ง config.json และ env var | config.json ชนะ | config.json ชนะ | PASS |
| Config | `test_config.py` | มีแค่ env var | fallback ไป env var | fallback ถูกต้อง | PASS |
| Config | `test_config.py` | config.json เสีย (invalid JSON) | ไม่ crash, คืน None | ไม่ crash | PASS |
| Config | `test_config.py` | list_configured_keys | คืนแค่ชื่อ key ไม่คืนค่า | ไม่มีค่าจริงหลุดออกมา | PASS |
| Context | `test_context.py` | ไฟล์ระบบ (todos.json ฯลฯ) | ถูก ignore เสมอ | ถูก ignore | PASS |
| Context | `test_context.py` | `.lcaignore` pattern กำหนดเอง | ไฟล์ตรง pattern ถูกกรอง | กรองถูกต้อง | PASS |
| Context | `test_context.py` | ไฟล์เกิน MAX_FILE_SIZE_BYTES | ถูกข้ามจาก auto-context | ถูกข้าม | PASS |
| Context | `test_context.py` | ไฟล์ที่ /add ไว้แล้ว (manual) | ไม่ถูกนับซ้ำใน auto | ไม่ซ้ำ | PASS |
| Context | `test_context.py` | ไฟล์รวมกันเกิน token budget | หยุดใส่เพิ่มเมื่อเต็ม budget | หยุดถูกต้อง | PASS |
| Todo | `test_todo.py` | ยังไม่มี todos.json | คืน list ว่าง | list ว่าง | PASS |
| Todo | `test_todo.py` | add แล้ว load | ข้อมูลตรงกัน | ตรงกัน | PASS |
| Todo | `test_todo.py` | ลบตัวกลางแล้วเพิ่มใหม่ | id ไม่ซ้ำ | ไม่ซ้ำ | PASS |
| Todo | `test_todo.py` | toggle สองครั้ง | กลับสถานะเดิม | ถูกต้อง | PASS |
| Todo | `test_todo.py` | toggle id ที่ไม่มีจริง | คืน False | False | PASS |
| Todo | `test_todo.py` | delete ปกติ + id ไม่มีจริง | True / False ตามลำดับ | ถูกต้อง | PASS |
| Todo | `test_todo.py` | todos.json เสีย | ไม่ crash คืน list ว่าง | ไม่ crash | PASS |
| Trust | `test_trust.py` | โฟลเดอร์ใหม่ | is_trusted = False | False | PASS |
| Trust | `test_trust.py` | mark_trusted แล้ว | is_trusted = True | True | PASS |
| Trust | `test_trust.py` | marker file content | มี `trusted_at=` | มี | PASS |
| Search (Brave) | `test_search.py` | ไม่มี key | raise RuntimeError | raise ถูกต้อง | PASS |
| Search (Brave) | `test_search.py` | response ถูกต้อง (mock) | parse ผลลัพธ์ถูกต้อง | ถูกต้อง | PASS |
| Search (Brave) | `test_search.py` | response เสีย (mock) | raise RuntimeError | raise ถูกต้อง | PASS |
| Search (Tavily) | `test_search.py` | ไม่มี key | raise RuntimeError | raise ถูกต้อง | PASS |
| Search (Tavily) | `test_search.py` | response ถูกต้อง (mock) | parse ผลลัพธ์ถูกต้อง | ถูกต้อง | PASS |
| Server | `test_server.py` | GET / | HTTP 200 | 200 | PASS |
| Server | `test_server.py` | GET path ที่ไม่มี | HTTP 404 | 404 | PASS |
| Server | `test_server.py` | POST /api/todos ถูกต้อง | สร้าง todo สำเร็จ | สำเร็จ | PASS |
| Server | `test_server.py` | POST /api/todos ไม่มี text | HTTP 400 | 400 | PASS |

## Coverage ที่ยังไม่ครอบคลุม (บอกตรงๆ ตาม Rule 19)

- `local_coder.py` (CLI หลัก) — ทดสอบด้วย manual integration test ผ่าน mock Ollama server เท่านั้น
  ยังไม่มี automated unit test เพราะ diff engine/chat loop ผูกกับ `input()` และ Ollama connection
  โดยตรง ต้อง refactor แยก I/O ออกจาก logic ก่อนถึงจะ unit test ได้สะดวก (ยังไม่ทำในรอบนี้ เพราะ
  นอก scope ที่ Manager อนุมัติ)
- `desktop_archive.py`, `linear_connector.py` — ยังไม่มี unit test ในรอบนี้ (ไม่ได้อยู่ใน pack grade
  spec ที่ระบุมา — spec ระบุแค่ config, context, search, todo, trust, server)
- `/api/chat` endpoint ของ `server.py` — ต้องมี Ollama จริงรันอยู่ ไม่เหมาะเป็น unit test อัตโนมัติ
