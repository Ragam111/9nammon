# install.ps1 — ติดตั้ง Local Code Assistant บน Windows 10/11
#
# คำสั่งเดียว (โหลด Release ล่าสุด + ตรวจ SHA-256 ให้เอง):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Ragam111/9nammon/main/install.ps1 | iex"
# หรือแตก zip แล้วดับเบิลคลิก install.bat (ใช้ไฟล์ในโฟลเดอร์นั้น ไม่โหลดซ้ำ)
#
# พารามิเตอร์ (ไม่ใส่ก็ได้ — จะถาม):
#   -InstallDir <path>   ตำแหน่งติดตั้ง (ข้ามคำถามเลือกไดรฟ์)
#   -Model <ชื่อ>        โมเดล Ollama (ข้ามคำถาม)
#   -Yes                 ไม่ถามอะไรเลย ใช้ค่าแนะนำทั้งหมด
#   -TuneOllama          รัน scripts\setup-ollama.ps1 (จูน Ollama สำหรับเครื่อง RAM 8GB) ไม่ต้องถาม
#   -Update              ใช้โดย update.ps1: ติดตั้งทับแบบเงียบ เก็บโมเดล/การตั้งค่าเดิม
param(
    [string]$InstallDir,
    [string]$Model,
    [switch]$Yes,
    [switch]$TuneOllama,
    [switch]$Update
)

$ErrorActionPreference = "Stop"

# >>> lca-release-download (เหมือนกันทั้ง install.ps1 และ update.ps1 — tests ตรวจว่าตรงกัน)
function Get-LcaReleasePackage {
    # โหลด lca-source.zip + lca-source.zip.sha256 จาก GitHub Release ล่าสุด, ตรวจ SHA-256,
    # แตกไฟล์ไปที่ TEMP แล้วคืน path ของโฟลเดอร์ที่มี server.py. hash ไม่ตรง = ลบทิ้งแล้ว throw
    param([string]$ReleaseUrl)
    if (-not $ReleaseUrl) {
        $ReleaseUrl = if ($env:LCA_RELEASE_URL) { $env:LCA_RELEASE_URL } else { "https://github.com/Ragam111/9nammon/releases/latest/download" }
    }
    $ReleaseUrl = $ReleaseUrl.TrimEnd("/")
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $oldProgress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"   # แถบ progress ของ iwr ทำให้ PowerShell 5.1 โหลดช้ามาก
    try {
        $work = Join-Path ([IO.Path]::GetTempPath()) ("lca-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $work | Out-Null
        $zip = Join-Path $work "lca-source.zip"
        $shaFile = "$zip.sha256"
        Write-Host "[download] $ReleaseUrl/lca-source.zip"
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$ReleaseUrl/lca-source.zip.sha256" -OutFile $shaFile
            Invoke-WebRequest -UseBasicParsing -Uri "$ReleaseUrl/lca-source.zip" -OutFile $zip
        } catch {
            Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
            throw "ดาวน์โหลดไม่สำเร็จ ($($_.Exception.Message)) — เช็กเน็ต หรือดูว่ามี Release ที่ https://github.com/Ragam111/9nammon/releases แล้วหรือยัง"
        }
        $expected = ((Get-Content -Path $shaFile -Raw) -split "\s+" | Where-Object { $_ } | Select-Object -First 1)
        if (-not $expected -or $expected.ToLower() -notmatch "^[0-9a-f]{64}$") {
            Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
            throw "ไฟล์ lca-source.zip.sha256 อ่านไม่ได้ — ไม่ติดตั้งต่อ"
        }
        $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLower()
        if ($actual -ne $expected.ToLower()) {
            Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
            throw "SHA-256 ไม่ตรง (คาดไว้ $expected, ได้ $actual) — ลบไฟล์ทิ้งแล้ว ไม่ติดตั้งต่อ"
        }
        Write-Host "[ok] SHA-256 ตรง: $actual" -ForegroundColor Green
        $dest = Join-Path $work "src"
        Expand-Archive -Path $zip -DestinationPath $dest -Force
        $root = Get-ChildItem -Path $dest -Recurse -Filter "server.py" -File |
            Sort-Object { $_.FullName.Length } | Select-Object -First 1
        if (-not $root) { throw "ไม่พบ server.py ในไฟล์ที่ดาวน์โหลด" }
        return $root.DirectoryName
    } finally {
        $ProgressPreference = $oldProgress
    }
}

