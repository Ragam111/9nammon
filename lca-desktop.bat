@echo off
REM lca-desktop.bat — เปิด LCA เป็น "หน้าต่างแอป" (Edge/Chrome --app ไม่มีแถบ URL)
REM ใช้ start-lca.bat ตัวเดียวกัน (หน้าต่างเซิร์ฟเวอร์ย่อไว้) — ปิดหน้าต่าง "LCA server" เพื่อหยุดใช้งาน
start "LCA server" /min cmd /c ""%~dp0start-lca.bat" --app"
