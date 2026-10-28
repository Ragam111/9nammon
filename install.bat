@echo off
chcp 65001 >nul
REM install.bat — ดับเบิลคลิกเพื่อติดตั้ง Local Code Assistant (ไม่ต้องใช้เทอร์มินัล)
REM เรียก install.ps1 ผ่าน PowerShell โดย bypass execution policy เฉพาะครั้งนี้
REM (ไม่แก้ execution policy ถาวรของเครื่อง)
title ติดตั้ง Local Code Assistant
echo ============================================
echo   ติดตั้ง Local Code Assistant (LCA)
echo ============================================
echo.
where powershell >nul 2>&1
if errorlevel 1 (
  echo [error] ไม่พบ PowerShell บนเครื่องนี้ — ติดตั้งไม่ได้
  echo ลองเปิดจากเครื่อง Windows ปกติ หรือดูวิธีติดตั้งด้วยมือใน README.md
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
echo ----------------------------------------------------------
echo ติดตั้งเสร็จแล้ว — เปิดใช้งานด้วยการดับเบิลคลิก start-lca.bat
echo (ตัวติดตั้งเปิดโฟลเดอร์ให้แล้ว มองหาไฟล์ start-lca.bat)
echo ----------------------------------------------------------
pause
