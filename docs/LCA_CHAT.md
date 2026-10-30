# LCA Chat — แอปแชตก้อนเดียว เหมือน Claude Desktop

**ปรัชญา (ตามที่ user สั่ง):** "ติดตั้ง .exe รวมก้อนเป็นแอป LCA Chat เด้งใช้งานแบบ Claude ได้เลย"

## ประสบการณ์แบบ Claude Desktop

```
ดาวน์โหลด LCA-Desktop.exe → ดับเบิลคลิก → หน้าต่างเปิดเลย
                                              ↓
                                 ถ้าครั้งแรก → /console (ตั้งสมอง)
                                 ครั้งที่ 2+ → / (แชต)
```

### First-run flow (v0.1.2+)

เมื่อ user เปิด `LCA-Desktop.exe` **ครั้งแรก**:
1. Server start บน `127.0.0.1:8420`
2. ตรวจว่ามี `connections.json` ไหม → **ไม่มี** = first run
3. เปิดหน้าต่าง `--app` mode ไปที่ **`/console`** (ไม่ใช่ `/` ปกติ)
4. User ตั้ง connection (OpenAI/TokenMe/vLLM/Ollama)
5. เริ่มแชตได้

ครั้งที่ 2 → เปิดไปที่ `/` ตรง (chat) เลย

### ทำไมต้องตั้ง connection ก่อน?

LCA ไม่ได้ฝังโมเดลใน .exe — user เลือกเองว่าใช้:
- **Cloud** (OpenAI, Claude API, TokenMe) → ไม่ต้องลง Ollama (เหมือน ChatGPT.app)
- **Local** (Ollama) → ข้อมูลไม่ออกเครื่อง (เหมือน Ollama Desktop)

หน้า `/console` รองรับทั้งคู่ในที่เดียว

## เทียบกับ Claude Desktop

| ประสบการณ์ | Claude Desktop | LCA Chat (LCA-Desktop.exe) |
|-----------|---------------|---------------------------|
| ดาวน์โหลด | ไฟล์เดียว ~100 MB | **ไฟล์เดียว ~10 MB** (ไม่ฝัง Chromium ใช้ Edge app-mode) |
| ติดตั้ง | ต้อง install | **แค่ดับเบิลคลิก** (portable) |
| First run | ขอ API key | **ขอ connection** (API key หรือ Ollama) |
| ข้อมูล | เก็บ cloud + local | **เก็บ local ล้วน** (`%LOCALAPPDATA%\LocalCodeAssistant\data`) |
| หลายโมเดล | Claude อย่างเดียว | **หลาย provider** ใน connection เดียวกัน |
| Opensource | ❌ | ✅ Python stdlib + ดู source ได้ |

## สำหรับ advanced users

### Custom port
```python
# แก้ lca_app.py บรรทัด DEFAULT_PORT = 8420
```

### Multiple instances
รัน `LCA-Desktop.exe` 2 ครั้ง → port_auto หา port ว่างให้ (ของเดิมมี `find_free_port()` ใน server.py)

### API access (เหมือน Claude API)
Server ที่ `LCA-Desktop.exe` รันเปิด HTTP API ที่ `/api/chat`, `/api/bots/run` etc.
→ automation (n8n/zapier) ยิง HTTP เข้ามาได้ ขณะที่ user แชตผ่าน GUI

### Bot workflows
สร้าง Skill + Bot ที่ `/console` → ยิงจาก n8n:
```bash
curl -X POST http://127.0.0.1:8420/api/bots/run \
  -H "Content-Type: application/json" \
  -d '{"bot_id": "bot-...", "input": "สรุปโค้ดนี้"}'
```

## ไฟล์ที่เกี่ยวข้อง

- `lca_app.py` — entry point ของ LCA Chat (first-run logic + window open)
- `server.py` — HTTP server + routes
- `app/console.html` — หน้า setup connection
- `app/chat.html` (หรือ `/` route) — หน้าแชตหลัก
- `docs/BUNDLING.md` — เทียบ LCA-Desktop.exe vs TokenLCAlimit.exe

## Troubleshooting

**หน้าต่างไม่เปิดเป็น app-mode** → ไม่มี Edge/Chrome บนเครื่อง → เปิดเบราว์เซอร์ default แทน
**ปิดหน้าต่างแล้ว process ยังรัน** → ไปที่ Task Manager → หา `LCA-Desktop.exe` → End task
**ขึ้นหน้า /console ซ้ำ** → `connections.json` อาจเสีย → ลบไฟล์ที่ `%LOCALAPPDATA%\LocalCodeAssistant\data\connections.json` → ลองใหม่
