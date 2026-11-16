# เปิดแดชบอร์ดหลัก (พอร์ต 8421)

คู่มือนี้สำหรับ Windows 10 Pro x64, Intel Core i5-7400 (4C/4T), RAM 8GB, HDD หรือ SSD, การ์ดจอออนบอร์ด
หน้าเว็บอยู่ใน `local_dashboard/web/`. สัญญาที่ `app_server.py` ต้องทำให้ตรงอยู่ที่ `docs/FRONTEND_BACKEND_CONTRACT.md`

PR นี้ไม่แก้ `start-dashboard.cmd`, ไฟล์ `.ps1`, `dist/`, `downloads/`, `app_server.py`, `local_dashboard/server.py` หรือ `VERSION` (`0.3.4`)

## ไฟล์ที่ต้องมีใน `local_dashboard/web/`

คัดลอกทั้งชุดนี้ไปที่เครื่องที่มีเกตเวย์อยู่แล้ว (ชื่อไฟล์และที่อยู่ต้องตรง):

| ไฟล์ | หน้าที่ |
|---|---|
| `local_dashboard/web/index.html` | เปลือกหน้าเว็บ |
| `local_dashboard/web/css/dashboard.css` | สไตล์บาง ไม่มี blur / ฟอนต์จากเน็ต |
| `local_dashboard/web/js/main.js` | เราเตอร์ hash และสถานะล็อกอิน |
| `local_dashboard/web/js/config.js` | Client ID, origin, พอร์ต, ชื่อเส้น API |
| `local_dashboard/web/js/origin.js` | ตรวจ origin และสร้าง redirect URI |
| `local_dashboard/web/js/oauth.js` | เรียก `/auth/google` |
| `local_dashboard/web/js/auth-state.js` | สถานะ signed out / signing in / signed in / error |
| `local_dashboard/web/js/router.js` | เส้น `#/`, `#/logs`, `#/nodes`, `#/account` |
| `local_dashboard/web/js/log-buffer.js` | หั่นก้อน 32KB, ตัวอ่าน SSE, DocumentFragment |
| `local_dashboard/web/js/log-panel.js` | แผงล็อก เรียก `/api/logs/stream` |
| `local_dashboard/web/js/nodes.js` | แปลงผลพอร์ต 8420/8421 |
| `local_dashboard/web/js/node-panel.js` | แผงโหนด เรียก `/api/cluster/status` |
| `local_dashboard/web/js/poll.js` | ตัวตั้งเวลาที่หยุดเมื่อแท็บถูกซ่อน |
| `local_dashboard/web/js/dom.js` | สร้างโหนดด้วย textContent |
| `local_dashboard/web/manifest.webmanifest` | PWA manifest |
| `local_dashboard/web/sw.js` | service worker ที่ไม่เขียนแคชลงดิสก์ |
| `local_dashboard/web/icon.svg` | ไอคอนเล็ก |
| `local_dashboard/web/package.json` | บอกว่าไฟล์ JS เป็น ES module ไม่มี dependency |

ไฟล์ที่เกตเวย์และโหนดงานเป็นของ CodexGPT คนละที่ ไม่ได้อยู่ในชุดนี้:

| ไฟล์ | หน้าที่ |
|---|---|
| `start-dashboard.cmd` | ตัวเปิดที่รากโปรเจกต์ — Nammon แก้เอง |
| `app_server.py` | เกตเวย์หลัก พอร์ต 8421 |
| `local_dashboard/server.py` | โหนดงาน พอร์ต 8420 |

## ค่าที่ต้องตรงกัน

| ค่า | ตั้งเป็น |
|---|---|
| Google Client ID | `456424591178-g3ufhccbhmnvt74ne7hfq27432b3sm19.apps.googleusercontent.com` |
| Client secret | ห้ามอยู่ใน `local_dashboard/web/` |
| Authorized JavaScript origins | `http://localhost:8421` และ `http://127.0.0.1:8421` |
| Authorized redirect URIs | `http://localhost:8421/auth/google` และ `http://127.0.0.1:8421/auth/google` |
| พอร์ตโหนดงาน | `8420` |
| พอร์ตแดชบอร์ด | `8421` |
| เส้นที่หน้าเว็บเรียก | `/auth/google`, `/api/cluster/status`, `/api/logs/stream` |

