# Changelog

เปลี่ยนแปลงของ LCA (Local Code Assistant) — เรียงใหม่สุดบน

Format: Keep a Changelog, SemVer. วันที่เป็นเวลาไทย (UTC+7)

## [Unreleased] — 2026-11-03 (CLI แชท: เลื่อนขึ้นอ่านระหว่างโมเดลตอบแล้วจอไม่เด้ง/แชทไม่หลุด)

ตามที่ user แจ้ง: "ใน PowerShell cmd terminal เลื่อนดู model ตอบคำถามห้องแชทหลุด"

### Fixed
- `local_coder.py` สตรีมคำตอบแบบ append-only: เลิกใช้ spinner เธรดที่เขียน `\r` ทุก 0.15 วิ
  และ print+flush ทุก token (conhost ดึง viewport กลับล่างทุกครั้งที่มี output)
  → สถานะ "กำลังคิด" เขียน/ลบครั้งเดียว, flush ไม่ถี่กว่า 0.25 วิ
- Ctrl+C ระหว่างตอบ = หยุดคำตอบนั้น (เก็บส่วนที่ได้) ไม่ปิดโปรแกรม; Ctrl+C ตอนถาม y/n แก้ไฟล์ = ยกเลิก
- Ollama ล่ม/หลุดกลางคัน = แจ้ง error แล้วกลับ prompt (เดิม `sys.exit(1)` ทิ้งทั้งแชท)

### Added
- `--stream-mode auto|live|quiet`, `--no-stream`, env `LCA_STREAM_MODE`, คำสั่ง `/stream`:
  quiet = ไม่เขียนลงจอระหว่างตอบ (ความคืบหน้าขึ้นที่ title bar) แล้วพิมพ์ทีเดียวตอนเสร็จ;
  auto = quiet บนหน้าต่าง cmd/PowerShell แบบเก่า (ไม่มี `WT_SESSION`/`TERM_PROGRAM`/`TERM`), live ที่อื่น
- `/last` เปิดคำตอบล่าสุดด้วย pager ในตัว (Enter ต่อ / q ออก), `/last raw`
- บันทึกแชททุกข้อความ `<data_dir>/cli_sessions/*.jsonl` (`app/cli_session.py`), `--resume`, `--no-save`
- `app/cli_render.py` (stdlib) + `tests/test_cli_render.py` (18 tests)

## [Unreleased] — 2026-11-03 (Chat Hub conversations, provider routing, Thai chat page)

### Added
- **`/api/chat` and `/api/chat/stream`** call `app.providers` when the request
  names a `provider`. The model is chosen on that request. A `conversation_id`
  reloads the shared transcript, so the next turn can name a different provider.
  Requests that name neither a provider nor a conversation stay on
  `model_backend` (including cluster forward).
- **SQLite migration `0010_chat_hub`** (`app/migrations/0010_chat_hub.sql`).
  No `app/migrations` files existed, so 0010 was free. A new database moves
  from `user_version` 0 to 10. Thai/English search is Python character bigrams
  in contentless FTS5 (`app/chat_search.py`).
- **Branch, regenerate, and compare** (`POST /api/chat/branch`, `/regen`,
  `/compare`). Compare runs cloud targets together and local targets one at a
  time through `admission`.
- **Local vs cloud by endpoint host** (`app/providers/locality.py`). A target
  is local only when its `base_url` host is `localhost`, `127.0.0.1` or `::1`
  (`[::1]`). Ollama / OpenAI-compatible on a LAN IP (e.g. `192.168.1.5`),
  another hostname, or a tunnel counts as cloud: no admission gate, runs in
  parallel in compare, and the `/chat` picker shows it as cloud. Vendor APIs
  (Anthropic, OpenAI, Gemini, xAI) are always cloud.
