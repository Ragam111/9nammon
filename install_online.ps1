# ============================================================================
# install_online.ps1 — ติดตั้ง Local Code Assistant แบบออนไลน์ (One-Liner)
# ไม่ต้อง Extract Zip เอง — สคริปต์นี้ดาวน์โหลด + แตกไฟล์ + ติดตั้งให้อัตโนมัติ
# ============================================================================
#
# วิธีใช้ (ผู้ใช้ปลายทางแปะบรรทัดเดียวใน PowerShell):
#   powershell -ExecutionPolicy Bypass -Command "iwr -useb https://raw.githubusercontent.com/Ragam111/9nammon/main/install_online.ps1 | iex"
# ============================================================================

$ErrorActionPreference = "Stop"

# ─────────────────────────────────────────────────────────────────────────
# ดาวน์โหลดซอร์สล่าสุดจาก GitHub โดยตรง (codeload zip ของ branch main) —
# repo เป็น public จึงโหลดได้เลยไม่ต้องสร้าง GitHub Release ก่อน. ไฟล์ที่แตกออกมา
# จะอยู่ในโฟลเดอร์ 9nammon-main/ ซึ่งมี install.ps1 อยู่ (ขั้นตอน 4 หาแบบ recursive)
# ─────────────────────────────────────────────────────────────────────────
$DownloadUrl = "https://github.com/Ragam111/9nammon/archive/refs/heads/main.zip"

$TempZipPath = Join-Path $env:TEMP "LocalCodeAssistant-download.zip"
$TempExtractPath = Join-Path $env:TEMP "LocalCodeAssistant-extract"
$InstallTargetDir = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant"

Write-Host "=== Local Code Assistant v0.1.0 — ตัวติดตั้งออนไลน์ ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "** แนะนำ: มี .exe ไฟล์เดียวใน Release แล้ว **" -ForegroundColor Yellow
Write-Host "   https://github.com/Ragam111/9nammon/releases/latest" -ForegroundColor Yellow
Write-Host "   (ดับเบิลคลิก TokenLCAlimit.exe → เสร็จ ไม่ต้องรันสคริปต์)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "สคริปต์นี้จะดาวน์โหลด zip + ติดตั้งแทน (ถ้าไม่โหลด .exe)" -ForegroundColor DarkGray
Write-Host ""

# ---------- Guard: เช็คว่า URL ยังไม่ใช่ placeholder เดิม ----------
if ($DownloadUrl -like "*YOUR_USER/YOUR_REPO*") {
    Write-Host "[error] `$DownloadUrl ยังเป็น placeholder — แก้ให้ชี้ repo จริงก่อน" -ForegroundColor Red
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
Write-Host ""
Write-Host "--- เริ่มใช้งาน ---" -ForegroundColor Cyan
Write-Host "ผู้ใช้ทั่วไป (บนเครื่องตัวเอง): เปิด server แล้วเข้า http://127.0.0.1:8420"
Write-Host "    python server.py . "
Write-Host ""
Write-Host "แอดมิน/เจ้าของ (เข้าด้วยรหัสไททัน = master token):" -ForegroundColor Yellow
Write-Host "    1) ตั้งรหัสไททันตอนเปิด server:"
Write-Host "       `$env:LCA_TOKEN='<รหัสลับยาวๆ>'; python server.py . --host 0.0.0.0 --port 8420"
Write-Host "    2) เปิดหน้า /login แล้ววางรหัสไททันในช่อง token -> ได้สิทธิ์ CEO (แอดมินเต็ม)"
Write-Host "    (โหมด local 127.0.0.1 ไม่ตั้ง token = เป็น CEO อยู่แล้ว ไม่ต้องใส่รหัส)"
