# Changelog

เปลี่ยนแปลงของ LCA (Local Code Assistant) — เรียงใหม่สุดบน

Format: Keep a Changelog, SemVer. วันที่เป็นเวลาไทย (UTC+7)

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

**1101 tests pass** (ไม่เปลี่ยน)

## [0.2.6] — 2026-11-04 (AI Cluster Setup — `scripts/ai_cluster_setup.sh`)

ตามที่ user สั่ง: "ทำPRที่แก้ไขขั้นสูง ทำให้ GitHub database น้อย รวมเป็นไฟล์เดียวกัน"
AI Cluster บน LAN 2 เครื่อง: Master (PC/Linux 192.168.1.10) + Worker (Notebook 192.168.1.20)

### Added
- `scripts/ai_cluster_setup.sh` — single-file cluster setup (ไม่มีแยกไฟล์ config):
  - `phase_ollama()` — Ollama install + systemd `OLLAMA_HOST=0.0.0.0:11434` + `ufw allow`
  - `phase_litellm()` — LiteLLM Docker + embedded YAML config (3 backends: Ollama/Claude/Gemini); MASTER_KEY auto-gen → `~/.lca/.env`
  - `phase_webui()` — Open WebUI Docker `:3000` → ต่อ Ollama + LiteLLM
  - `phase_tunnel()` — Cloudflare quick tunnel → `https://*.trycloudflare.com` (ไม่ต้อง login)
  - `phase_verify()` — curl health checks ทุก service (Ollama/LiteLLM/WebUI/LCA)
  - Commands: `all [--tunnel]`, `--verify`, `--stop`, `--worker`, `--tunnel`
- `.claude/skills/ai-cluster-setup/SKILL.md` — Claude Code skill `/ai-cluster-setup`:
  - ASCII architecture diagram (Master/Worker/Cloud)
  - Commands, env vars, AI backends (Ollama/Claude/Gemini)
  - 3-Agent development pattern (Leader/Engineer/QA Chef)
  - Troubleshooting table + ports summary

### No new tests (bash script — no Python test needed)

**1101 tests pass** (ไม่เปลี่ยน)

## [0.2.5] — 2026-11-04 (Cluster Sync — `GET /api/nodes/sync`)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Added
- `app/cluster_sync.py` — `sync_discovered(project_root, base_ip, port, timeout)`: รัน LAN discovery แล้วลงทะเบียน node ที่พบใหม่เข้า cluster_store อัตโนมัติ; คืน `{added[], existing[], scanned, elapsed_s}`; ถ้า discover error คืน field `error` ด้วย
- `GET /api/nodes/sync` — ADMIN-gated; `?port=`, `?timeout=`, `?base_ip=` เหมือน /discover; เรียก `cluster_sync.sync_discovered()`; bridges lan_discovery ↔ cluster_store
- `tests/test_cluster_sync.py` — 10 tests: 6 HTTP + 4 unit (adds new node, skips existing, error passthrough, no nodes)

### Tests
+10 ใน `tests/test_cluster_sync.py`

**1101 tests pass** (จาก 1091 → +10)

## [0.2.4] — 2026-11-04 (LAN Discovery — `GET /api/nodes/discover`)

ตามที่ user สั่ง: P6 LAN/IP 2-PC setup (software layer)

### Added
- `app/lan_discovery.py` — `discover(base_ip, port, timeout)`: scan /24 subnet ด้วย thread pool; ลอง `GET /api/version` แต่ละ IP; คืน `{nodes[], scanned, base_ip, elapsed_s}`; `get_local_ips()` รายการ IP เครื่องนี้ (กรอง loopback)
- `GET /api/nodes/discover` — ADMIN-gated; `?port=`, `?timeout=`, `?base_ip=` override; เรียก `lan_discovery.discover()`
- `tests/test_lan_discovery.py` — 10 tests: 6 HTTP + 4 unit (probe mock server, invalid IP, loopback scan)

### Tests
+10 ใน `tests/test_lan_discovery.py`

**1091 tests pass** (จาก 1081 → +10)

## [0.2.3] — 2026-11-04 (Multi-tier Ollama Selector — `GET /api/models/recommend`)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Added
- `app/router.py` — `recommend(project_root)` เรียก `hw_profile` ดู tier แล้วคืนรายการโมเดล Ollama ที่เหมาะ; เช็ค Ollama ผ่าน `GET /api/tags`; 5-min in-memory cache
- `GET /api/models/recommend` — USER-gated; คืน tier, models[], top_pick, ollama_running, installed[]
- `tests/test_router_api.py` — 11 tests: 8 HTTP + 3 unit; monkeypatch router.recommend + tearDownClass restore

