# update.ps1 — อัปเดต Local Code Assistant คำสั่งเดียว
#
#   lca-update                                   (หลังติดตั้งแล้ว — อยู่ใน PATH)
#   powershell -ExecutionPolicy Bypass -c "iex ((irm https://raw.githubusercontent.com/Ragam111/9nammon/main/update.ps1) -replace '^\uFEFF')"
#
# ขั้นตอน: หาโฟลเดอร์ที่ติดตั้ง → โหลด Release ล่าสุด + ตรวจ SHA-256 → ปิด LCA ที่เปิดอยู่
#   → ติดตั้งไฟล์โปรแกรมทับ (install.ps1 -Update: เก็บโมเดล/launcher เดิม)
#   → รัน migration ของฐานข้อมูล (scripts\migrate.py) → เปิด LCA กลับเหมือนเดิม
# ไม่แตะข้อมูลผู้ใช้: <InstallDir>\data (เช่น %LOCALAPPDATA%\LocalCodeAssistant\data),
#   config.json / *.db / stores ในโฟลเดอร์โปรเจกต์ — ไฟล์พวกนี้ไม่อยู่ในแพ็กเกจ จึงไม่ถูกทับ
#   migration ที่แก้ข้อมูลสำรอง .db ไว้ใน backups\ ก่อนเสมอ
#
# พารามิเตอร์:
#   -InstallDir <path>  ตำแหน่งที่ติดตั้ง (ไม่ใส่ = หาเองจาก PATH / %LOCALAPPDATA% / D:\)
#   -Package <path>     ใช้โฟลเดอร์แพ็กเกจที่แตกไว้แล้ว (ออฟไลน์) แทนการโหลด
#   -Force              ติดตั้งทับแม้เวอร์ชันเท่าเดิม
#   -NoRestart          ไม่เปิด LCA กลับหลังอัปเดต
#   -Pause              รอกด Enter ก่อนปิดหน้าต่าง (lca-update.bat ใส่ให้)
param(
    [string]$InstallDir,
    [string]$Package,
    [switch]$Force,
    [switch]$NoRestart,
    [switch]$Pause
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

function Find-LcaInstall {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($PSScriptRoot) { $candidates.Add($PSScriptRoot) }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath) { foreach ($p in $userPath.Split(";")) { if ($p) { $candidates.Add($p) } } }
    if ($env:LOCALAPPDATA) { $candidates.Add((Join-Path $env:LOCALAPPDATA "LocalCodeAssistant")) }
    $candidates.Add("D:\LocalCodeAssistant")
    foreach ($c in $candidates) {
        try {
            if ((Test-Path (Join-Path $c "version.txt")) -and (Test-Path (Join-Path $c "server.py"))) {
                return [IO.Path]::GetFullPath($c).TrimEnd("\")
            }
        } catch {}
    }
    return $null
}

function Get-LcaProcesses($dir) {
    # python/pythonw ที่รัน server.py / lca_app.py จากโฟลเดอร์นี้ + powershell ที่รัน lca-tray.ps1
    $found = @()
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='py.exe' OR Name='powershell.exe' OR Name='pwsh.exe'"
    } catch { return $found }
    foreach ($p in $procs) {
        $cmd = [string]$p.CommandLine
        if (-not $cmd -or $p.ProcessId -eq $PID) { continue }
        if ($cmd.IndexOf($dir, [StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
        $kind = $null
        if ($cmd -match "lca-tray\.ps1") { $kind = "tray" }
        elseif ($cmd -match "lca_app\.py") { $kind = "desktop" }
        elseif ($cmd -match "server\.py") { $kind = "server" }
        if ($kind) { $found += [pscustomobject]@{ Id = $p.ProcessId; Kind = $kind } }
    }
    return $found
}

function Invoke-LcaUpdate {
    if ($InstallDir) { $script:InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd("\") }
    else { $script:InstallDir = Find-LcaInstall }
    if (-not $InstallDir -or -not (Test-Path (Join-Path $InstallDir "server.py"))) {
        throw "ไม่พบการติดตั้ง LCA — ติดตั้งก่อน หรือระบุ -InstallDir <path>"
    }
    Write-Host "=== Local Code Assistant — อัปเดต ===" -ForegroundColor Cyan
    Write-Host "[info] ติดตั้งอยู่ที่: $InstallDir"

    # 1) แพ็กเกจใหม่: โหลด Release ล่าสุดแล้วส่งต่อให้ update.ps1 *ตัวใหม่* ทำงานต่อ
    if (-not $Package) {
        $pkg = Get-LcaReleasePackage
        $args2 = @{ InstallDir = $InstallDir; Package = $pkg }
        if ($Force) { $args2.Force = $true }
        if ($NoRestart) { $args2.NoRestart = $true }
        try { & (Join-Path $pkg "update.ps1") @args2 } finally { Remove-LcaPackage $pkg }
        return
    }
    $Package = [IO.Path]::GetFullPath($Package).TrimEnd("\")
    if (-not (Test-Path (Join-Path $Package "install.ps1"))) { throw "แพ็กเกจไม่ครบ (ไม่มี install.ps1): $Package" }

    $versionFile = Join-Path $InstallDir "version.txt"
    $oldVersion = if (Test-Path $versionFile) { (Get-Content $versionFile -Raw).Trim() } else { "ไม่ทราบ" }
    $newVersion = (Get-Content (Join-Path $Package "VERSION") -Raw).Trim()
    Write-Host "[info] เวอร์ชันเดิม: $oldVersion → ใหม่: $newVersion"
    if ($oldVersion -eq $newVersion -and -not $Force) {
        Write-Host "[ok] เป็นเวอร์ชันล่าสุดแล้ว (ใช้ -Force เพื่อติดตั้งทับ)" -ForegroundColor Green
        return
    }

    $freeMB = $null
    try { $freeMB = [math]::Round((Get-Item $InstallDir).PSDrive.Free / 1MB) } catch {}
    if ($null -ne $freeMB -and $freeMB -lt 100) { throw "ดิสก์เหลือ $freeMB MB — ต้องมีอย่างน้อย 100 MB ก่อนอัปเดต" }

    # 2) ปิด LCA ที่เปิดจากโฟลเดอร์นี้ (จำไว้ว่าเปิดแบบไหน เพื่อเปิดกลับ)
    $running = @(Get-LcaProcesses $InstallDir)
    $kinds = @($running | ForEach-Object { $_.Kind } | Select-Object -Unique)
    foreach ($p in $running) {
        Write-Host "[info] ปิด LCA ($($p.Kind), PID $($p.Id))"
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
    if ($running.Count -gt 0) { Start-Sleep -Seconds 2 }

    # 3) ติดตั้งไฟล์โปรแกรมทับ — install.ps1 ของแพ็กเกจใหม่ในโหมดเงียบ
    & (Join-Path $Package "install.ps1") -Update -InstallDir $InstallDir
    if (-not $?) { throw "install.ps1 -Update ไม่สำเร็จ" }

    # 4) migration ฐานข้อมูล (เฉพาะ .db ที่มีอยู่แล้ว)
    $python = $null
    foreach ($c in @("python", "python3", "py")) { if (Get-Command $c -ErrorAction SilentlyContinue) { $python = $c; break } }
    $migrate = Join-Path (Join-Path $InstallDir "scripts") "migrate.py"
    if ($python -and (Test-Path $migrate)) {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $python $migrate (Join-Path $InstallDir "data") (Join-Path (Join-Path $env:LOCALAPPDATA "LocalCodeAssistant") "data") $env:USERPROFILE 2>&1 | ForEach-Object { Write-Host "$_" }
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        if ($code -ne 0) { Write-Host "[warn] migration มีปัญหา (exit $code) — ข้อมูลเดิมยังอยู่ (มี backup ใน backups\)" -ForegroundColor Yellow }
    }

    # 5) เปิดกลับแบบเดิม
    if (-not $NoRestart -and $kinds.Count -gt 0) {
        if ($kinds -contains "tray") { $launcher = "lca-tray.bat" }
        elseif ($kinds -contains "desktop") { $launcher = "lca-desktop.bat" }
        else { $launcher = "start-lca.bat" }
        $path = Join-Path $InstallDir $launcher
        if (Test-Path $path) {
            Write-Host "[info] เปิด LCA กลับ: $launcher"
            Start-Process -FilePath $path -WorkingDirectory $InstallDir
        }
    }
    Write-Host "[ok] อัปเดตเป็น v$newVersion แล้ว (ข้อมูลผู้ใช้ไม่ถูกแตะ)" -ForegroundColor Green
}

try {
    Invoke-LcaUpdate
} catch {
    Write-Host "[error] $($_.Exception.Message)" -ForegroundColor Red
    if ($Pause) { Read-Host "กด Enter เพื่อปิด" | Out-Null }
    if ($PSScriptRoot) { exit 1 } else { return }
}
if ($Pause) { Read-Host "กด Enter เพื่อปิด" | Out-Null }
