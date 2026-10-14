# ============================================================================
# install_online.ps1 — ติดตั้ง Local Code Assistant แบบออนไลน์ (One-Liner)
# ไม่ต้อง Extract Zip เอง — สคริปต์นี้ดาวน์โหลด + แตกไฟล์ + ติดตั้งให้อัตโนมัติ
# ============================================================================
#
# วิธีใช้ (ผู้ใช้ปลายทางแปะบรรทัดเดียวใน PowerShell):
#   powershell -ExecutionPolicy Bypass -Command "iwr -useb <URL_ของไฟล์นี้> | iex"
#
# ⚠️ ก่อนแจกจ่าย one-liner นี้ให้ใครใช้ ต้องแก้ $DownloadUrl ด้านล่างนี้ก่อนเสมอ ⚠️
# ============================================================================

$ErrorActionPreference = "Stop"

# ─────────────────────────────────────────────────────────────────────────
# แก้ตรงนี้: ใส่ URL ของไฟล์ .zip จริงที่ host ไว้ (เช่น GitHub Releases asset)
#    ดูวิธีสร้าง GitHub Release + เอา URL มาใส่ตรงนี้ได้ใน ONLINE_INSTALL_GUIDE.md
# ─────────────────────────────────────────────────────────────────────────
$DownloadUrl = "https://github.com/YOUR_USER/YOUR_REPO/releases/latest/download/LocalCodeAssistant.zip"

# หมายเหตุความซื่อสัตย์ (Rule 21 / 9arm ข้อ 1 — ไม่แต่งเติม): ค่าด้านบนยังเป็น
# placeholder ที่ไม่มีไฟล์จริงอยู่ปลายทาง — สคริปต์นี้จะปฏิเสธทำงานทันทีถ้ายังไม่แก้
# (fail ดัง ไม่ fail เงียบ) เพื่อไม่ให้ผู้ใช้งงว่าทำไมดาวน์โหลดไม่ได้

$TempZipPath = Join-Path $env:TEMP "LocalCodeAssistant-download.zip"
$TempExtractPath = Join-Path $env:TEMP "LocalCodeAssistant-extract"
$InstallTargetDir = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant"

Write-Host "=== Local Code Assistant — ตัวติดตั้งออนไลน์ ===" -ForegroundColor Cyan

# ---------- Guard: เช็คว่า URL ถูกตั้งค่าแล้วจริงหรือยัง ----------
if ($DownloadUrl -like "*YOUR_USER/YOUR_REPO*") {
    Write-Host "[error] ยังไม่ได้ตั้งค่า `$DownloadUrl ให้ชี้ไปไฟล์จริง" -ForegroundColor Red
    Write-Host "        ผู้ดูแลโปรเจกต์ต้อง host ไฟล์ .zip บน GitHub Releases ก่อน" -ForegroundColor Red
    Write-Host "        แล้วแก้บรรทัด `$DownloadUrl ในสคริปต์นี้ (ดู ONLINE_INSTALL_GUIDE.md)" -ForegroundColor Red
    exit 1
}

# ---------- ขั้นตอน 1: ดาวน์โหลด zip ลง %TEMP% ----------
Write-Host "[1/5] กำลังดาวน์โหลดจาก $DownloadUrl ..."
try {
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $TempZipPath -UseBasicParsing
}
catch {
    Write-Host "[error] ดาวน์โหลดไม่สำเร็จ: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "        เช็คว่า internet เชื่อมต่ออยู่ และ URL ยังใช้งานได้จริง" -ForegroundColor Red
    exit 1
}
$sizeMB = [math]::Round((Get-Item $TempZipPath).Length / 1MB, 1)
Write-Host "[ok] ดาวน์โหลดเสร็จ (${sizeMB}MB) -> $TempZipPath"

# ---------- ขั้นตอน 2: แตกไฟล์ (Expand-Archive) ----------
Write-Host "[2/5] กำลังแตกไฟล์..."
try {
    if (Test-Path $TempExtractPath) {
        Remove-Item -Path $TempExtractPath -Recurse -Force
    }
    Expand-Archive -Path $TempZipPath -DestinationPath $TempExtractPath -Force
}
catch {
    Write-Host "[error] แตกไฟล์ไม่สำเร็จ: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "        ไฟล์อาจดาวน์โหลดไม่สมบูรณ์ ลองรันสคริปต์นี้ใหม่อีกครั้ง" -ForegroundColor Red
    Remove-Item -Path $TempZipPath -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "[ok] แตกไฟล์แล้วที่ $TempExtractPath"

# ---------- ขั้นตอน 3: สร้างโฟลเดอร์ %LOCALAPPDATA%\LocalCodeAssistant ----------
# (install.ps1 ด้านในจะเป็นคนคัดลอกไฟล์จริงเข้าไป — ตรงนี้แค่เตรียมโฟลเดอร์ให้พร้อม
#  เผื่อ install.ps1 บางเวอร์ชันคาดหวังว่าโฟลเดอร์ปลายทางมีอยู่แล้ว)
Write-Host "[3/5] เตรียมโฟลเดอร์ปลายทาง..."
try {
    if (-not (Test-Path $InstallTargetDir)) {
        New-Item -ItemType Directory -Path $InstallTargetDir -Force | Out-Null
        Write-Host "[ok] สร้าง $InstallTargetDir แล้ว"
    } else {
        Write-Host "[info] พบโฟลเดอร์ $InstallTargetDir อยู่แล้ว (จะไม่ลบไฟล์เดิม)"
    }
}
catch {
    Write-Host "[error] สร้างโฟลเดอร์ไม่สำเร็จ: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ---------- ขั้นตอน 4: หาและเรียก install.ps1 ที่แตกออกมา ----------
# หาแบบ recursive กันกรณีโครงสร้างโฟลเดอร์ข้างใน zip เปลี่ยนไประหว่างเวอร์ชัน
# (ไม่ hardcode path ตรงๆ เพื่อความทนทาน)
Write-Host "[4/5] กำลังหาตัวติดตั้งภายใน..."
$innerInstaller = Get-ChildItem -Path $TempExtractPath -Filter "install.ps1" -Recurse -File | Select-Object -First 1

if (-not $innerInstaller) {
    Write-Host "[error] หา install.ps1 ในไฟล์ที่แตกออกมาไม่เจอ" -ForegroundColor Red
    Write-Host "        โครงสร้าง zip อาจเปลี่ยนไป — ไฟล์ที่แตกอยู่ที่: $TempExtractPath" -ForegroundColor Red
    Write-Host "        (ไม่ลบไฟล์ทิ้งให้ ลองเข้าไปติดตั้งด้วยมือแทนได้)" -ForegroundColor Yellow
    exit 1
}
Write-Host "[ok] พบตัวติดตั้งที่: $($innerInstaller.FullName)"

try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $innerInstaller.FullName
}
catch {
    Write-Host "[error] รัน install.ps1 ไม่สำเร็จ: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ---------- ขั้นตอน 5: เก็บกวาดไฟล์ชั่วคราวทิ้ง ----------
Write-Host "[5/5] กำลังลบไฟล์ชั่วคราว..."
Remove-Item -Path $TempZipPath -Force -ErrorAction SilentlyContinue
Remove-Item -Path $TempExtractPath -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "[ok] ลบไฟล์ชั่วคราวใน %TEMP% เรียบร้อย"

Write-Host ""
Write-Host "=== ติดตั้งออนไลน์เสร็จสมบูรณ์ ===" -ForegroundColor Green
