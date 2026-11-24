@echo off
chcp 65001 >nul
REM lca-desktop.bat — เปิด LCA เป็น "หน้าต่างแอป" เหมือน Claude/OpenAI/Gemini Desktop
REM (เปิดเซิร์ฟเวอร์เบื้องหลัง + รอให้ตอบ 200 แล้วเปิดเบราว์เซอร์แบบ app-mode = ไม่มีแถบ URL/แท็บ ดูเหมือนแอปจริง)
title LCA Desktop
set "PORT=8420"
set "URL=http://127.0.0.1:%PORT%/"

REM 1) ตรวจพอร์ตก่อนเริ่ม — ถ้าชนให้หยุด ไม่เปิดแอปไปเจอตัวผิด
netstat -ano -p tcp | findstr /R /C:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo [ผิดพลาด] พอร์ต %PORT% ถูกใช้อยู่แล้ว - LCA อาจเปิดค้างอยู่
  echo  - ปิดหน้าต่าง "LCA server" เดิม หรือโปรแกรมที่ใช้พอร์ตนี้ แล้วลองใหม่
  pause
  exit /b 1
)

REM 2) เปิดเซิร์ฟเวอร์เบื้องหลัง (หน้าต่างเล็ก — ปิดเพื่อหยุดใช้งาน)
start "LCA server" /min cmd /c python "%~dp0server.py" "%USERPROFILE%" --port %PORT%

REM 3) รอความพร้อมจริง: GET / ต้องได้ 200 ภายใน deadline 30 วินาที (เทียบเวลาจริง ไม่ใช่นับรอบ)
powershell -NoProfile -Command "$ok=$false; $deadline=(Get-Date).AddSeconds(30); while((Get-Date) -lt $deadline){ $left=[int][math]::Floor(($deadline-(Get-Date)).TotalSeconds); if($left -lt 1){$left=1}; if($left -gt 2){$left=2}; try{ if((Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -TimeoutSec $left).StatusCode -eq 200){$ok=$true;break} }catch{}; if((Get-Date) -lt $deadline){ Start-Sleep -Milliseconds 500 } }; if($ok){exit 0}else{exit 1}"
if errorlevel 1 (
  echo [ผิดพลาด] LCA server ไม่ตอบ 200 ที่ %URL% ภายใน 30 วินาที
  echo  - ดูหน้าต่าง "LCA server" ที่ย่อไว้ เพื่อดูสาเหตุ
  pause
  exit /b 1
)

REM 4) เปิดเป็นหน้าต่างแอป — ลอง Edge ก่อน, ไม่มีค่อย Chrome, ไม่มีค่อยเบราว์เซอร์ปกติ
start "" msedge --app=%URL% 2>nul || start "" chrome --app=%URL% 2>nul || start "" "%URL%"
echo เปิด LCA Desktop แล้ว — ปิดหน้าต่าง "LCA server" (สีดำ) เพื่อหยุดใช้งาน