function Remove-LcaPackage([string]$Package) {
    # ลบโฟลเดอร์ TEMP\lca-<guid> ที่ Get-LcaReleasePackage สร้าง (ไม่แตะ path อื่น)
    $dir = $Package
    while ($dir) {
        if ((Split-Path -Leaf $dir) -match "^lca-[0-9a-f]{32}$") {
            Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
            return
        }
        $dir = Split-Path -Parent $dir
    }
}
# <<< lca-release-download

# ---------- ถ้ารันแบบ one-liner (irm | iex) หรือไม่มีไฟล์โปรแกรมข้างๆ → โหลด Release ก่อน ----------
$ScriptRoot = $PSScriptRoot
if (-not $ScriptRoot -or -not (Test-Path (Join-Path $ScriptRoot "server.py"))) {
    $pkg = Get-LcaReleasePackage
    $forward = @{}
    foreach ($k in $PSBoundParameters.Keys) { $forward[$k] = $PSBoundParameters[$k] }
    try { & (Join-Path $pkg "install.ps1") @forward } finally { Remove-LcaPackage $pkg }
    return
}

$CurrentVersion = "0.0.0"
$pkgVersionFile = Join-Path $ScriptRoot "VERSION"
if (Test-Path $pkgVersionFile) { $CurrentVersion = (Get-Content $pkgVersionFile -Raw).Trim() }
$interactive = -not ($Yes -or $Update)

Write-Host "=== Local Code Assistant v$CurrentVersion — ตัวติดตั้ง (Windows) ===" -ForegroundColor Cyan
Write-Host ""