- **Chat page `/chat`** (`app/chat.html`, `app/chat.css`, `app/chat.js`).
  Vanilla JS, no framework. IBM Plex Sans Thai and IBM Plex Mono are subset
  to woff2 under `app/fonts/` and served locally (OFL). The subset is renamed
  to LCA Sans / LCA Mono because "IBM Plex" is a Reserved Font Name.
- Chat skills with `mode=chat` are seeded into `personas` once. Dataset
  samples are copied only when `CHAT_IMPORT_SAMPLES` is `1`/`true`/`yes`.

### Fixed
- `/chat` loads `/app.js` and sends the per-launch session token on every
  `/api/chat/*` call, so the page works behind the #107 request guard
  (guard code unchanged).

### Tests
+20 in `tests/test_chat_store.py`, `tests/test_chat_api.py`, and
`tests/test_chat_page.py` (mocked providers, no network, no real keys).
+17 after merging main: `tests/test_provider_locality.py` (localhost,
127.0.0.1, ::1, LAN IP, remote host, look-alikes), LAN compare runs in
parallel, `/chat` carries the session token. Full suite: **1013 passed**.

### Not changed
- `VERSION` stays 0.1.6.

## [Unreleased] — 2026-11-03 (Chat Hub provider adapters)

### Added
- **Chat provider adapters** (`app/providers/`) on top of `app/model_backend.py`.
  One transcript (`system` / `user` / `assistant` text) can continue on another
  provider. Stdlib HTTP only (`urllib`, `json`, `http.client`, `ssl`) — no
  Anthropic, OpenAI, or Google SDK.
  - Providers: Anthropic Messages, OpenAI Chat Completions and Responses,
    Google Gemini, xAI, Ollama, and any OpenAI-compatible `base_url`.
  - `chat`, `stream` (text deltas over SSE or Ollama NDJSON), `list_models`.
  - Usage from the provider response, with a 4-characters-per-token estimate
    when a count is missing.
  - USD cost estimate from an editable table in `app/providers/pricing.py`.
    Figures are configurable defaults with the public page they were copied
    from. Unknown models stay `None`. `authoritative` is always false.
