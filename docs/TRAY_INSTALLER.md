# LCA Tray Installer — ใช้งานยังไง

**แนวคิด (จาก user):** หลังติดตั้งเสร็จ แอปอยู่ใน system tray (ลูกศรบน taskbar ของ Windows) เหมือน Discord/Steam — ไม่มีหน้าต่างสีดำค้าง, คลิกไอคอน → เปิดแอป

## วิธีติดตั้ง (ครั้งแรก)

1. ดาวน์โหลด installer (`TokenLCAlimit.exe` ที่แพ็กจาก `installer_gui.py`) — หรือรัน `python installer_gui.py` ตรงๆ
2. ดับเบิลคลิก → หน้าต่างติดตั้งโผล่
3. ตั้งค่า:
   - **ติดตั้งไปที่:** โฟลเดอร์ที่จะติดตั้ง (default: `%LOCALAPPDATA%\LocalCodeAssistant`)
   - **สร้าง icon บน Desktop:** ✅
   - **เริ่มใน system tray:** ✅ (แนะนำ — เหมือน Discord/Steam ไม่มีหน้าต่างค้าง)
4. กดปุ่ม "ติดตั้ง" → progress bar ขึ้น → เขียวเต็มหลอด = เสร็จ
5. กด Close

## วิธีเปิดใช้งาน (หลังติดตั้ง)

- ดับเบิลคลิก icon บน Desktop ("เปิด Local Code Assistant.bat")
- จะเริ่มเงียบๆ ในพื้นหลัง → ไอคอนโผล่ที่ system tray (ลูกศรบน taskbar)

## ควบคุมจาก tray

**คลิกซ้ายไอคอน:** เปิดหน้าต่างแอป (ลองใช้ Edge app-mode ก่อน, fallback เบราว์เซอร์ปกติ)

**คลิกขวาไอคอน:** เมนู
- **เปิดแอป** — เปิดหน้าต่างแชต (http://127.0.0.1:8420/)
- **เปิดคอนโซล** — เปิดคอนโซลตั้งค่า (http://127.0.0.1:8420/console)
- **ดู logs** — เปิด `%LOCALAPPDATA%\LocalCodeAssistant\data\lca-tray.log` ใน Notepad
- **ออก** — ปิดเซิร์ฟเวอร์ + เอาไอคอนออก (clean shutdown)

## ไฟล์ที่เกี่ยวข้อง

| ไฟล์ | หน้าที่ |
|------|---------|
| `installer_gui.py` | GUI installer (tkinter) — ดาวน์โหลด + extract + สร้าง shortcut |
| `lca-tray.ps1` | PowerShell script ที่สร้าง tray icon + รัน server เบื้องหลัง |
| `lca-tray.bat` | Launcher ของ `lca-tray.ps1` — ซ่อนหน้าต่าง PowerShell |
| `lca-desktop.bat` | โหมด "หน้าต่างแอป" (Edge --app) — มีหน้าต่าง server /min |
| `start-lca.bat` | โหมด "เปิดเซิร์ฟเวอร์ + เบราว์เซอร์ปกติ" — fallback |

## ความต้องการระบบ

- **Windows 10/11** (PowerShell + .NET Framework built-in)
- **Python 3.10+** ติดตั้งไว้แล้ว (`python` หรือ `py` ใน PATH)
- **Edge หรือ Chrome** (optional) — ถ้าไม่มีจะเปิดด้วยเบราว์เซอร์ default

## ซื่อตรง: ข้อจำกัด

- ใช้ `System.Windows.Forms.NotifyIcon` ของ .NET → **Windows เท่านั้น** (ไม่รองรับ Mac/Linux)
- Icon ใช้ `SystemIcons.Information` (ของในตัว) — ไม่ใช่ custom .ico. ถ้าอยากเปลี่ยน แก้ `lca-tray.ps1` บรรทัดที่ใส่ icon
- ไม่ใช่ native .exe — เป็น PowerShell script ที่ Windows มี runtime มาพร้อม

## แพ็ก installer เป็น .exe ไฟล์เดียว

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --name TokenLCAlimit installer_gui.py
# → dist\TokenLCAlimit.exe (แจกได้เลย)
```

## Troubleshooting

**ไอคอนไม่โผล่:** เช็ค `%LOCALAPPDATA%\LocalCodeAssistant\data\lca-tray.log` — ดู error. ลองรัน `lca-tray.ps1` ตรงๆ (ไม่ hidden) จะเห็น output จริง:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File lca-tray.ps1
```

**พอร์ต 8420 ชน:** เปิด `lca-tray.ps1` แก้ `$Port = 8420` เป็นเลขอื่น

**ปิดจาก Task Manager แล้ว tray ยังค้าง:** ไอคอน tray ของ Windows ค้างชั่วคราวจนกว่าจะ hover (บั๊กของ Windows เอง). รันแล้วหยุดโดยคลิกขวา → "ออก" จะเก็บกวาดเรียบร้อย
