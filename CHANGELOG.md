# Changelog

เปลี่ยนแปลงของ LCA (Local Code Assistant) — เรียงใหม่สุดบน

Format: Keep a Changelog, SemVer. วันที่เป็นเวลาไทย (UTC+7)

## [0.3.5] — 2026-11-11 (Production hardening — auth, RBAC pages, ownership, SSE contract)

### Added
- `app/session_store.py` — session token หลัง login (in-memory, TTL 12h, compare_digest, brute-force guard ต่อ IP)
- `POST /api/auth/login` (username/password → `lcs_` token ใช้เป็น X-Auth-Token), `POST /api/auth/logout`; `/api/me` คืน `source`/`expires_at`
- `app/login.html` — ฟอร์ม username/password (+ วาง key ได้เหมือนเดิม); `app.js` มี `lca.login()/logout()` และตั้ง cookie `lca_key` สำหรับ page gate
- Page gate: `/dev` และ `/console` ต้อง ADMIN+ (ไม่มีตัวตน → `302 /login?next=`, USER → 403; โหมด local บน loopback ผ่านเหมือนเดิม)
- Conversation ownership: `owner=ชื่อ` = พื้นที่ส่วนตัว, `owner=NULL` = พื้นที่บริษัท; list/search/get/update/delete/export/switch/branch/regen/edit/compare/ส่งข้อความ ตรวจ `_assert_access` (403 `ChatAccessError`); import บังคับ owner = ผู้นำเข้า
- GUEST mode (feature flag `guest_chat`, ปิด default): แชทโดยไม่ล็อกอินได้เฉพาะโมเดล local, ไม่บันทึกอะไรลงดิสก์, โควตา 20 ข้อความ/วัน/IP (429); role `GUEST` สร้างเป็นบัญชีไม่ได้
- `POST /api/vscode/chat` — alias ของ `/api/chat/stream` (สัญญา SSE เดียวกัน) สำหรับ extension
- `GET /api/chat/export?format=md` — Session Tape เป็น Markdown (`chat_hub.export_markdown`)
- Tests +37 → 1333: `test_session_store`, `test_auth_login_api`, `test_chat_ownership`, `test_sse_contract`, `test_guest_chat`

### Fixed
- "Empty reply from server" (curl 52): exception ที่ไม่มีใครดักใน handler เคยปิด socket เงียบ ๆ → ตอนนี้ `do_GET/do_POST` มีด่านสุดท้าย `_fail_last_resort` ตอบ `500 JSON` (ถ้ายังไม่ส่ง header) + ลง `history_store` error_log
- SSE: `_sse_stream` และ `/api/chat/stream` ปิดสตรีมด้วย `{"error":...}` ทุก exception (เดิมดักเฉพาะ BackendError → RuntimeError ทำสตรีมค้าง/ขยะ); `chat_hub.serve_chat` เคย `_send_json` ซ้อนหลังเปิดสตรีม → ส่ง error event แทน
- `chat_store.list_conversations/search` คืน `owner` เพื่อให้กรองตามสิทธิ์ได้

## [0.3.4] — 2026-11-05 (Test Coverage — router unit tests)

### Added
- `tests/test_router.py` — 27 unit tests covering `_TIER_MODELS` structure,
  `_ollama_installed_models()` (success/URLError/bad-JSON), and `recommend()`
  (shape, tier mapping, unknown-tier fallback, profile-exception, installed flags,
  top_pick logic, cache hit, cached_until)
- Test suite: 1246 → 1273 tests total

## [0.3.3] — 2026-11-05 (Test Coverage — cli_session unit tests)

### Added
- `tests/test_cli_session.py` — 32 unit tests covering `data_dir`, `sessions_dir`,
  `SessionLog.append` (create/write/OSError fallback), `load_messages` (parse/filter),
  and `latest_session` (match by project field) in `app/cli_session.py`
- Test suite: 1282 → 1246 (after squash: 1214 baseline + 32 new = 1246)

## [0.3.2] — 2026-11-05 (Test Coverage — hw_meter unit tests)

### Added
- `tests/test_hw_meter.py` — 23 unit tests covering `snapshot()` in `app/hw_meter.py`:
  CPU/RAM rounding, freq/load None-when-falsy, tier+model from hw_profile,
  profile-exception fallback. Uses setUp/tearDown sys.modules injection for
  isolation without polluting the full suite.
