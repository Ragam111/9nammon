# install.ps1 — ตัวติดตั้ง Local Code Assistant บน Windows 10/11 (AMD64)
# รันด้วย: powershell -ExecutionPolicy Bypass -File install.ps1
# (หรือดับเบิลคลิก install.bat ซึ่งเรียกไฟล์นี้ให้อัตโนมัติ)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CurrentVersion = "0.1.0"

Write-Host "=== Local Code Assistant v$CurrentVersion — ตัวติดตั้ง (Windows) ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "** แนะนำที่สุด: LCA-Desktop.exe (ก้อนเดียวจริง ไม่ต้องลง Python) **" -ForegroundColor Yellow
Write-Host "   https://github.com/Ragam111/9nammon/releases/latest" -ForegroundColor Yellow
Write-Host "   ดับเบิลคลิก LCA-Desktop.exe → หน้าต่างแชตเปิดเลย (~10 MB)" -ForegroundColor DarkGray
Write-Host "   (สคริปต์นี้สำหรับคนมี Python แล้วอยากติดตั้งแบบระบบ)" -ForegroundColor DarkGray
Write-Host ""

# ---------- ขั้นตอน 0: เลือกไดรฟ์ติดตั้ง (ถามเสมอ ไม่ fallback เงียบๆ) ----------
# ค่าเริ่มต้นคือ %LOCALAPPDATA% (มักอยู่บน C:) แต่ถ้าผู้ใช้อยากติดตั้งบนไดรฟ์อื่น
# เช่น D: (พื้นที่ C: จำกัด) ให้เลือกได้ตรงนี้ — เช็คว่าไดรฟ์ที่เลือกมีอยู่จริงก่อนเสมอ
Write-Host ""
Write-Host "จะติดตั้งที่ไดรฟ์ไหน?"
Write-Host "  [1] ค่าเริ่มต้น ($env:LOCALAPPDATA)"
Write-Host "  [2] ไดรฟ์ D: (D:\LocalCodeAssistant)"
Write-Host "  [3] ระบุ path เอง"
$driveChoice = Read-Host "เลือก (1/2/3, กด Enter = 1)"

