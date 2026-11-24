@echo off
chcp 65001 >nul
REM start-lca.bat — ดับเบิลคลิกเพื่อเปิด Local Code Assistant (ไม่ต้องพิมพ์อะไร)
REM เปิดเซิร์ฟเวอร์ที่ 127.0.0.1:%PORT% แล้วเปิดเบราว์เซอร์เมื่อเซิร์ฟเวอร์ตอบ 200 เท่านั้น
title Local Code Assistant
set "PORT=8420"
set "URL=http://127.0.0.1:%PORT%/"

REM 1) ตรวจพอร์ตก่อนเริ่ม — ถ้ามีโปรเซสอื่น LISTEN อยู่ หยุดทันที ไม่เปิดเบราว์เซอร์ (กันเปิดไปเจอแอปผิดตัว)
netstat -ano -p tcp | findstr /R /C:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo [ผิดพลาด] พอร์ต %PORT% ถูกใช้อยู่แล้ว - อาจมี LCA หรือโปรแกรมอื่นรันค้างอยู่
  echo  - ถ้าเป็น LCA เดิม ให้ใช้หน้าต่างเดิมต่อ หรือปิดหน้าต่างนั้นก่อนแล้วเปิดใหม่
  echo  - เซิร์ฟเวอร์จะไม่ขยับไปพอร์ตอื่นเอง จึงไม่เปิดเบราว์เซอร์ให้
  pause
  exit /b 1
)

echo ============================================
echo   Local Code Assistant
echo   กำลังเปิด... %URL%
echo   (ปิดหน้าต่างนี้เพื่อหยุดใช้งาน)
echo ============================================

REM 2) รอความพร้อมจริง: เปิดเบราว์เซอร์เมื่อ GET / ได้ 200 (deadline 30 วินาทีตามนาฬิกาจริง ไม่ใช่นับรอบ) ทำใน process แยก
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "$ok=$false; $deadline=(Get-Date).AddSeconds(30); while((Get-Date) -lt $deadline){ $left=[int][math]::Floor(($deadline-(Get-Date)).TotalSeconds); if($left -lt 1){$left=1}; if($left -gt 2){$left=2}; try{ if((Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -TimeoutSec $left).StatusCode -eq 200){$ok=$true;break} }catch{}; if((Get-Date) -lt $deadline){ Start-Sleep -Milliseconds 500 } }; if($ok){ Start-Process '%URL%' } else { Add-Type -AssemblyName System.Windows.Forms; [void][System.Windows.Forms.MessageBox]::Show('LCA did not return HTTP 200 at %URL% within 30 seconds. Check the server window for errors.','LCA start failed') }"

REM 3) เปิดเซิร์ฟเวอร์ (ค้างในหน้าต่างนี้ — ปิดหน้าต่างเพื่อหยุด)
python "%~dp0server.py" "%USERPROFILE%" --port %PORT%
echo.
echo เซิร์ฟเวอร์ปิดแล้ว
pause
