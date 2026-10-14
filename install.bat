@echo off
REM install.bat — สำหรับคนที่เปิดจาก CMD ตรงๆ (ดับเบิลคลิกได้)
REM เรียก install.ps1 ผ่าน PowerShell โดย bypass execution policy เฉพาะการรันนี้ครั้งเดียว
REM (ไม่แก้ execution policy ถาวรของเครื่อง)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