switch ($driveChoice) {
    "2" {
        if (-not (Test-Path "D:\")) {
            Write-Host "[error] ไม่พบไดรฟ์ D: บนเครื่องนี้ — เลือกตัวเลือกอื่นแทน" -ForegroundColor Red
            exit 1
        }
        $freeSpaceGB = [math]::Round((Get-PSDrive D).Free / 1GB, 1)
        if ($freeSpaceGB -lt 2) {
            Write-Host "[error] ไดรฟ์ D: เหลือพื้นที่แค่ ${freeSpaceGB}GB (ต้องการอย่างน้อย 2GB สำหรับตัวโปรแกรม" -ForegroundColor Red
            Write-Host "        ไม่รวมโมเดล Ollama ที่แยก pull เองซึ่งอาจกินอีกหลาย GB) — เลือกตัวเลือกอื่นแทน" -ForegroundColor Red
            exit 1
        }
        $InstallDir = "D:\LocalCodeAssistant"
        Write-Host "[ok] ติดตั้งที่ D:\LocalCodeAssistant (เหลือพื้นที่ ${freeSpaceGB}GB)"
    }
    "3" {
        $customPath = Read-Host "พิมพ์ path เต็มที่ต้องการติดตั้ง (เช่น E:\Tools\LCA)"
        $customDrive = (Split-Path -Qualifier $customPath -ErrorAction SilentlyContinue)
        if (-not $customDrive -or -not (Test-Path "$customDrive\")) {
            Write-Host "[error] ไม่พบไดรฟ์ที่ระบุ ($customPath) — ยกเลิกการติดตั้ง" -ForegroundColor Red
            exit 1
        }
        $InstallDir = $customPath
        Write-Host "[ok] ติดตั้งที่ $InstallDir"
    }
    default {
        $InstallDir = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant"
        Write-Host "[ok] ติดตั้งที่ค่าเริ่มต้น: $InstallDir"
    }
}

$VersionFile = Join-Path $InstallDir "version.txt"

# ---------- ขั้นตอน 1: ตรวจสอบ Python ----------
function Test-Command($name) {
    try { Get-Command $name -ErrorAction Stop | Out-Null; return $true }
    catch { return $false }
}

$pythonCmd = $null
foreach ($candidate in @("python", "python3")) {
    if (Test-Command $candidate) { $pythonCmd = $candidate; break }
}
if (-not $pythonCmd) {
    Write-Host "[error] ไม่พบ Python ในเครื่อง — ติดตั้งก่อนที่ https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "        (เลือก 'Add python.exe to PATH' ตอนติดตั้งด้วย)" -ForegroundColor Yellow
    exit 1
}
Write-Host "[ok] พบ Python: $pythonCmd"

# ---------- ขั้นตอน 2: ตรวจสอบ Ollama ----------
$hasOllama = Test-Command "ollama"
if (-not $hasOllama) {
    Write-Host "[warn] ไม่พบ Ollama ในเครื่อง — ดาวน์โหลดที่ https://ollama.com/download/windows" -ForegroundColor Yellow
    Write-Host "        ติดตั้งเสร็จแล้วรัน install.ps1 นี้ใหม่อีกครั้ง (หรือรันต่อได้ แต่ pull โมเดลเองทีหลัง)"
} else {
    Write-Host "[ok] พบ Ollama"
}

# ---------- ขั้นตอน 3: ตรวจ RAM แล้วเลือกโมเดลที่แนะนำ ----------
$totalRamBytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
$totalRamGB = [math]::Round($totalRamBytes / 1GB, 1)

function Get-RecommendedModel($ramGB) {
    if ($ramGB -lt 8)  { return @{ Model = "qwen2.5-coder:0.5b"; Tier = "ต่ำกว่า 8GB (ใช้โมเดลเล็กสุด อาจยังหน่วง)" } }
    if ($ramGB -lt 16) { return @{ Model = "qwen2.5-coder:1.5b"; Tier = "8GB" } }
    if ($ramGB -lt 32) { return @{ Model = "qwen2.5-coder:7b";   Tier = "16GB" } }
    if ($ramGB -lt 64) { return @{ Model = "qwen2.5-coder:14b";  Tier = "32GB" } }
    return @{ Model = "qwen2.5-coder:32b"; Tier = "64GB ขึ้นไป" }
}

$rec = Get-RecommendedModel $totalRamGB
Write-Host ""
Write-Host "[ram] เครื่องนี้มี RAM ประมาณ $totalRamGB GB (ระดับ: $($rec.Tier))"
Write-Host "[ram] โมเดลที่แนะนำ: $($rec.Model)" -ForegroundColor Green

$modelChoice = Read-Host "กด Enter เพื่อใช้โมเดลที่แนะนำ หรือพิมพ์ชื่อโมเดล Ollama อื่นที่ต้องการ"
if ([string]::IsNullOrWhiteSpace($modelChoice)) { $modelChoice = $rec.Model }

# ---------- ขั้นตอน 4: คัดลอกไฟล์ไปที่โฟลเดอร์ติดตั้ง ----------
if (Test-Path $InstallDir) {
    Write-Host "[info] พบการติดตั้งเดิมที่ $InstallDir — ไฟล์ผู้ใช้ (todos.json, CHANGELOG_local.md) จะไม่ถูกลบ"
} else {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
}

Copy-Item -Path (Join-Path $ScriptRoot "local_coder.py") -Destination $InstallDir -Force
Copy-Item -Path (Join-Path $ScriptRoot "server.py") -Destination $InstallDir -Force
if (Test-Path (Join-Path $ScriptRoot "requirements.txt")) {
    Copy-Item -Path (Join-Path $ScriptRoot "requirements.txt") -Destination $InstallDir -Force
}

# app\ มีโมดูลทั้งหมดแล้ว (folder_trust.py, context_manager.py, app.css ฯลฯ รวมอยู่ในนี้)
# — ก๊อปทั้งโฟลเดอร์ ไม่ต้องไล่ก๊อปทีละไฟล์จาก root (ไฟล์พวกนั้นไม่ได้อยู่ที่ root แล้ว)
$AppDestDir = Join-Path $InstallDir "app"
if (-not (Test-Path $AppDestDir)) { New-Item -ItemType Directory -Path $AppDestDir | Out-Null }
Copy-Item -Path (Join-Path $ScriptRoot "app\*") -Destination $AppDestDir -Recurse -Force

# sysmanager\ — จำเป็นสำหรับ lca-web (server.py import sysmanager.sysinfo / sysmanager.monitor)
if (Test-Path (Join-Path $ScriptRoot "sysmanager")) {
    $SysDestDir = Join-Path $InstallDir "sysmanager"
    if (Test-Path $SysDestDir) { Remove-Item $SysDestDir -Recurse -Force }
    Copy-Item -Path (Join-Path $ScriptRoot "sysmanager") -Destination $InstallDir -Recurse -Force
}

# psutil = dependency เดียวนอก stdlib (sysmanager ใช้) — ติดตั้งแบบ best-effort ไม่บล็อกถ้าล้ม
Write-Host "[info] ติดตั้ง dependency (psutil)..."
try {
    & $pythonCmd -m pip install --user --quiet psutil 2>$null
    Write-Host "[ok] psutil พร้อม (หรือมีอยู่แล้ว)"
} catch {
    Write-Host "[warn] ติดตั้ง psutil ไม่สำเร็จ — หน้าเว็บ/metrics อาจใช้ไม่ได้ ลองรันเอง: $pythonCmd -m pip install psutil" -ForegroundColor Yellow
}

Set-Content -Path $VersionFile -Value $CurrentVersion -Encoding UTF8
Set-Content -Path (Join-Path $InstallDir "default_model.txt") -Value $modelChoice -Encoding UTF8

Write-Host "[ok] ติดตั้งไฟล์ไปที่ $InstallDir แล้ว"

# ---------- ขั้นตอน 5: สร้าง launcher (lca.bat) ----------
$LauncherPath = Join-Path $InstallDir "lca.bat"
$LauncherContent = @"
@echo off
REM lca.bat — เรียกใช้ Local Code Assistant จากที่ไหนก็ได้ใน terminal
$pythonCmd "$InstallDir\local_coder.py" --model $modelChoice %*
"@
Set-Content -Path $LauncherPath -Value $LauncherContent -Encoding ASCII

# ตัวดับเบิลคลิก: เปิดเซิร์ฟเวอร์ + เด้งเบราว์เซอร์ให้อัตโนมัติ (ผู้ใช้ไม่ต้องพิมพ์อะไร)
$StartLauncherPath = Join-Path $InstallDir "start-lca.bat"
$StartLauncherContent = @"
@echo off
chcp 65001 >nul
title Local Code Assistant
echo ============================================
echo   Local Code Assistant
echo   กำลังเปิด... http://127.0.0.1:8420
echo   (ปิดหน้าต่างนี้เพื่อหยุดใช้งาน)
echo ============================================
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8420/"
$pythonCmd "$InstallDir\server.py" "%USERPROFILE%" --port 8420
echo.
echo เซิร์ฟเวอร์ปิดแล้ว
pause
"@
Set-Content -Path $StartLauncherPath -Value $StartLauncherContent -Encoding UTF8

# โหมด Desktop app: เปิดเป็นหน้าต่างแอป (app-mode) เหมือน Claude/OpenAI/Gemini Desktop
$DesktopLauncherPath = Join-Path $InstallDir "lca-desktop.bat"
$DesktopLauncherContent = @"
@echo off
chcp 65001 >nul
title LCA Desktop
set "URL=http://127.0.0.1:8420/"
start "LCA server" /min cmd /c $pythonCmd "$InstallDir\server.py" "%USERPROFILE%" --port 8420
timeout /t 3 >nul
start "" msedge --app=%URL% 2>nul || start "" chrome --app=%URL% 2>nul || start "" "%URL%"
echo เปิด LCA Desktop แล้ว — ปิดหน้าต่าง "LCA server" เพื่อหยุดใช้งาน
"@
Set-Content -Path $DesktopLauncherPath -Value $DesktopLauncherContent -Encoding UTF8

Write-Host "[ok] สร้าง launcher แล้ว: lca.bat (CLI), start-lca.bat, lca-desktop.bat (โหมดแอป), lca-tray.bat (tray)"

# ---------- ขั้นตอน 6: เพิ่ม InstallDir เข้า PATH ผู้ใช้ (ถ้ายังไม่มี) ----------
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentPath;$InstallDir", "User")
    Write-Host "[ok] เพิ่ม $InstallDir เข้า PATH แล้ว — ต้องเปิด terminal ใหม่ถึงจะเรียก lca ได้ทุกที่"
} else {
    Write-Host "[ok] $InstallDir อยู่ใน PATH อยู่แล้ว"
}

# ---------- สรุป ----------
Write-Host ""
Write-Host "=== ติดตั้งเสร็จสมบูรณ์ ===" -ForegroundColor Cyan
Write-Host "1. เปิด terminal (CMD/PowerShell) ใหม่"
if ($hasOllama) {
    Write-Host "2. ดึงโมเดล: ollama pull $modelChoice"
} else {
    Write-Host "2. ติดตั้ง Ollama ก่อน แล้วรัน: ollama pull $modelChoice"
}
Write-Host "3. วิธีง่ายสุด: ดับเบิลคลิก start-lca.bat ที่ $InstallDir" -ForegroundColor Green
Write-Host "   (เปิดเซิร์ฟเวอร์ + เด้งเบราว์เซอร์หน้าแชทให้อัตโนมัติ)"
Write-Host "   หรือใช้ terminal: lca C:\path\to\project"
# เปิดโฟลเดอร์ติดตั้งให้ผู้ใช้เห็น start-lca.bat ได้ทันที
try { Start-Process explorer.exe $InstallDir } catch {}
