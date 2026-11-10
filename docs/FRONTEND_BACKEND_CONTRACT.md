# สัญญา Frontend ↔ Backend — แดชบอร์ดพอร์ต 8421

หน้าเว็บอยู่ที่ `local_dashboard/web/` และเปิดที่พอร์ต **8421** เท่านั้น (localhost)
เกตเวย์คือ `app_server.py` (CodexGPT). โหนดงานคือ `local_dashboard/server.py` ที่พอร์ต **8420**
PR นี้ไม่แก้ไฟล์ Python สองตัวนั้น และไม่แก้ `start-dashboard.cmd`

ตรวจในรีโปวันนี้ (สาขา main และ working tree): **ไม่มีไฟล์ `app_server.py` และไม่มี `local_dashboard/server.py`**
จึงยังไม่มีเส้นที่หน้าเว็บเรียก. หน้าเว็บเรียกชื่อตามสเปกด้านล่างอยู่แล้ว ถ้าได้ 404/405/501 จะขึ้น `not implemented` ถ้าต่อไม่ติดหรือ 503 จะขึ้น `offline`

อย่า rewrite `/auth/google`, `/api/cluster/status`, `/api/logs/stream` ไปที่ `index.html`

## เครื่องและพอร์ต

- Windows 10 Pro x64, Intel Core i5-7400 (4 คอร์ / 4 เธรด), RAM 8GB, HDD หรือ SSD, การ์ดจอออนบอร์ด
- `http://127.0.0.1:8420` และ `http://localhost:8420` = worker nodes (`local_dashboard/server.py`)
- `http://127.0.0.1:8421` และ `http://localhost:8421` = main dashboard UI (`app_server.py` เสิร์ฟ `local_dashboard/web/`)
- หน้าเว็บไม่ยิงไปหาพอร์ต 8420 เอง. มันถามเกตเวย์ที่ `/api/cluster/status` เท่านั้น

## ไฟล์ที่เกตเวย์ต้องเสิร์ฟที่รากของพอร์ต 8421

เสิร์ฟเนื้อใน `local_dashboard/web/` เป็นเว็บรูท ไม่ใช่ทั้งโฟลเดอร์ `local_dashboard/`

| URL | ไฟล์ |
|---|---|
| `/` และ `/index.html` | `local_dashboard/web/index.html` |
| `/css/dashboard.css` | `local_dashboard/web/css/dashboard.css` |
| `/js/*` | `local_dashboard/web/js/*` |
| `/manifest.webmanifest` | `local_dashboard/web/manifest.webmanifest` |
| `/sw.js` | `local_dashboard/web/sw.js` |
| `/icon.svg` | `local_dashboard/web/icon.svg` |

## Origin และ Google

Client ID (สาธารณะ, อยู่ใน `local_dashboard/web/js/config.js`):

`456424591178-g3ufhccbhmnvt74ne7hfq27432b3sm19.apps.googleusercontent.com`

Authorized JavaScript origins (ไม่มี path, ไม่มี `/` ท้าย):

- `http://localhost:8421`
- `http://127.0.0.1:8421`

Authorized redirect URIs (ตรงกับ `window.location.origin + "/auth/google"`):

- `http://localhost:8421/auth/google`
- `http://127.0.0.1:8421/auth/google`

ห้ามใส่ client secret ใน `local_dashboard/web/` หรือไฟล์ที่ commit. ถ้าเกตเวย์ต้องใช้ secret ให้อ่านจากตัวแปรสภาพแวดล้อมหรือ config ที่ถูก gitignore

## CORS

ใช้ allow-list ตรงตัวนี้เท่านั้น ห้ามใช้ `*`

```text
allow_origins = [
  "http://localhost:8421",
  "http://127.0.0.1:8421",
]
```

ถ้าใช้เฟรมเวิร์กที่รองรับ `CORSMiddleware` ให้ตั้งค่าเท่านี้ และให้ `OPTIONS` ตอบ 204
หน้าเว็บอยู่ origin เดียวกับเกตเวย์ จึงไม่ได้พึ่ง CORS สำหรับสามเส้นหลัก
แต่ห้ามเปิด origin อื่น เพราะ Google และเบราว์เซอร์ใช้สองค่านี้เท่านั้น

## `GET /auth/google` และ `POST /auth/google`

