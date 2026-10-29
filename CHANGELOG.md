# Changelog

เปลี่ยนแปลงของ LCA (Local Code Assistant) — เรียงใหม่สุดบน

Format: Keep a Changelog, SemVer. วันที่เป็นเวลาไทย (UTC+7)

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
