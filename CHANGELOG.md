# Changelog

เปลี่ยนแปลงของ LCA (Local Code Assistant) — เรียงใหม่สุดบน

Format: Keep a Changelog, SemVer. วันที่เป็นเวลาไทย (UTC+7)

## [0.1.4] — 2026-10-30 (version endpoint — QA/support observability)

ตามที่ user สั่ง: "PR TOdo ให้อัพเดท file แก้ อัพเดทงานตลอดและ pr วนลูปดูทางจริงทำงานยังไง"

### Added
- **`GET /api/version`** (public, ไม่ auth) — คืน `{version, python, name}` อ่าน `VERSION` file
  - ใช้ตอน support/QA/debug: ลูกค้าแจ้งเวอร์ชันปัจจุบันได้โดยไม่ต้องเปิด terminal
  - ตัวอย่าง: `curl http://localhost:9000/api/version` → `{"version":"0.1.4","python":"3.11.9","name":"LCA (Local Code Assistant)"}`
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
