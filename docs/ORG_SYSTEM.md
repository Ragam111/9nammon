# LCA — Org System (CEO / Admin / User + API Key)

ระบบองค์กรที่เพิ่มเข้า LCA เพื่อรองรับหลายผู้ใช้/หลายสิทธิ์ + จัดการ API key แบบ free/paid
ยึดสไตล์เดิมของโปรเจกต์: **stdlib ล้วน, JSON store ต่อโปรเจกต์, unittest (ไม่ใช้ pytest)**

## ทำไมต้องมี
`server.py` เดิมใช้ token เดี่ยวตัวเดียว — ใครมี token ก็ทำได้ทุกอย่าง ไม่พอสำหรับองค์กร
โมดูลนี้เพิ่ม 3 อย่าง: **ใครเป็นใคร** (user), **ทำอะไรได้** (role), **ใช้ API ได้เท่าไร** (quota)

## บทบาท (สูง → ต่ำ)
| Role | ทำได้ |
|------|-------|
| **CEO** | ทุกอย่าง + ตั้ง ADMIN + ดูภาพรวมทั้งองค์กร |
| **ADMIN** | ของ USER + สร้าง/ปิด user ระดับ USER + ออก/ยกเลิก API key |
| **USER** | แชท/ใช้งาน AI (กินโควตาตาม tier ของ key) |

- ADMIN สร้าง role ที่ ≥ ตัวเองไม่ได้ (สร้าง ADMIN/CEO ไม่ได้), ปิดบัญชี CEO ไม่ได้
- **user คนแรกต้องเป็น CEO** (bootstrap) — สร้างได้โดยไม่ต้อง auth ตอนระบบยังว่าง

## API Key & Quota
| Tier | โควตา/วัน | ใช้กับ |
|------|-----------|--------|
| `free` | 100 requests | ผู้ใช้ทั่วไป / ทดลอง |
| `paid` | ไม่จำกัด | ซื้อ API / ลูกค้าจ่ายเงิน |

- key สุ่มด้วย `secrets`, รูปแบบ `lca_<f|p>_<random>` — **โชว์ค่าเต็มครั้งเดียวตอนสร้าง** หลังจากนั้นเก็บแค่ sha256 hash
- โควตารีเซ็ตอัตโนมัติเมื่อข้ามวัน

## Module Contract — `app/org_store.py`
- **Dependencies**: stdlib เท่านั้น (`hashlib`, `hmac`, `secrets`, `json`, `datetime`, `pathlib`)
- **Store**: `org.json` ที่ project_root (อยู่ใน `.gitignore` — Rule 23)
- **Security**:
  - รหัสผ่าน = `pbkdf2_hmac(sha256)` + salt สุ่ม 200k iterations (ไม่เคยเก็บ plaintext)
  - API key เก็บแค่ sha256 hash + prefix 12 ตัวแรกไว้โชว์ระบุตัว
  - เทียบค่าด้วย `hmac.compare_digest` (กัน timing attack)
  - `list_*` ไม่คืน hash/key เต็ม
- **Error Handling**: `org.json` เสีย → warn แล้วถือว่าว่าง (ไม่ crash); input/สิทธิ์ผิด → `ValueError` ให้ caller แปลงเป็น HTTP error

## HTTP API (เพิ่มใน `server.py`)
Auth 2 ทาง: `X-Auth-Token` (master = CEO, bootstrap/ดูแลระบบ) หรือ `X-API-Key` (resolve เป็น user/role/tier)

| Method | Path | สิทธิ์ขั้นต่ำ | หน้าที่ |
|--------|------|--------------|---------|
| POST | `/api/admin/users` | ADMIN* | สร้าง user (*ตอน bootstrap สร้าง CEO คนแรกได้โดยไม่ต้อง auth) |
| GET | `/api/admin/users` | ADMIN | รายชื่อ user (ไม่มี hash) |
| POST | `/api/admin/users/active` | ADMIN | เปิด/ปิด user |
| POST | `/api/admin/apikeys` | ADMIN | ออก API key (คืน key เต็มครั้งเดียว) |
| GET | `/api/admin/apikeys` | ADMIN | รายการ key (prefix เท่านั้น) |
| POST | `/api/admin/apikeys/revoke` | ADMIN | ยกเลิก key |
| GET | `/api/me` | USER | ดูตัวตน/role/tier ของตัวเอง |
| POST | `/api/chat` | USER | แชท — กินโควตาถ้าเข้ามาด้วย API key (เกิน → 429) |

> โหมด local ล้วน (ไม่ตั้ง `--token`, bind 127.0.0.1): ถือเป็น CEO เหมือนพฤติกรรมเดิม — ใช้พัฒนา/ใช้คนเดียวได้สะดวก

## ตัวอย่างใช้งาน (curl)
```bash
# 1) bootstrap CEO คนแรก (ระบบยังว่าง ไม่ต้อง auth)
curl -X POST localhost:8420/api/admin/users \
  -d '{"username":"boss","password":"password123","role":"CEO"}'

# 2) CEO สร้าง USER แล้วออก free key (ใช้ master token)
curl -X POST localhost:8420/api/admin/users -H "X-Auth-Token: $TOKEN" \
  -d '{"username":"dev","password":"password123","role":"USER"}'
curl -X POST localhost:8420/api/admin/apikeys -H "X-Auth-Token: $TOKEN" \
  -d '{"owner":"dev","tier":"free"}'      # << เก็บ key ที่คืนมาไว้เลย

# 3) dev ใช้ key แชท
curl -X POST localhost:8420/api/chat -H "X-API-Key: lca_f_xxxx" \
  -d '{"messages":[{"role":"user","content":"hi"}]}'
```

## Tests
`tests/test_org_store.py` (21 เคส — logic) + `tests/test_server_org.py` (2 เคส — HTTP/RBAC/quota)
```bash
python3 -m unittest discover -s tests
```

## ยังไม่ทำ / ข้อจำกัด (ไม่ปิดบัง ตามหลัก 9arm)
- ยังไม่มี **admin UI** บนหน้าเว็บ (`index.html`) — ตอนนี้จัดการผ่าน API/curl เท่านั้น
- ยังไม่มี **session/login cookie** — client ต้องแนบ header ทุก request (เหมาะกับ API, ยังไม่เหมาะกับ UI คนทั่วไป)
- quota เป็นแบบ **รายวันต่อ key** เท่านั้น ยังไม่มี rate-limit รายวินาที/รายเดือน
- ยังไม่ทดสอบบน Windows จริง (แซนด์บ็อกซ์เป็น Linux)
