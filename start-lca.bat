@echo off
chcp 65001 >nul
REM start-lca.bat — ดับเบิลคลิกเพื่อเปิด Local Code Assistant (ไม่ต้องพิมพ์อะไร)
REM server.py --open browser เปิดเบราว์เซอร์ให้เองหลังพร้อม (ไม่เดาเวลา ได้พอร์ตจริงแม้ 8420 ไม่ว่าง)
REM โหมดหน้าต่างแอป: lca-desktop.bat (= ไฟล์นี้ + --open app)
title Local Code Assistant
set "LCA_OPEN=browser"
if /i "%~1"=="--app" set "LCA_OPEN=app"
echo ============================================
echo   Local Code Assistant  (ปิดหน้าต่างนี้เพื่อหยุดใช้งาน)
echo ============================================
python "%~dp0server.py" "%USERPROFILE%" --port 8420 --open %LCA_OPEN%
echo.
echo เซิร์ฟเวอร์ปิดแล้ว
pause