เส้นเดียวใช้ทั้งเริ่มล็อกอิน, callback, ดูสถานะ, และออกจากระบบ

### ดูสถานะ

`GET /auth/google?mode=status`

ต้องตอบ JSON `200` และ **ห้าม** 302 ไป Google (หน้าเว็บตั้ง `redirect: "manual"` ถ้าถูกเด้งจะถือว่า `not implemented` เพื่อไม่ให้เด้งทุกครั้งที่เปิดหน้า)

ยังไม่ล็อกอิน:

```json
{ "authenticated": false }
```

ล็อกอินแล้ว:

```json
{
  "authenticated": true,
  "name": "Nammon",
  "email": "nammon1130@gmail.com"
}
```

หน้าเว็บโชว์ `name` ก่อน ถ้าไม่มีจึงโชว์ `email`

### เริ่มล็อกอิน

`GET /auth/google?mode=start&redirect_uri=http%3A%2F%2F127.0.0.1%3A8421%2Fauth%2Fgoogle&client_id=456424591178-g3ufhccbhmnvt74ne7hfq27432b3sm19.apps.googleusercontent.com`

- รับ `redirect_uri` ก็ต่อเมื่อเป็นหนึ่งในสองค่าด้านบนเท่านั้น นอกนั้นตอบ `400`
- ถ้ามี `client_id` ต้องตรงกับ Client ID ด้านบน
- ตอบ `302` ไป Google หรือ `200` JSON `{ "url": "https://accounts.google.com/..." }`
- เก็บ `state` ฝั่งเซิร์ฟเวอร์. หน้าเว็บไม่ส่ง client secret และไม่แลก code กับ Google เอง

### Callback

`GET /auth/google?code=...&state=...`

เกตเวย์ต้องรับเส้นนี้ก่อนเสิร์ฟไฟล์สถิต. แลก code ที่เซิร์ฟเวอร์, ตั้งคุกกี้เซสชัน (`SameSite=Lax`, ไม่ใส่ secret ลงในหน้าเว็บ), แล้ว `302` ไป `/#/account`
ถ้าหน้าเว็บ SPA โหลดขึ้นมาทั้งที่ยังมี `code` อยู่ แปลว่าเกตเวย์ยังไม่รับ callback และหน้าเว็บจะขึ้น `not implemented`

### ออกจากระบบ

`POST /auth/google?mode=logout`

ตอบ `200`:

```json
{ "ok": true }
```

แล้วลบคุกกี้. หน้าเว็บเคลียร์สถานะบนจอแม้เส้นนี้จะ 404

## `GET /api/cluster/status`

สุขภาพของพอร์ต 8420 (worker) และ 8421 (dashboard). หน้าเว็บโพลล์ทุก 8 วินาทีเมื่อแผงโหนดเปิดอยู่ และหยุดเมื่อแท็บถูกซ่อน

`200`:

```json
{
  "nodes": [
    { "port": 8420, "role": "worker", "status": "up", "latency_ms": 12 },
    { "port": 8421, "role": "dashboard", "status": "up", "latency_ms": 3 }
  ]
}
```

`status` เป็น `"up"`, `"down"` หรือ `"not_implemented"`. `latency_ms` เป็นจำนวนเต็มหรือ `null`
การวัดไปที่ 8420 ต้องไม่บล็อกเธรดหลัก (ดู ThreadPoolExecutor ด้านล่าง). timeout สั้น ๆ พอ (หน้าเว็บตัดที่ 2 วินาที)

ถ้าเส้นนี้ไม่มี หน้าเว็บขึ้น `not implemented` ทั้งสองพอร์ต และไม่ไปยิง `/api/health` เอง

## `GET /api/logs/stream`

สตรีมล็อกเทอร์มินัล. หน้าเว็บชอบ SSE

```text
Content-Type: text/event-stream
Cache-Control: no-cache

event: log
data: {"id":1,"ts":"2026-11-10T17:00:00+07:00","level":"info","text":"ready"}

```

- แต่ละก้อนที่เขียนออกซ็อกเก็ตต้องไม่เกิน **32KB** (32768 ไบต์). หน้าเว็บก็หั่นก้อนที่ใหญ่กว่านั้นก่อนถอดรหัส
- `text` เป็นข้อความธรรมดา ไม่ใช่ HTML
- ถ้ายังไม่มี SSE แต่ส่ง JSON `200` ที่เส้นเดียวกัน หน้าเว็บรับได้เป็น snapshot แล้วถามซ้ำทุก 8 วินาที:

