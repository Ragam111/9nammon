# LCA v0.0.2 — Architecture

## Module Map

```
LCA/
├── local_coder.py      # CLI: chat loop, diff engine, spinner, streaming, /help
├── server.py            # Web backend (MVC-style): Model=call_ollama, Controller=HTTP handler, View=index.html/JSON
├── app/
│   ├── config_manager.py    # Hot-swap API key storage (config.json > env var)
│   ├── context_manager.py   # Auto-scan project files, .lcaignore, token budget
│   ├── folder_trust.py      # .lca_trust marker — ยืนยันโฟลเดอร์ก่อนเริ่มทำงาน
│   ├── todo_store.py         # todos.json CRUD
│   ├── web_search.py          # Brave Search API provider
│   ├── tavily_search.py       # Tavily Search API provider (feature ใหม่)
│   ├── linear_connector.py    # Linear API (อ่านอย่างเดียว, พักไว้ตาม Rule 16)
│   ├── desktop_archive.py     # sync CHANGELOG_local.md/todos.json ไปเดสก์ท็อป
│   └── index.html              # Web Chat UI
├── tests/                       # unittest (stdlib เท่านั้น — ไม่ใช้ pytest)
└── docs/                         # เอกสารชุดนี้
```

## Module Contracts

### config_manager.py
- **Purpose**: จัดการ API key แบบ hot-swap ต่อโปรเจกต์
- **Input**: `project_root: Path`, `key_name: str`
- **Output**: `str | None`
- **Dependencies**: stdlib เท่านั้น (`json`, `os`, `pathlib`)
- **Error Handling**: `config.json` เสีย → warn แล้วคืนค่าว่าง ไม่ raise exception (ทดสอบแล้วใน `test_config.py`)
- **Security**: ไม่ commit เข้า git (Rule 23), `list_configured_keys()` ไม่คืนค่าจริง

### context_manager.py
- **Purpose**: auto-scan ไฟล์โปรเจกต์เข้า context ตาม `.lcaignore` + token budget
- **Input**: `project_root: Path`, `num_ctx: int`, `already_manual: set`
- **Output**: `dict[str, str]` (rel_path → content)
- **Dependencies**: stdlib (`fnmatch`, `pathlib`)
- **Error Handling**: อ่านไฟล์ไม่ได้ (binary/permission) → ข้ามเงียบๆ ไม่ crash

### folder_trust.py
- **Purpose**: ยืนยันโฟลเดอร์โปรเจกต์ก่อนเริ่ม scan/แก้ไฟล์ครั้งแรก
- **Input**: `project_root: Path`
- **Output**: `bool`
- **Dependencies**: stdlib (`datetime`, `pathlib`)
- **Security**: กันเปิดโฟลเดอร์ผิด (พิมพ์ path พลาด) โดยไม่รู้ตัว

### todo_store.py
- **Purpose**: CRUD todo list เก็บเป็น `todos.json` ต่อโปรเจกต์
- **Dependencies**: stdlib (`json`, `pathlib`)
- **Error Handling**: JSON เสีย → warn แล้วถือว่าว่างเปล่า

### web_search.py / tavily_search.py
- **Purpose**: ค้นเว็บจริงผ่าน Brave หรือ Tavily API แล้ว format เข้า context
- **Interface เดียวกันทั้งคู่**: `search_web(query, project_root) -> list`, `format_results_for_context(results) -> str`
- **Provider switching**: `local_coder.py` เลือก provider ผ่าน `get_search_provider()` โดยไม่ต้องรู้ raw implementation ของแต่ละตัว (ดู Search Architecture ด้านล่าง)
- **Error Handling**: ไม่มี key/เรียก API ไม่สำเร็จ → raise `RuntimeError` ให้ caller fallback เป็นโหมด LLM ล้วน (ตาม Rule 18)

## Search Provider Architecture

```
local_coder.py
      │
      ▼
get_search_provider(project_root)   ← อ่าน /config set SEARCH_PROVIDER (default: brave)
      │
      ├──→ web_search module (Brave)
      └──→ tavily_search module (Tavily)
```

ทั้งสอง provider มี interface เดียวกันทุกจุด (`search_web`, `format_results_for_context`) — `local_coder.py`
ไม่รู้รายละเอียดภายในของแต่ละตัวเลย เรียกผ่าน module reference ที่ได้จาก `get_search_provider()` เท่านั้น

## Error Handling Standard (ยึดจาก SKILL.md)

ทุก external operation ต้องมี error handling ที่ระบุ exception type ชัดเจน ห้ามใช้ `except:` เปล่า:
- Network → `urllib.error.URLError`
- File → `OSError`
- JSON → `json.JSONDecodeError`
- ทดสอบยืนยันแล้วว่าไม่มีจุดไหน crash โปรแกรมหลักเมื่อ external dependency ล้มเหลว (ดู `tests/`)

## Known Limitations (ไม่ปิดบัง ตามหลัก 9arm ข้อ 1)

- RAM usage บนเครื่อง Windows จริงยังไม่มีตัวเลขวัดจริง (มีแต่ประมาณเชิงสถาปัตยกรรม)
- Bug #4 (หน้าเว็บ chat เลื่อนหลุด) ยังไม่แก้ — สถานะ EVIDENCE REQUIRED
- `test_server.py` ทดสอบเฉพาะ `/api/todos` และ `GET /` — ไม่ทดสอบ `/api/chat` เพราะต้องมี Ollama จริงรันอยู่ (integration test แยกต่างหาก ไม่ใช่ unit test)