# ---------- ขั้นตอน 0: เลือกไดรฟ์ติดตั้ง ----------
if (-not $InstallDir) {
    $driveChoice = ""
    if ($interactive) {
        Write-Host "จะติดตั้งที่ไดรฟ์ไหน?"
        Write-Host "  [1] ค่าเริ่มต้น ($env:LOCALAPPDATA\LocalCodeAssistant)"
        Write-Host "  [2] ไดรฟ์ D: (D:\LocalCodeAssistant)"
        Write-Host "  [3] ระบุ path เอง"
        $driveChoice = Read-Host "เลือก (1/2/3, กด Enter = 1)"
    }
    switch ($driveChoice) {
        "2" {
            if (-not (Test-Path "D:\")) {
                Write-Host "[error] ไม่พบไดรฟ์ D: บนเครื่องนี้ — เลือกตัวเลือกอื่นแทน" -ForegroundColor Red
                exit 1
            }
            $freeSpaceGB = [math]::Round((Get-PSDrive D).Free / 1GB, 1)
            if ($freeSpaceGB -lt 2) {
                Write-Host "[error] ไดรฟ์ D: เหลือพื้นที่แค่ ${freeSpaceGB}GB (ต้องการอย่างน้อย 2GB ไม่รวมโมเดล Ollama) — เลือกตัวเลือกอื่นแทน" -ForegroundColor Red
                exit 1
            }
            $InstallDir = "D:\LocalCodeAssistant"
        }
        "3" {
            $customPath = Read-Host "พิมพ์ path เต็มที่ต้องการติดตั้ง (เช่น E:\Tools\LCA)"
            $customDrive = (Split-Path -Qualifier $customPath -ErrorAction SilentlyContinue)
            if (-not $customDrive -or -not (Test-Path "$customDrive\")) {
                Write-Host "[error] ไม่พบไดรฟ์ที่ระบุ ($customPath) — ยกเลิกการติดตั้ง" -ForegroundColor Red
                exit 1
            }
            $InstallDir = $customPath
        }
        default { $InstallDir = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant" }
    }
}
Write-Host "[ok] ติดตั้งที่ $InstallDir"
$VersionFile = Join-Path $InstallDir "version.txt"
$ModelFile = Join-Path $InstallDir "default_model.txt"

# ---------- ขั้นตอน 1: ตรวจสอบ Python ----------
function Test-Command($name) {
    try { Get-Command $name -ErrorAction Stop | Out-Null; return $true }
    catch { return $false }
}

$pythonCmd = $null
foreach ($candidate in @("python", "python3", "py")) {
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
    Write-Host "[warn] ไม่พบ Ollama — ดาวน์โหลดที่ https://ollama.com/download/windows (หรือใช้โหมด cloud ที่ /console)" -ForegroundColor Yellow
} else {
    Write-Host "[ok] พบ Ollama"
}

# ---------- ขั้นตอน 3: เลือกโมเดลตาม RAM ----------
$totalRamGB = 0
try { $totalRamGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1) } catch {}

function Get-RecommendedModel($ramGB) {
    if ($ramGB -lt 8)  { return @{ Model = "qwen2.5-coder:0.5b"; Tier = "ต่ำกว่า 8GB (ใช้โมเดลเล็กสุด อาจยังหน่วง)" } }
    if ($ramGB -lt 16) { return @{ Model = "qwen2.5-coder:1.5b"; Tier = "8GB" } }
    if ($ramGB -lt 32) { return @{ Model = "qwen2.5-coder:7b";   Tier = "16GB" } }
    if ($ramGB -lt 64) { return @{ Model = "qwen2.5-coder:14b";  Tier = "32GB" } }
    return @{ Model = "qwen2.5-coder:32b"; Tier = "64GB ขึ้นไป" }
}

$rec = Get-RecommendedModel $totalRamGB
if (-not $Model -and (Test-Path $ModelFile)) {
    $Model = (Get-Content $ModelFile -Raw).Trim()   # ติดตั้งทับ/อัปเดต: ใช้โมเดลเดิม
}
if (-not $Model) {
    Write-Host "[ram] RAM ประมาณ $totalRamGB GB (ระดับ: $($rec.Tier)) — แนะนำ $($rec.Model)" -ForegroundColor Green
    if ($interactive) {
        $Model = Read-Host "กด Enter เพื่อใช้โมเดลที่แนะนำ หรือพิมพ์ชื่อโมเดล Ollama อื่น"
    }
    if ([string]::IsNullOrWhiteSpace($Model)) { $Model = $rec.Model }
}
Write-Host "[ok] โมเดล: $Model"

# ---------- ขั้นตอน 4: คัดลอกไฟล์โปรแกรม (ไม่แตะ data\ และไฟล์ผู้ใช้) ----------
# ข้อมูลผู้ใช้อยู่ที่ <InstallDir>\data (LCA Desktop/tray) และโฟลเดอร์โปรเจกต์ — ไม่อยู่ในแพ็กเกจ จึงไม่ถูกทับ
$ProgramDirs  = @("app", "sysmanager", "scripts")
$ProgramFiles = @(
    "server.py", "local_coder.py", "lca_app.py", "requirements.txt", "VERSION", "README.md",
    "lca-tray.bat", "lca-tray.ps1", "lca-update.bat", "install.ps1", "update.ps1", "uninstall.ps1"
)
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir | Out-Null }
foreach ($d in $ProgramDirs) {
    $src = Join-Path $ScriptRoot $d
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $InstallDir $d
    if (-not (Test-Path $dst)) { New-Item -ItemType Directory -Path $dst | Out-Null }
    Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force
}
foreach ($f in $ProgramFiles) {
    $src = Join-Path $ScriptRoot $f
    if (Test-Path $src) { Copy-Item -Path $src -Destination $InstallDir -Force }
}

# dependency (psutil) — best-effort; อ่านผลจาก exit code ไม่ใช่ stderr (pip เขียน warning ลง stderr)
Write-Host "[info] ติดตั้ง dependency จาก requirements.txt ..."
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $pythonCmd -m pip install --user --quiet --disable-pip-version-check -r (Join-Path $InstallDir "requirements.txt") 2>&1 | Out-Null
$pipCode = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($pipCode -eq 0) { Write-Host "[ok] dependency พร้อม" }
else { Write-Host "[warn] pip ไม่สำเร็จ (exit $pipCode) — รันเอง: $pythonCmd -m pip install psutil" -ForegroundColor Yellow }

# คอมไพล์ .pyc ล่วงหน้า — เปิดครั้งแรกบนเครื่อง HDD เร็วขึ้น (ไม่ต้องคอมไพล์ ~200 โมดูลตอนสตาร์ท); best-effort
$ErrorActionPreference = "Continue"
& $pythonCmd -m compileall -q -j 0 (Join-Path $InstallDir "server.py") (Join-Path $InstallDir "lca_app.py") (Join-Path $InstallDir "local_coder.py") (Join-Path $InstallDir "app") (Join-Path $InstallDir "sysmanager") 2>&1 | Out-Null
$ErrorActionPreference = $prevEap

Set-Content -Path $VersionFile -Value $CurrentVersion -Encoding UTF8
Set-Content -Path $ModelFile -Value $Model -Encoding UTF8

# ---------- ขั้นตอน 5: สร้าง launcher (ฝัง python + โมเดลที่เลือก) ----------
Set-Content -Path (Join-Path $InstallDir "lca.bat") -Encoding ASCII -Value @"
@echo off
REM lca.bat - Local Code Assistant CLI (generated by install.ps1)
$pythonCmd "$InstallDir\local_coder.py" --model $Model %*
"@

Set-Content -Path (Join-Path $InstallDir "start-lca.bat") -Encoding UTF8 -Value @"
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

Set-Content -Path (Join-Path $InstallDir "lca-desktop.bat") -Encoding UTF8 -Value @"
@echo off
chcp 65001 >nul
title LCA Desktop
set "URL=http://127.0.0.1:8420/"
start "LCA server" /min cmd /c $pythonCmd "$InstallDir\server.py" "%USERPROFILE%" --port 8420
timeout /t 3 >nul
start "" msedge --app=%URL% 2>nul || start "" chrome --app=%URL% 2>nul || start "" "%URL%"
echo เปิด LCA Desktop แล้ว — ปิดหน้าต่าง "LCA server" เพื่อหยุดใช้งาน
"@

Write-Host "[ok] launcher: lca.bat, start-lca.bat, lca-desktop.bat, lca-tray.bat, lca-update.bat"

# ---------- ขั้นตอน 6: PATH ผู้ใช้ ----------
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentPath;$InstallDir", "User")
    Write-Host "[ok] เพิ่ม $InstallDir เข้า PATH แล้ว — เปิด terminal ใหม่ถึงจะเรียก lca / lca-update ได้"
}