## ตั้ง Google Cloud Console

1. เปิด [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. เลือก OAuth client ประเภท **Web application** ที่มี Client ID ด้านบน
3. Authorized JavaScript origins:
   - `http://localhost:8421`
   - `http://127.0.0.1:8421`
4. Authorized redirect URIs:
   - `http://localhost:8421/auth/google`
   - `http://127.0.0.1:8421/auth/google`
5. บันทึก. ไม่ต้องใส่ client secret ลงในหน้าเว็บ

## เปิดด้วย start-dashboard.cmd

1. อยู่ที่รากโปรเจกต์ที่มี `start-dashboard.cmd`, `app_server.py` และโฟลเดอร์ `local_dashboard/`
2. ดับเบิลคลิก `start-dashboard.cmd` (ไฟล์นี้ไม่ได้ถูกแก้ใน PR)
3. สคริปต์ควรสตาร์ตเกตเวย์ที่พอร์ต **8421** โดยเสิร์ฟ `local_dashboard/web/` เป็นเว็บรูท และปล่อยให้โหนดงานอยู่ที่พอร์ต **8420** เมื่อโปรเซสนั้นขึ้น
4. ต้องตอบได้ทั้ง `http://127.0.0.1:8421/` และ `http://localhost:8421/`
5. ไม่เรียก uvicorn และไม่ย้ายแดชบอร์ดไปพอร์ตอื่นเมื่อ 8420 ยังไม่ขึ้น
6. เปิดเบราว์เซอร์ที่ `http://127.0.0.1:8421/` แล้วตรวจว่าไม่มีแถบเตือน origin. จากนั้นเปิด `http://localhost:8421/` อีกครั้ง

ในรีโปนี้ยังไม่มี `app_server.py`. ระหว่างที่ CodexGPT ยังไม่ต่อเส้น API หน้าเว็บยังเปิดเป็นไฟล์สถิตได้ และจะขึ้น `not implemented` หรือ `offline`

## เช็กลิสต์ด้วยมือ

- [ ] ดับเบิลคลิก `start-dashboard.cmd` แล้วเปิด `http://127.0.0.1:8421/` ได้โดยไม่ต้องเปิด uvicorn
- [ ] `http://localhost:8421/` เปิดหน้าเดียวกัน และไม่มีแถบ `origin_mismatch`
- [ ] เปิดจากพอร์ตอื่นแล้วเห็นข้อความให้กลับไปที่สอง origin และปุ่ม Google กดไม่ได้
- [ ] ยังไม่ล็อกอิน: ข้อความ `ยังไม่ได้เข้าสู่ระบบ` หรือ `not implemented` / `offline` ถ้า `/auth/google` ยังไม่มี
- [ ] กดเข้าสู่ระบบแล้วเบราว์เซอร์ไปที่ `/auth/google?mode=start` (หรือเด้งต่อจากเกตเวย์ไป Google). ระหว่างนั้นสถานะเป็น `กำลังเข้าสู่ระบบ…` แล้วกลับมาเป็นชื่อหรืออีเมล หรือข้อความ error
- [ ] ในเน็ตเวิร์กของเบราว์เซอร์ไม่มี request ที่แนบ client secret และไม่มีเส้นนอกจาก `/auth/google`, `/api/cluster/status`, `/api/logs/stream` บวกไฟล์สถิต
- [ ] `#/logs` ขึ้นล็อก หรือ `not implemented` / `offline`. ปุ่มเลื่อนตามท้ายสลับได้
- [ ] `#/nodes` เห็นพอร์ต 8420 (โหนดงาน) และ 8421 (แดชบอร์ด) เป็น `up` / `down` / `not implemented`
- [ ] สลับแท็บเบราว์เซอร์ออกไปอย่างน้อย 10 วินาที แล้วกลับมา: ไม่มีการยิงรัวระหว่างที่แท็บถูกซ่อน
- [ ] `#/ไม่มีหน้านี้` มีลิงก์กลับภาพรวม
- [ ] `python -m unittest discover -s tests` ผ่าน และ `VERSION` ยังเป็น `0.3.4`
