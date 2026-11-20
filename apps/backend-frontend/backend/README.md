# backend-frontend API (FastAPI)

Auth ด้วย session cookie แบบ httpOnly, quota ต่อผู้ใช้, rate limit ต่อผู้ใช้และต่อ IP และ proxy แบบ streaming ไปยังโมเดลที่รองรับ OpenAI-compatible `/chat/completions` (เช่น Ollama ในเครื่อง)

## รันในเครื่อง

```powershell
cd apps/backend-frontend/backend
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe --exclude-newer 2026-11-06 -r requirements.lock
copy ..\.env.example .env
```

แก้ค่าใน `.env` ตามต้องการ แล้วสร้างผู้ใช้คนแรก (ระบบจะถามรหัสผ่านโดยไม่แสดงบนจอ)

```powershell
.venv\Scripts\python.exe -m scripts.create_user admin --admin
```

เปิด server

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

app อ่าน `.env` ในโฟลเดอร์ที่รันเอง (หรือไฟล์ที่ระบุใน `ENV_FILE`) ค่าจาก environment จริงจะชนะค่าในไฟล์

## โหมด dev (ไม่ต้องมีโมเดลจริง)

เปิดสามหน้าต่าง: โมเดลจำลอง, API และหน้าเว็บ

```powershell
.venv\Scripts\python.exe scripts\fake_model.py 9100
```

```powershell
.venv\Scripts\python.exe scripts\dev_server.py
```

```powershell
cd ..\frontend
npm run dev
```

API โหมด dev รันที่ port 8010 และ Vite ส่งต่อ `/api` ไปที่นั่น ข้อมูลเก็บใน `data-dev/` ใส่คำในข้อความเพื่อจำลองปัญหา: `badkey` (key ผิด), `busy` (บริการล่ม), `slowstart` (ตอบช้า 3 วินาที), `drop` (เน็ตหลุดกลางทาง)

## Endpoint

| Method | Path | ต้อง login | หมายเหตุ |
|---|---|---|---|
| GET | `/api/health` | ไม่ | สถานะ server และว่าตั้ง key แล้วหรือยัง (ไม่คืนค่า key) |
| POST | `/api/auth/login` | ไม่ | ตั้ง cookie `bf_session` (HttpOnly, SameSite=Lax) |
| POST | `/api/auth/logout` | ไม่ | ลบ session |
| GET | `/api/auth/me` | ใช่ | ผู้ใช้ปัจจุบัน |
| GET | `/api/settings` | ใช่ | สถานะ key (4 ตัวท้าย), quota, rate limit, ขีดจำกัด |
| GET / PUT / DELETE | `/api/settings/key` | PUT/DELETE เฉพาะ admin | ตั้ง key ผ่าน onboarding; คืนเฉพาะ 4 ตัวท้าย |
| POST | `/api/run` | ใช่ | SSE: `start`, `delta`, `done` หรือ `error` (มี `partial` เมื่อได้ผลมาบางส่วน) |
| GET | `/api/history` | ใช่ | `q`, `status` (ok/partial/error), `limit`, `offset` |
| GET / DELETE | `/api/history/{id}` | ใช่ | เห็นและลบได้เฉพาะของตัวเอง |

## ประเภท error

ทุก error ตอบเป็น `{"error": {"type", "message", "retryable", "request_id"}}` โดย `message` เป็นภาษาไทยที่บอกว่าทำอะไรต่อได้

| type | HTTP | retry |
|---|---|---|
| auth | 401 | ไม่ |
| quota | 429 | ไม่ |
| rate_limit | 429 (+ `Retry-After`) | ได้ |
| timeout | 504 | ได้ |
| validation | 422 | ไม่ |
| upstream | 502 | ได้ |
| unknown | 500 | ไม่ |

การเรียกโมเดลจะ retry แบบ exponential backoff เฉพาะ timeout, เชื่อมต่อไม่ได้, 429 และ 5xx และ retry เฉพาะก่อนได้ข้อมูลไบต์แรกเท่านั้น

## Log

ทุก request เขียน log เป็น JSON หนึ่งบรรทัด (request id, method, path, status, latency, error type) และทุกการรันโมเดลเขียนเพิ่ม (token, ค่าใช้จ่ายโดยประมาณ) ห้าม log prompt, ผลลัพธ์, key, cookie หรือรหัสผ่าน

## Test และ lint

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t .
.venv\Scripts\python.exe -m ruff check .
```

Eval set (ชุดคำถามคงที่ใน `evals/cases.json`) รันได้ด้วยคำสั่งเดียว:

```powershell
.venv\Scripts\python.exe -m scripts.run_eval --fake
.venv\Scripts\python.exe -m scripts.run_eval --out eval-report.json
```

`--fake` ใช้คำตอบอ้างอิงของแต่ละข้อ ใช้ตรวจว่าระบบทดสอบทำงานถูกต้อง ไม่ได้วัดโมเดล ส่วนการรันโดยไม่มี `--fake` เรียกโมเดลที่ตั้งใน `.env` และ exit 1 ถ้าผ่านต่ำกว่า `--min-pass` (ค่าเริ่มต้น 0.8)

## E2E (Playwright)

รันจากโฟลเดอร์ frontend ไม่ต้องเปิด server เอง ระบบจะเปิดโมเดลจำลอง, API และ Vite บน port 9101, 8011 และ 5174 ด้วยฐานข้อมูลใหม่ทุกครั้ง และใช้ Microsoft Edge ที่ติดตั้งอยู่แล้ว

```powershell
cd ..\frontend
npx playwright test
```