if ($Update) {
    Write-Host "[ok] ติดตั้งไฟล์ v$CurrentVersion ทับแล้ว (ข้อมูลผู้ใช้ไม่ถูกแตะ)" -ForegroundColor Green
    return
}

# ---------- ขั้นตอน 7 (เลือกได้): จูน Ollama สำหรับเครื่องแรมน้อย ----------
$tuneScript = Join-Path (Join-Path $InstallDir "scripts") "setup-ollama.ps1"
if ($hasOllama -and (Test-Path $tuneScript)) {
    $runTune = [bool]$TuneOllama
    if (-not $runTune -and $interactive -and $totalRamGB -gt 0 -and $totalRamGB -le 12) {
        $ans = Read-Host "จูน Ollama สำหรับเครื่อง RAM น้อย (ตั้งค่า + โหลด qwen2.5 1.5b ~2GB)? พิมพ์ y เพื่อทำ (Enter = ข้าม)"
        $runTune = ($ans -eq "y")
    }
    if ($runTune) {
        try { & $tuneScript } catch { Write-Host "[warn] setup-ollama.ps1: $($_.Exception.Message)" -ForegroundColor Yellow }
    }
}

# ---------- สรุป ----------
Write-Host ""
Write-Host "=== ติดตั้งเสร็จสมบูรณ์ (v$CurrentVersion) ===" -ForegroundColor Cyan
if ($hasOllama) { Write-Host "1. ดึงโมเดล: ollama pull $Model" }
else { Write-Host "1. ติดตั้ง Ollama แล้วรัน: ollama pull $Model" }
Write-Host "2. เปิดใช้: ดับเบิลคลิก start-lca.bat ที่ $InstallDir" -ForegroundColor Green
Write-Host "   หรือใน terminal ใหม่: lca C:\path\to\project"
Write-Host "3. อัปเดตครั้งหน้า: lca-update" -ForegroundColor Green
if ($interactive) { try { Start-Process explorer.exe $InstallDir } catch {} }