- API keys: `config_manager.get_key`, and `app.secrets.reveal` when that module
  is importable (PR #108, not on main yet). Keys are not logged.

### Tests
+79 in `tests/test_providers.py` (mocked HTTP, no network). Full suite: **916 passed**.

### Not changed
- `VERSION` stays 0.1.6.
- `model_backend.generate` / `generate_stream` and their callers, including
  `server.py` (request-guard work is PR #107).

## [Unreleased] — 2026-11-03 (API keys sealed at rest)

ไม่ขยับเลข `VERSION` (ยัง 0.1.6)

### Added
- **`app/secret_store.py`** — เก็บ API key / token / password นอกไฟล์ config แบบ plaintext
  - Windows: `CryptProtectData` / `CryptUnprotectData` ผ่าน ctypes, scope CurrentUser
    (`CRYPTPROTECT_UI_FORBIDDEN` และไม่ตั้ง `CRYPTPROTECT_LOCAL_MACHINE`)
  - นอก Windows: `keyring` จะถูกใช้ก็ต่อเมื่อมีชื่ออยู่ใน `requirements.txt`
    ตอนนี้ไม่มี (มีแต่ `psutil`) จึงเก็บใน `secrets.bin` โหมด `0600` พร้อมคำเตือนหนึ่งครั้ง
    คำเตือนไม่พิมพ์ค่าความลับ
- เทส `tests/test_secret_store.py` จำลอง DPAPI บน Linux

### Changed
- `config.json`, `connections.json`, และ `config_versions.json`: ค่าที่เป็น credential
  ถูกเปลี่ยนเป็นตัวชี้ `$lca_secret_ref` ตอนอ่าน ถ้าเข้ารหัสไม่ได้ ค่าเดิมยังอยู่
- snapshot ของ config ไม่เก็บค่าความลับอีกต่อไป — เก็บ ref ที่ชี้สำเนาใน `secrets.bin`
  เพื่อให้ rollback ยังได้ค่าเดิม โดยไม่เขียน plaintext ลงไฟล์เวอร์ชัน
- `.gitignore`: `cluster.json`, `.lca_trust`, `secrets.bin`, `lca_dataset.jsonl`, `data/`
  - คอมเมนต์ท้ายบรรทัดทำให้แพทเทิร์นเดิมไม่ match (gitignore ไม่ตัด `#` ท้ายบรรทัด)
    ย้ายคอมเมนต์ไปบรรทัดของตัวเอง ไฟล์ลับเดิมเช่น `config.json` จึงถูก ignore จริง
  - `.lca_trust` เคยถูก track (มีแต่ `trusted_at=2026-09-02T14:38:24`) — เอาออกจาก index ด้วย `git rm --cached` ไม่ได้เขียนประวัติใหม่
  - `cluster.json` ไม่เคยถูก track
- `docs/learn/rapid-iteration-ecosystem/SKILL.md`: เส้นทาง `app/*.html`,
  `TokenLCAlimit.exe` เป็นผลบิลด์ของ workflow ไม่ใช่ไฟล์ใน repo,
  และ `docs/ARCHITECTURE.md` ไม่ใช่แผน v0.0.2 ที่ยังใช้เป็นสถาปัตยกรรมปัจจุบัน
- `app/context_manager.py`: ไม่ดึง `secrets.bin` / `connections.json` / `config_versions.json`
  เข้า context ของโมเดล
- ตั้งชื่อโมดูลเป็น `app/secret_store.py` (ไม่ใช่ `app/secrets.py`) — `local_coder.py` ใส่ `app/`
  ไว้หน้า `sys.path` ถ้าชื่อ `secrets` จะบัง stdlib `secrets` ที่ `org_store` / `server` ใช้สุ่ม token
- ชื่อที่ลงท้าย `_TOKEN(S)` แต่เป็นตัวเลขตั้งค่า (`MAX_TOKENS`, `MIN_`/`NUM_`/`TOTAL_`…,
  `PRICE_PER_1K_TOKENS`, คำว่า LIMIT/COUNT/PER/BUDGET/CONTEXT ฯลฯ) ไม่ถูก seal — เก็บ plaintext แก้มือได้

### Security
- ไม่ log ค่า API key. อ่าน blob ไม่ได้จะไม่ลบ entry ใน `secrets.bin`
- ลบสำเนาที่ seal ไว้เมื่อเจ้าของหายไป:
  - `connections.remove()` (และ connection ที่ถูกตัดเกิน `MAX_RECORDS`) ลบ `conn:<id>`
  - snapshot ที่ถูกตัดเกิน `MAX_VERSIONS` ลบ `snapshot:<vid>:*` ของมัน
    (ยกเว้น entry ที่ `config.json` หลัง rollback หรือเวอร์ชันที่เหลือยังชี้อยู่)
  - `set_key(KEY, "")` ลบ `config:KEY` และสำเนา `snapshot:*:KEY` ทุกเวอร์ชัน

### Tests
- `python3 -m unittest discover -s tests` — **862 passed** (837 เดิม + 25 ใน `tests/test_secret_store.py`)

## [Unreleased] — 2026-11-03 (localhost CSRF / DNS rebinding guard)

### Security — 2026-11-03

- **กัน CSRF / DNS rebinding บน loopback** (`server.py` พอร์ต 8420)
  - Host allowlist: `127.0.0.1:<port>`, `localhost:<port>`, `[::1]:<port>`
    และชื่อใน `LCA_HOST` เมื่อ bind นอก loopback. ค่าอื่นตอบ 403
  - ตรวจ Origin บน POST/PUT/PATCH/DELETE และ websocket upgrade.
    ไม่มี Origin ได้สำหรับ CLI. Origin คนละต้นทางตอบ 403. ไม่เพิ่ม CORS
  - ไม่ได้ตั้ง `--token` / `LCA_TOKEN`: สุ่ม session token (`secrets.token_urlsafe`) ต่อการเปิดโปรเซส
    และต้องส่ง `X-Auth-Token` สำหรับ endpoint ที่ต้องล็อกอิน. สิทธิ์ยังเป็น CEO
  - หน้าเว็บได้ token จากสคริปต์ที่ฝังใน HTML (`window.__LCA_SESSION_TOKEN`)
    และแอปเดสก์ท็อปเปิดด้วย fragment `#lca_token=`. `server.py` พิมพ์ค่าให้ CLI
  - ตั้ง token เอง: พฤติกรรมเดิม (master token = CEO, API key / role เหมือนเดิม) และไม่ฝัง token ลงหน้า
- **`GET /api/version` ยัง public** — ไม่มี secret. คงฟิลด์ `python` ไว้สำหรับ support
- **ใช้ได้หลัง proxy HTTPS / tunnel** (Render, HF Spaces, Docker, cloudflared): เมื่อ bind `0.0.0.0` / `::`
  (บังคับ token) รับ Host ที่ไม่มีพอร์ต หรือ `:80` / `:443` / พอร์ตที่ฟัง และเทียบ Origin กับชื่อใน Host
  โดยไม่สนพอร์ต. Origin เว็บอื่นยังตอบ 403. loopback เข้มเหมือนเดิม
- **`LCA_ALLOWED_HOSTS`** (คั่นด้วยจุลภาค) — allow-list ชื่อ host เพิ่ม. ชื่อ loopback ถูกตัดออก (คลายไม่ได้)
  และหน้าเว็บที่เปิดผ่านชื่อเหล่านี้ไม่ได้ session token อัตโนมัติ
- **กัน clickjacking**: หน้า HTML ส่ง `X-Frame-Options: DENY` + `Content-Security-Policy: frame-ancestors 'none'`
- docs: `DEPLOY.md` §1/§2a + ตาราง env, `GO_ONLINE_FREE.md` เส้นทาง A/C, `GO_LIVE.md` หมายเหตุ tunnel

### Tests
- +17 (`tests/test_server_request_guard.py` และ `launch_url` ใน `test_lca_app.py`)
- +15 (`tests/test_server_proxy_hosts.py` — Host ไม่มีพอร์ตบน wildcard, Origin เว็บอื่น 403,
  `LCA_ALLOWED_HOSTS`, header กัน iframe)

## [Unreleased] — 2026-11-03 (installer SHA-256 verify)

### Security
- **ตัวติดตั้งตรวจ SHA-256 ของไฟล์ที่ดาวน์โหลด** (`installer_gui.py`)
  - `verify_sha256()` อ่านไฟล์ทีละ chunk ผ่าน `hashlib.sha256`
  - ช่อง urllib อัปเดต hash ไปพร้อมกับเขียนสตรีม; ช่อง curl ตรวจไฟล์ที่เซฟแล้วด้วย helper เดียวกัน
  - hash ไม่ตรง → ลบไฟล์ทิ้ง แล้วโยน `ChecksumMismatch` (ไม่แตก zip ต่อ และไม่ fallback ไปช่องทางอื่น)
- **ปัก commit แทน `refs/heads/main.zip`**
  - URL แบบ latest ไม่มี SHA-256 คงที่ (ไบต์เปลี่ยนทุก push) และ GitHub ไม่ได้เผยแพร่ `.sha256` ของ source archive — จึงไม่ใส่ hash ที่เดา
  - `PINNED_COMMIT` = `93f1ca8de37543af528b33c8620347cf10865c5c` (HEAD ของ main ตอนเพิ่มการตรวจ)
  - `ZIP_SHA256` = `d03326baa16f1555b1d0089e46884a0f0ddf249e3b2b4976f77854313fe5ef8d`
    คำนวณจากไฟล์ที่ดาวน์โหลดจริงจาก URL นั้นเมื่อ 2026-11-03 (curl สองครั้งได้ digest เดียวกัน, 518881 ไบต์)
    — **ไม่ใช่** checksum ที่ upstream ประกาศ

### Tests
+3 (`837` → `840`) ใน `tests/test_sha256_verify.py` และ `tests/test_installer_gui.py`:
- `VerifySha256Test` — match คืน digest และเก็บไฟล์, mismatch ลบไฟล์แล้ว raise
- `DownloadZipTest.test_urllib_mismatch_deletes_file_and_skips_curl`

## [Unreleased] — 2026-11-03 (VS Code workspace + SKILL.md install path)

ไม่ bump เวอร์ชัน — ยังเป็น 0.1.6 จนกว่าจะมี release

### Added
- **`.vscode/`** (`launch.json`, `tasks.json`, `settings.json`, `extensions.json`)
  ให้รัน เทส ลิงต์ และดีบัก LCA ใน VS Code บน Windows
  - launch: `server.py <dir> --host 127.0.0.1 --port 8420`, `lca_app.py`,
    `local_coder.py <dir> --model qwen2.5-coder:3b`, `installer_gui.py`
  - task หลักตรง CI: `python -m unittest discover -s tests`
  - `files.eol` เป็น LF — repo เก็บไฟล์เป็น LF (`git ls-files --eol`)
- **README** ส่วน "Develop in VS Code"

### Fixed
- **`SKILL.md`**: ไม่ชี้ `install.sh`, `install_online.ps1`, `lca-web` / `lca-web.bat`
  ที่ลบใน v0.1.3 (#101) แล้ว
  - Windows: `install.bat` / `install.ps1` (one-liner เดิม), เปิดเว็บด้วย `start-lca.bat`
  - Linux/macOS: `pip install -r requirements.txt` แล้ว `python server.py <dir>`
- **`docs/APP_WALKTHROUGH.md`**: `install*.ps1/sh` → `install.ps1` + `install.bat`

---

## [0.1.6] — 2026-10-30 (`--version` CLI flag — ตรงกับ `/api/version`)

ตามที่ user สั่ง: "**ดูทางจริงทำงานยังไง**" — ผู้ใช้ต้องเช็กเวอร์ชันจาก
command line ได้ตรงกันกับ endpoint `/api/version`

### Added
- **`server.py --version`** → `LCA <ver> (python X.Y.Z)` แล้ว exit 0
- **`lca_app.py --version`** → `LCA Desktop <ver> (python X.Y.Z)` แล้ว exit 0
- **`server.read_version(root=None)`** — module-level helper อ่าน VERSION file
  (ถ้า root=None ใช้ `_resource_root()` — รองรับ frozen bundle ด้วย)
- สอดคล้อง: `--version` CLI ใช้ `read_version()` ตัวเดียวกับ `/api/version` endpoint
  → ไม่มี drift ระหว่างสองช่องทาง

### Tests
+7 ใน `test_lca_app.py`:
- `VersionFlagTest` ×2 — `python server.py --version` และ `python lca_app.py --version`
  คืน exit 0 + stdout ขึ้นเวอร์ชัน (subprocess ของจริง)
- `ReadVersionTest` ×5 — reads VERSION file, fallback no file, fallback empty,
  strip whitespace, default root = resource_root

**837 tests pass** (จาก 830 → +7)

### Rationale
ก่อนหน้านี้ user เช็กเวอร์ชันได้แค่ `curl ... /api/version` (ต้องรัน server ก่อน)
ตอนนี้: `LCA-Desktop.exe --version` ได้เลยไม่ต้องรัน → support/debug ง่ายขึ้น
+ ไม่ต้องเปิด GUI/browser ก็เห็น (dev + sysadmin workflow)

---

## [0.1.5] — 2026-10-30 (docs cleanup — stale refs ไฟล์ที่ลบใน v0.1.3)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Fixed (docs stale refs)
- **`docs/APP_WALKTHROUGH.md` ตารางไฟล์**: ลบ row `install.sh` และ `install_online.ps1` (ลบใน v0.1.3)
  - เพิ่ม row `lca_app.py` (`LCA-Desktop.exe`) ที่หายไปในตาราง
  - เปลี่ยน `lca-web` → `start-lca.bat` + ยืนยัน port 8420
- **`docs/GO_ONLINE_FREE.md` section WSL**: `bash install.sh` → `pip install -r requirements.txt`
  (`install.sh` ลบไปแล้ว; `pip install` ตรงกว่าสำหรับ Linux/WSL)
- **`docs/RESOURCE_MANAGER_DESIGN.md`**: `install.ps1/install.sh` → `install.ps1`
  (install.sh ลบไปแล้ว)
- **`install.ps1`** comment: `lca-web` → `start-lca`

### Not changed (ตั้งใจ)
- **`SKILL.md`** `windows-package/install.sh` refs — เป็นบันทึก design history (dir ไม่มีจริงแล้ว)
- **`docs/*` `curl ... ollama.com/install.sh`** — เป็น Ollama's install.sh (external, ไม่ใช่ของเรา)
- **`CHANGELOG.md`** entries ของ v0.1.3 Removed section — เป็น record ประวัติ

### Fixed (PR #102 followup)
- CHANGELOG example curl URL ที่พิมพ์ port ผิด `9000` → `8420`

---

## [0.1.4] — 2026-10-30 (version endpoint — QA/support observability)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Added
- **`GET /api/version`** (public, ไม่ auth) — คืน `{version, python, name}` อ่าน `VERSION` file
  - ใช้ตอน support/QA/debug: ลูกค้าแจ้งเวอร์ชันปัจจุบันได้โดยไม่ต้องเปิด terminal
  - ตัวอย่าง: `curl http://localhost:8420/api/version` → `{"version":"0.1.4","python":"3.11.9","name":"LCA (Local Code Assistant)"}`
  - ไม่คืน commit sha / build id (ไม่ลับแต่ไม่จำเป็น)
  - อยู่ใน schedule allowlist — ลูกค้าดูเวอร์ชันได้ตลอดแม้ server ปิดตามตาราง

### Tests
+4 เทส `test_server_health.py` (shape, อ่าน VERSION file, fallback "unknown", python version shape)

### Rationale
Observability-first: เวลา user เจอ bug ที่หน้าแอป → ขอ `/api/version` ก่อน
กันคำถาม "เวอร์ชันไหน" รบกวนทุกบั๊ก report + ง่ายต่อ smoke test ใน CI

---

## [0.1.3] — 2026-10-30 (file cleanup — consolidation)

ตามที่ user สั่ง: "ลบไฟล์ที่กระจาย รวบรวมให้ติดตั้งง่าย"

### Removed (ไฟล์ซ้ำซ้อน)
- **`install.sh`** — Linux installer, overlap กับ `pip install -r requirements.txt && python server.py`
- **`install_online.ps1`** — ซ้ำกับ `install.ps1` + banner แล้ว (banner ชี้ `.exe` ก็อยู่ใน `install.ps1`)
- **`lca-web.bat`** — ซ้ำกับ `start-lca.bat` (ทั้งคู่รัน `server.py`; `start-lca.bat` ดีกว่าเพราะเด้ง browser ให้)

### Changed
- `install.ps1` ไม่สร้าง `lca-web.bat` อีกต่อไป (ลบ Set-Content block + ปรับ echo message)
- `installer_gui.py` COPY_FILES ลบ `lca-web.bat`
- `update.ps1` lift ลบ `lca-web.bat` + เพิ่ม `lca-tray.bat` + `lca-tray.ps1` (ที่ลืมใส่)
- README + install.html: ลิงก์ one-liner ชี้ `install.ps1` แทน `install_online.ps1`
- README + install.html: `lca-web` → `start-lca.bat`

### หลังปรับ (ไฟล์ที่เหลือใน root)
- Build targets: `installer_gui.py`, `lca_app.py`
- Core: `server.py`, `local_coder.py`
- Install: `install.bat`, `install.ps1`
- Launcher: `lca.bat` (CLI), `start-lca.bat`, `lca-desktop.bat`, `lca-tray.bat`, `lca-tray.ps1`
- Maintenance: `uninstall.ps1`, `update.ps1`
- Dirs: `app/`, `sysmanager/`, `docs/`, `tests/`, `scripts/`
- Meta: `README.md`, `CHANGELOG.md`, `VERSION`, `requirements.txt`, `.gitignore`, `Dockerfile`

**ไฟล์เก่าหายไป 3 ตัว** — surface area ลดลง, no scattering

---

## [0.1.2] — 2026-10-30 (SSL cert hotfix)

**Hotfix:** user เจอ installer_gui.py แสดง error ตอนรันบน Windows:
`[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate`

### Fixed
- **installer_gui.py `_download_zip()` fallback 2 ชั้น** (bug fix)
  - 1. `urllib.request.urlretrieve()` — ปกติ (ตรวจ cert ครบ)
  - 2. `curl.exe` (Windows 10+ มีมาเอง — ใช้ CA ของระบบ update ถี่กว่า Python bundled)
  - ทั้ง 2 fail → RuntimeError + ชี้วิธีแก้ (ติดตั้ง Python ใหม่ หรือ `pip install --upgrade certifi`)
- **Root cause:** Python stdlib urllib ใช้ bundled CA — Windows installations บางเวอร์ชัน
  ไม่มี update → cert chain ตรวจไม่ผ่านกับ GitHub cert ปัจจุบัน

### Tests
+3 เทส DownloadZipTest (urllib success, curl fallback, both-fail raises with recovery msg)

---

## [0.1.1] — 2026-10-29 (Bug fixes — ready-for-use, not beta)

ตามที่ user สั่ง: "0.1.1 เป็นตัวพร้อมใช้งาน ไม่ใช่เบต้า" + "ทำให้ดาวน์โหลดเป็นก้อนเดียวกัน"

### Changed (v0.1.1 docs/UX)
- **Promote `LCA-Desktop.exe` เป็น primary download** ใน README, `/install`, install.bat/.ps1 banners
  - เดิม `TokenLCAlimit.exe` ขึ้นก่อน (เป็น installer — ยังต้องมี Python)
  - ใหม่: `LCA-Desktop.exe` ขึ้นก่อน (ก้อนเดียวจริง — ฝัง Python runtime มาด้วย)
- เพิ่ม `docs/BUNDLING.md` — อธิบายเทียบ 2 ชนิดของ .exe + roadmap option A/B/C

### Fixed (v0.1.1 bugs)
- **installer_gui.py `check_free_disk` ไม่ครอบ TEMP**: ของเดิมเช็คแค่ `install_dir`
  แต่ installer ใช้ `tempfile.TemporaryDirectory()` สำหรับ download+extract ก่อน
  (ถ้า install=D: แต่ C:/TEMP เต็ม → urlretrieve พังตั้งแต่โหลด). ตอนนี้ตรวจทั้งคู่
  + รายงาน disk ไหนตึง (`install_dir` หรือ `TEMP`)
- **server.py `_schedule_gated` ไม่ handle trailing slash**: `/console/` (มี slash
  ท้าย) ไม่ตรงกับ `/console` ใน allowlist → ถูก gate ปิด. เพิ่ม `_norm_path()`
  ลบ trailing slash ก่อนเทียบ

### PRs (v0.1.1)
- (this one) — bug fixes จาก v0.1.0 QA review

---

## [0.1.0] — 2026-10-29 (Official Release)

**Milestone แรกของ LCA** — รวม 5 PRs (#89–#93), **812 unit/integration tests ผ่านหมด**

### Fixed
- **Installer disk space pre-check** (`installer_gui.py`) — ตรวจพื้นที่ว่างก่อนดาวน์โหลด
  (ต้องมี ≥ 300 MB) → fail-fast พร้อมข้อความช่วย recovery แทนให้ user เจอ
  "Cannot create ... Not enough space on the disk" กลางคัน (user เจอ 118 errors
  ตอน extract บน Desktop ที่เต็ม)
- README: เพิ่ม section ".exe ไฟล์เดียว" ขึ้นเป็นวิธีติดตั้งที่แนะนำที่สุด +
  warning สำหรับคน extract zip ที่ดิสก์เต็ม

### Added
- **เวลาเปิด-ปิดเซิร์ฟเวอร์ตามเวลาไทย** (`app/schedule_gate.py`) — ปิดเซิร์ฟเวอร์
  ตามตารางเวลา เพื่อประหยัดค่า cloud/ไฟ ตอนลูกค้าไม่ค่อยใช้
  - Config: `SCHEDULE_ENABLED`, `SCHEDULE_OPEN_HOUR` (default 6), `SCHEDULE_CLOSE_HOUR` (default 20)
  - รองรับ window ภายในวัน (6..20) และข้ามเที่ยงคืน (22..6)
  - CEO/ADMIN bypass → ดูแลระบบตอนปิดได้
- **`GET /api/status`** (public, ไม่ auth) — แจ้งลูกค้าสถานะ (เปิด/ปิด/เวลาเปลี่ยนสถานะถัดไป)
  คืน response + `Retry-After` header เมื่อปิด
- **System tray installer** (`lca-tray.ps1` + `lca-tray.bat`) — ติดตั้งปุ๊บแล้วอยู่
  ใน system tray เหมือน Discord/Steam (คลิกซ้าย = เปิดแอป, คลิกขวา = เมนู)
- **764+ unit tests** (จาก 489) — เพิ่ม coverage ให้ 16 modules ที่ยังไม่มีเทส

### Security
- **Timing-safe token comparison** — ใช้ `hmac.compare_digest` แทน `==` ใน:
  - `app/auth_backend.py` (`LocalAuthBackend` master_token + `StaticTokenBackend`)
  - `server.py` (`X-Auth-Token` header)
  - ป้องกัน timing attack เดา token ทีละ byte
- **Request body size limit** — cap `_read_json_body` ที่ 2 MiB
  (ป้องกัน DoS จากการส่ง `Content-Length` ใหญ่ ทำให้ server รอ/จอง RAM จนล้ม)

### PRs
- #89 — เพิ่ม 124 tests สำหรับ 8 modules
- #90 — เพิ่ม 136 tests สำหรับ 8 modules เหลือ
- #91 — system tray installer mode
- #92 — schedule gate + zero-day security fixes
- #93 — disk space pre-check + README .exe section

### Downloads (ของทางการ)

ที่ [GitHub Releases](https://github.com/Ragam111/9nammon/releases/tag/v0.1.0) หรือ [Actions artifacts](https://github.com/Ragam111/9nammon/actions):
- **`TokenLCAlimit.exe`** (~12 MB) — ตัวติดตั้ง GUI ไฟล์เดียว (ดับเบิลคลิก → ติดตั้ง)
- **`LCA-Desktop.exe`** (~10 MB) — แอปก้อนเดียวเปิดแชตได้เลย (ฝัง Python + server มาด้วย)

ต้องมี **Python 3.10+** และ **Ollama** บนเครื่องปลายทาง (`.exe` เป็น installer/launcher, ไม่ได้ฝัง runtime หนัก)

---

## วิธีอ่าน

- **Added**: ของใหม่
- **Changed**: ของเดิมที่พฤติกรรมเปลี่ยน (potentially breaking)
- **Fixed**: บั๊ก
- **Security**: ช่องโหว่/การเสริมความปลอดภัย
- **Removed**: ของที่เอาออก

> ไฟล์นี้อัพเดตทุก PR cycle (ตามที่ user สั่ง: "ห้ามลืม update file GitHub แพ็ดใหม่ด้วยครั้งใหม่")