- Test suite: 1259 → 1282 tests total

## [0.3.1] — 2026-11-05 (Test Coverage — news_store unit tests)

### Added
- `tests/test_news_store.py` — 19 unit tests covering `_fetch_feed` and `get_news`
  in `app/news_store.py`: RSS/Atom parse, 20-item cap, cache hit/TTL, error tracking
- Test suite: 1240 → 1259 tests total

## [0.3.0] — 2026-11-05 (Test Coverage — stats_store unit tests)

### Added
- `tests/test_stats_store.py` — 31 unit tests covering `record` and `get_stats`
  in `app/stats_store.py`: empty db, counts, error_rate, top-20 by_endpoint, last_24h
- Test suite: 1209 → 1240 tests total

## [0.2.9] — 2026-11-05 (Test Coverage — db unit tests)

### Added
- `tests/test_db.py` — 40 unit tests covering `split_sql`, `db_path`, `write_lock`,
  `connect_raw` (WAL/FK/lca_seg), and `list_migrations` in `app/db.py`
- Test suite: 1169 → 1209 tests total

## [0.2.8] — 2026-11-05 (Test Coverage — chat_search unit tests)

### Added
- `tests/test_chat_search.py` — 68 unit tests covering all 6 pure functions in `app/chat_search.py`:
  `_fold`, `seg`, `is_single_thai_char`, `fts_query`, `snippet`, `like_pattern`
- Test suite: 1101 → 1169 tests total

## [0.2.7] — 2026-11-04 (Storage Slim — ลด GitHub database)

ตามที่ user สั่ง: "ยิ่งเก็บ Data เยอะยิ่งมีค่าใช้จ่าย ทำแบบเล็กๆ ลบหมด fix"

### Changed
- `docs/` 32 files → 22 files (-14 source, +3 merged):
  - `docs/SETUP.md` — รวม DEPLOY + GO_LIVE + GO_ONLINE_FREE + HOSTING + BUNDLING + INSTALLER_EXE + TRAY_INSTALLER
  - `docs/CLUSTER.md` — รวม CLUSTER_FORWARD + NETBOOK_NETWORKING + NETBOOK_SOFTWARE_STACK + LCA_NETBOOK_HPC
  - `docs/AGENTS.md` — รวม AGENT_ORG + AGENT_TECH_PLAN + ORG_SYSTEM
- `CHANGELOG.md` — compact history table แทน verbose v0.1.x blocks (579→201 lines)
- `SKILL.md` — compact PR history (16→2 rows), compact TODO (40+→3 rows)

### Removed
- docs/AGENT_ORG.md, AGENT_TECH_PLAN.md, BUNDLING.md, CLUSTER_FORWARD.md, DEPLOY.md
- docs/GO_LIVE.md, GO_ONLINE_FREE.md, HOSTING.md, INSTALLER_EXE.md, LCA_NETBOOK_HPC.md
- docs/NETBOOK_NETWORKING.md, NETBOOK_SOFTWARE_STACK.md, ORG_SYSTEM.md, TRAY_INSTALLER.md

### No new tests (docs/config only)

## History (v0.1.0–0.2.6)

| Version | Date | Key change |
|---------|------|------------|
| 0.2.6 | 2026-10 | LCA v0.2.6 mega release |
| 0.2.5 | 2026-09 | HPC cluster sync |
| 0.2.4 | 2026-09 | LAN discovery |
| 0.2.3 | 2026-09 | Ollama selector |
| 0.2.2 | 2026-09 | Hardware meter |
| 0.2.1 | 2026-09 | DB layer |
| 0.2.0 | 2026-09 | News feed |
| 0.1.9 | 2026-08 | Rate limit |
| 0.1.8 | 2026-08 | Stats API |
| 0.1.7 | 2026-07 | Request body size limit (DoS fix) |
| 0.1.6 | 2026-07 | Timing-safe token compare |
| 0.1.5 | 2026-07 | Schedule gate |
| 0.1.4 | 2026-06 | Console UI |
| 0.1.3 | 2026-06 | Server wiring |
| 0.1.2 | 2026-05 | Bots |
| 0.1.1 | 2026-05 | Skills store |
| 0.1.0 | 2026-05 | Connections registry |
