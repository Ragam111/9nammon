@echo off
chcp 65001 >nul
REM lca-tray.bat — เริ่ม LCA เป็น tray app (ซ่อนหน้าต่าง PowerShell)
REM ดับเบิลคลิกเพื่อเริ่ม — ไอคอนจะโผล่ที่ system tray (ลูกศรบน taskbar)
REM ปิดโดยคลิกขวาไอคอน → "ออก"
title LCA Tray (hidden)
where powershell >nul 2>&1
if errorlevel 1 (
  echo [error] ไม่พบ PowerShell บนเครื่องนี้
  pause
  exit /b 1
)
REM -WindowStyle Hidden ซ่อนหน้าต่าง PowerShell, -ExecutionPolicy Bypass เฉพาะครั้งนี้
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0lca-tray.ps1"
