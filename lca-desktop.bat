@echo off
chcp 65001 >nul
REM lca-desktop.bat — เปิด LCA เป็น "หน้าต่างแอป" เหมือน Claude/OpenAI/Gemini Desktop
REM (เปิดเซิร์ฟเวอร์เบื้องหลัง + เปิดเบราว์เซอร์แบบ app-mode = ไม่มีแถบ URL/แท็บ ดูเหมือนแอปจริง)
title LCA Desktop
set "URL=http://127.0.0.1:8420/"
REM 1) เปิดเซิร์ฟเวอร์เบื้องหลัง (หน้าต่างเล็ก — ปิดเพื่อหยุดใช้งาน)
start "LCA server" /min cmd /c python "%~dp0server.py" "%USERPROFILE%" --port 8420
REM 2) รอให้เซิร์ฟเวอร์ตั้งตัว
timeout /t 3 >nul
REM 3) เปิดเป็นหน้าต่างแอป — ลอง Edge ก่อน, ไม่มีค่อย Chrome, ไม่มีค่อยเบราว์เซอร์ปกติ
start "" msedge --app=%URL% 2>nul || start "" chrome --app=%URL% 2>nul || start "" "%URL%"
echo เปิด LCA Desktop แล้ว — ปิดหน้าต่าง "LCA server" (สีดำ) เพื่อหยุดใช้งาน