```json
{
  "lines": [
    { "id": 1, "ts": "2026-11-10T17:00:00+07:00", "level": "info", "text": "ready" }
  ]
}
```

ฐานล็อกใช้ไม่ได้ ตอบ `503`:

```json
{ "error": "offline", "detail": "database locked" }
```

ยังไม่มีเส้นนี้ ตอบ `404`:

```json
{ "error": "not implemented" }
```

หน้าเว็บวาดด้วย `DocumentFragment` ใน `requestAnimationFrame` และเก็บโหนดบนจอไม่เกิน 500 บรรทัด (บรรทัดเก่าถูกลบออกจาก DOM)

## Backend TODO for CodexGPT

ยังไม่ได้ทำให้ใน PR นี้. หน้าเว็บทนต่อการไม่มีเส้นเหล่านี้แล้ว

### เส้นที่ต้องเพิ่มใน `app_server.py`

ไฟล์นี้ยังไม่อยู่ในรีโป. เมื่อสร้างเกตเวย์บนพอร์ต 8421 ให้มีครบสามเส้นในชื่อนี้เท่านั้น (หน้าเว็บไม่เรียกชื่ออื่น):

1. `/auth/google` — เริ่ม, callback, `mode=status`, `mode=logout` ตามสคีมาด้านบน
2. `GET /api/cluster/status` — รายงาน 8420 เป็น `worker` และ 8421 เป็น `dashboard`
3. `GET /api/logs/stream` — SSE เป็นค่าหลัก, ก้อนละไม่เกิน 32KB

`local_dashboard/server.py` เป็นโปรเซสโหนดงานบน 8420. หน้าเว็บไม่ import และไม่เรียกมันตรง ๆ. ให้เกตเวย์เป็นคนตรวจแล้วใส่ผลใน `/api/cluster/status`
ถ้า 8420 ดับ แดชบอร์ดบน 8421 ต้องยังเปิดอยู่ และรายงาน 8420 เป็น `down`. ห้ามย้ายหน้าเว็บไป origin อื่น

### ออฟโหลด I/O ที่บล็อก

งานที่รอดิสก์หรือซ็อกเก็ต (อ่าน SQLite, อ่านไฟล์ล็อก, ยิงตรวจพอร์ต 8420) ต้องออกจากเธรดที่รับ HTTP ไปที่:

```python
ThreadPoolExecutor(max_workers=2)
```

เครื่องนี้มี 4 เธรดและ RAM 8GB. ไม่ต้องเปิดพูลใหญ่กว่า 2 สำหรับงานบล็อกของแดชบอร์ด

### SQLite WAL และไฟล์ชั่วคราว

- `PRAGMA journal_mode=WAL;`
- `PRAGMA synchronous=NORMAL;`
- ตอนปิดแบบปกติ: `PRAGMA wal_checkpoint(TRUNCATE);` แล้วปิด connection เพื่อให้ไฟล์ `-wal` และ `-shm` หาย
- ตอนเริ่ม ถ้าเจอ `*.db-wal` / `*.db-shm` ค้างโดยไม่มีโปรเซสเจ้าของ ให้เปิดฐานแล้ว checkpoint
- ลบ `*.db.tmp` และ `*.db-journal` ใน `finally` ทั้งตอนรันและตอนเทส
- อย่าวางไฟล์ฐานข้อมูลไว้ใน `local_dashboard/web/` เพราะโฟลเดอร์นั้นถูกเสิร์ฟเป็นไฟล์สถิต
- ถ้าฐานถูกล็อกหรือหาย ให้ `/api/logs/stream` ตอบ `503` ตามสคีมาด้านบน ทั้งโปรเซสต้องไม่ล้ม

### สตรีมและ CORS

- เขียนก้อนล็อกทีละไม่เกิน 32768 ไบต์
- `CORSMiddleware` (หรือส่วนที่ทำหน้าที่เดียวกัน) ใช้ `allow_origins` สองค่าด้านบนเท่านั้น ห้าม `*`
- ไม่ใช้ uvicorn ในสคริปต์ที่ Nammon เปิดด้วย `start-dashboard.cmd`. PR นี้ไม่แก้ไฟล์ cmd นั้น
