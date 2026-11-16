@echo off
chcp 65001 >nul
REM start-lca.bat — ดับเบิลคลิกเพื่อเปิด Local Code Assistant (ไม่ต้องพิมพ์อะไร)
REM เปิดเซิร์ฟเวอร์ที่ 127.0.0.1:8420 แล้วเด้งเบราว์เซอร์ไปหน้าแชทให้อัตโนมัติ
title Local Code Assistant
echo ============================================
echo   Local Code Assistant
echo   กำลังเปิด... http://127.0.0.1:8420
echo   (ปิดหน้าต่างนี้เพื่อหยุดใช้งาน)
echo ============================================
REM รอ 3 วิให้เซิร์ฟเวอร์ตั้งตัว แล้วเปิดเบราว์เซอร์
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8420/"
python "%~dp0server.py" "%USERPROFILE%" --port 8420
echo.
echo เซิร์ฟเวอร์ปิดแล้ว
pause