### Tests
+11 ใน `tests/test_router_api.py`

**1081 tests pass** (จาก 1070 → +11)

## [0.2.2] — 2026-11-04 (Hardware Meter — `GET /api/metrics/hw`)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Added
- `app/hw_meter.py` — `snapshot(project_root, interval)` รวม live collect() + hw_profile tier; คืน cpu_pct, cpu_per_core, freq_mhz, logical_cores, load_avg_1m, ram_pct, ram_used_gb, ram_total_gb, tier, recommended_model
- `GET /api/metrics/hw` — USER-gated; `?interval=` ปรับ CPU measurement window (0.05–2.0s)
- `tests/test_hw_meter_api.py` — 6 HTTP integration tests; monkeypatch hw_meter.snapshot + tearDownClass restore

### Tests
+6 `HwMeterApiTest` ใน `tests/test_hw_meter_api.py`

**1070 tests pass** (จาก 1064 → +6)

## [0.2.1] — 2026-11-04 (Database layer upgrade — migration 0011 + `GET /api/admin/db/status`)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Added
- `app/migrations/0011_server_events.sql` — เพิ่มตาราง `server_events` ใน `lca.db` (kind, level, source, message, extra, ts)
- `app/migrations/0011_server_events.py` — migration runner; ตาม pattern เดิม 0010_chat_hub
- `app/db_manager.py` — `get_db_status()` คืน db_version, code_version, db_size_bytes, tables, migrations_applied/pending; `log_event()` silent
- `GET /api/admin/db/status` — ADMIN-gated endpoint บน server.py
- `tests/test_db_manager.py` — 9 tests: 6 HTTP + 3 unit; fix tearDownClass เพื่อ restore model_backend.generate

### Fixed
- `tests/test_chat_store.py` — อัปเดต 2 tests ที่ hardcode migration count=1 / version=10 ให้รองรับ migration ที่เพิ่มในอนาคต (assertGreaterEqual, assertIn)
- `tests/test_db_manager.py` — เพิ่ม tearDownClass เพื่อ restore model_backend.generate (กัน test isolation leak)

### Tests
+9 `DbStatusHttpTest` + `DbManagerUnitTest` ใน `tests/test_db_manager.py`

**1064 tests pass** (จาก 1055 → +9)

## [0.2.0] — 2026-11-04 (News RSS API — `GET /api/news`)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Added
- `app/news_store.py` — RSS/Atom feed fetcher (stdlib only): `get_news(feeds)` + 15-min in-memory cache; `_fetch_feed` monkeypatch-able สำหรับ test
- `GET /api/news` — USER-gated endpoint; รองรับ `?feed=url` override; คืน `{articles, count, feeds, errors, cached_until}`
- `tests/test_news_api.py` — 6 HTTP integration tests: 200 shape, articles list, auth 401, count=len, fields check

### Tests
+6 `NewsApiTest` ใน `tests/test_news_api.py`

**1055 tests pass** (จาก 1049 → +6)

## [0.1.9] — 2026-11-04 (Review/Statistics API — `GET /api/admin/stats`)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Added
- `app/stats_store.py` — SQLite counter (stdlib only): `record(project_root, endpoint, status)` + `get_stats()` คืน total_requests, total_errors, error_rate, last_24h, by_endpoint (top 20)
- `GET /api/admin/stats` — ADMIN-gated endpoint บน server.py; บันทึกทุก `_send_json` response ก่อน write
- `tests/test_stats_api.py` — 6 HTTP integration tests: 200 shape, error_rate type, RBAC 401, total increments, by_endpoint list

### Tests
+6 `StatsApiTest` ใน `tests/test_stats_api.py`

**855 tests pass** (จาก 849 → +6)

## [0.1.8] — 2026-11-04 (rate-limiting HTTP tests — ทดสอบ 429 guard จริงผ่าน HTTP)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Tests
+6 `RateLimitHttpTest` + `RateLimitDisabledTest` ใน `tests/test_server_rate_limit.py` —
HTTP integration tests สำหรับ rate limiting (429 guard) ที่มี `RateLimiter` อยู่แล้วแต่ยังไม่มี
การทดสอบผ่าน HTTP จริง:
- `test_requests_within_limit_succeed` — 3 ครั้ง ภายใน quota ต้องได้ 200
- `test_request_over_limit_gets_429` — ครั้งที่ 4 ต้องได้ 429 + response มี `"error"`
- `test_429_error_message_in_response` — response body มี `{"error": "..."}` ไม่ว่างเปล่า
- `test_root_path_not_rate_limited` — `/` (static) หลัง quota หมดยังไม่ได้ 429
- `test_console_path_not_rate_limited` — `/console` ไม่โดน rate limit
- `test_many_requests_never_429_when_disabled` — `rate_limit_max=0` → ปิด rate limit ทั้งหมด (10 req)

