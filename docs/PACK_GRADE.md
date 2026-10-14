# LCA v0.0.2 — Pack Grade

**Pack Grade Version**: 1.0
**Status**: **SCAFFOLD + TESTING** (ไม่ใช่ VERIFIED หรือ RELEASE — ดูเหตุผลด้านล่าง)

สถานะที่ใช้ในเอกสารนี้: `DESIGN` → `SCAFFOLD` → `TESTING` → `VERIFIED` → `RELEASE`

## ทำไมยังไม่ VERIFIED/RELEASE

| เงื่อนไข | สถานะ |
|---|---|
| Unit tests (`tests/`) รันผ่านจริง | ✅ 34/34 PASS |
| Windows UTF-8 console encoding | 🟡 Pending — ยังไม่ยืนยันผลจริงบน PowerShell |
| RAM measurement บนเครื่องจริง | 🟡 Pending — ไม่มีตัวเลขจาก Task Manager |
| Chat Bug #4 | 🔴 Evidence Required — ยังไม่แก้ตามคำสั่ง Manager |
| Dependencies | ✅ 0 third-party packages |
| Offline capability | ✅ ทดสอบแล้ว (ไม่พึ่ง internet ยกเว้นเปิด `/websearch` เอง) |

## Architecture

ดู `docs/ARCHITECTURE.md`

## Modules

| Module | สถานะ |
|---|---|
| `config_manager.py` | TESTING (6 unit tests ผ่าน) |
| `context_manager.py` | TESTING (5 unit tests ผ่าน) |
| `todo_store.py` | TESTING (7 unit tests ผ่าน) |
| `folder_trust.py` | TESTING (4 unit tests ผ่าน) |
| `web_search.py` | TESTING (4 unit tests ผ่าน, mock API) |
| `tavily_search.py` | TESTING (3 unit tests ผ่าน, mock API) — **feature ใหม่จาก session นี้** |
| `server.py` | TESTING (4 unit tests ผ่าน — เฉพาะ `/api/todos`, `GET /`) |
| `local_coder.py` | ทดสอบด้วย manual integration test (mock Ollama server) — ยังไม่มี unit test อัตโนมัติ |

## Interfaces

Search provider interface เดียวกันทุกตัว: `search_web(query, project_root) -> list[dict]`,
`format_results_for_context(results) -> str` — ดูรายละเอียดใน ARCHITECTURE.md

## Dependencies

**0 third-party Python packages** — stdlib เท่านั้น: `json`, `urllib`, `threading`, `pathlib`,
`os`, `sys`, `shutil`, `fnmatch`, `datetime`, `unittest`, `unittest.mock`

## Security

- `config.json` มี secret จริง ห้าม commit เข้า git (Rule 23)
- Path traversal guard ก่อน apply diff ทุกครั้ง
- Web server bind `127.0.0.1` เป็นค่าเริ่มต้นเสมอ (Rule 12)
- `/websearch` ปิดเป็นค่าเริ่มต้นเสมอ ไม่ persist ข้ามเซสชัน (Rule 18)

## Performance

- ไม่มี global background thread ที่ทำงานตลอดเวลา (spinner thread หยุดทันทีที่ chunk แรกมาถึง)
- ไม่มี polling
- Streaming response (ไม่โหลดคำตอบทั้งก้อนเข้า RAM ก่อนแสดงผล)
- **ยังไม่มีตัวเลข RAM จริงจากเครื่อง Windows** — ต้องวัดจริงก่อนประกาศ VERIFIED

## Testing

ดู `docs/TEST_PLAN.md`

## Known Limitations

- Chat Bug #4 (หน้าเว็บเลื่อนหลุด) — EVIDENCE REQUIRED
- ไม่มีตัวเลข RAM benchmark จริง
- `local_coder.py` ไม่มี automated unit test (มีแต่ manual integration test ผ่าน mock server)
- `installer.iss` (Inno Setup) ยังไม่เคยคอมไพล์จริง