**849 tests pass** (จาก 843 → +6)

### Rationale
Rate limiting ป้องกัน DoS แต่ไม่มี HTTP integration test จริงมาก่อน — เพิ่ม 6 tests ให้ CI
จับ regression ได้ทันที ใช้ `rate_limit_max=3` เพื่อ trigger 429 ได้เร็วโดยไม่ต้องยิง
300 ครั้งจริง ทดสอบทั้งโหมดปกติและ disabled (rate_limit_max=0)

## [0.1.7] — 2026-11-04 (integration tests `/api/admin/hw-profile` — ตรวจสอบ endpoint จริง)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Tests
+6 `HwProfileEndpointTest` ใน `test_server_health.py` — HTTP integration tests สำหรับ
`GET /api/admin/hw-profile` ที่มี handler อยู่แล้วแต่ยังไม่เคยมีการทดสอบผ่าน HTTP จริง:
- `test_hw_profile_returns_200` — local bind = CEO auto → 200 (ไม่ต้อง token)
- `test_hw_profile_shape` — response มีครบทุก key (tier, cpu_model, ram_gb, is_hdd, gpus, ...)
- `test_hw_profile_tier_valid` — tier ต้องเป็น netbook / workstation / server
- `test_hw_profile_recommended_config_shape` — recommended_config มี PREFERRED_MODEL, COMPUTE_BACKEND, MAX_CONCURRENT_GENERATIONS
- `test_hw_profile_next_upgrade_is_string` — next_upgrade เป็น string ไม่ว่าง
- `test_hw_profile_no_disk_param_is_safe` — ไม่ส่ง `?disk=` ก็ต้องไม่พัง (default safe)

**843 tests pass** (จาก 837 → +6)

### Rationale
`/api/admin/hw-profile` เป็น endpoint "สมองรู้จักตัวเอง" (HPC principle: self-aware machine)
ใช้ตอน support ถามว่า "เครื่อง tier ไหน แนะนำ config อะไร" — มีอยู่แล้วแต่ไม่มี HTTP test
เพิ่ม integration tests ให้ CI จับได้ถ้า regression เกิด (เช่น key หาย / 500 error)

## ประวัติ v0.1.0–v0.1.7 (compact — ดูรายละเอียดใน git log)

| Version | วันที่ | สรุป | Tests |
|---|---|---|---|
| Unreleased ×7 | 2026-11-03 | CLI chat scroll fix, Chat Hub conversations+provider routing, provider adapters, API keys sealed at rest, CSRF/DNS rebinding guard, SHA-256 installer verify, VS Code workspace | 843 |
| 0.1.7 | 2026-11-04 | integration tests `GET /api/admin/hw-profile` (+6) | 843 |
| 0.1.6 | 2026-10-30 | `--version` CLI flag (+7) | 837 |
| 0.1.5 | 2026-10-30 | docs cleanup — stale refs หลัง v0.1.3 | 830 |
| 0.1.4 | 2026-10-30 | `GET /api/version` public endpoint (+4) | 830 |
| 0.1.3 | 2026-10-30 | file cleanup — ลบ install.sh, install_online.ps1, lca-web.bat | 823 |
| 0.1.2 | 2026-10-30 | SSL cert hotfix — urllib + curl.exe fallback (+3) | 820 |
| 0.1.1 | 2026-10-29 | Bug fixes, LCA-Desktop.exe primary download, disk space pre-check | 812 |
| 0.1.0 | 2026-10-29 | Official Release: schedule gate, tray installer, 764+ tests, timing-safe token, body size limit | 812 |

---

## วิธีอ่าน

- **Added**: ของใหม่
- **Changed**: ของเดิมที่พฤติกรรมเปลี่ยน (potentially breaking)
- **Fixed**: บั๊ก
- **Security**: ช่องโหว่/การเสริมความปลอดภัย
- **Removed**: ของที่เอาออก

> ไฟล์นี้อัพเดตทุก PR cycle (ตามที่ user สั่ง: "ห้ามลืม update file GitHub แพ็ดใหม่ด้วยครั้งใหม่")
