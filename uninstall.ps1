# uninstall.ps1 — ถอนการติดตั้ง Local Code Assistant
# รันด้วย: powershell -ExecutionPolicy Bypass -File uninstall.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== Local Code Assistant — ถอนการติดตั้ง ===" -ForegroundColor Cyan

# ตอนนี้ install.ps1 เลือกไดรฟ์ติดตั้งได้ (default/D:/custom) จึงต้องถามตำแหน่ง
# แทนการ hardcode %LOCALAPPDATA% เหมือนเดิม — เดาค่า default ให้ก่อนเพื่อความสะดวก
$defaultGuess = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant"
$dGuess = "D:\LocalCodeAssistant"
$guess = if (Test-Path $defaultGuess) { $defaultGuess } elseif (Test-Path $dGuess) { $dGuess } else { "" }

if ($guess) {
    Write-Host "พบการติดตั้งที่: $guess"
    $confirmPath = Read-Host "กด Enter เพื่อใช้ path นี้ หรือพิมพ์ path อื่น"
    $InstallDir = if ([string]::IsNullOrWhiteSpace($confirmPath)) { $guess } else { $confirmPath }
} else {
    $InstallDir = Read-Host "ไม่พบการติดตั้งที่ตำแหน่งปกติ — พิมพ์ path ที่ติดตั้งไว้ (เช่น D:\LocalCodeAssistant)"
}

if (-not (Test-Path $InstallDir)) {
    Write-Host "[info] ไม่พบการติดตั้งที่ $InstallDir — ไม่มีอะไรให้ถอน"
    exit 0
}

Write-Host "[คำเตือน] จะลบโฟลเดอร์ $InstallDir ทั้งหมด" -ForegroundColor Yellow
Write-Host "          รวมถึงไฟล์โปรแกรม (local_coder.py, server.py) แต่ไม่แตะไฟล์โปรเจกต์ของคุณ"
Write-Host "          (todos.json / CHANGELOG_local.md ที่อยู่ในโฟลเดอร์โปรเจกต์แยกต่างหากจะไม่ถูกลบ)"
$confirm = Read-Host "พิมพ์ yes เพื่อยืนยันการถอนการติดตั้ง"

if ($confirm -ne "yes") {
    Write-Host "[ยกเลิก] ไม่ได้ถอนการติดตั้ง"
    exit 0
}

$scriptSelf = $MyInvocation.MyCommand.Path
$scriptIsInsideInstallDir = $scriptSelf -and $scriptSelf.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)

if ($scriptIsInsideInstallDir) {
    # ปัญหา: ถ้า uninstall.ps1 อยู่ใน $InstallDir เอง Windows จะล็อกไฟล์นี้ไว้ระหว่าง
    # กำลังรัน ทำให้ Remove-Item ลบตัวเองไม่ได้ (error "file in use") — แก้โดยคัดลอก
    # logic ไปรันจาก %TEMP% แทน แล้วให้ตัว process ใหม่นั้นลบ $InstallDir ทีหลัง
    Write-Host "[info] ย้ายตัวเองไปรันที่ %TEMP% ก่อนลบ (กันปัญหาไฟล์ถูกล็อก)..."
    $tempRunner = Join-Path $env:TEMP "lca_uninstall_runner.ps1"
    $runnerScript = @"
Start-Sleep -Milliseconds 800
Remove-Item -Path '$InstallDir' -Recurse -Force -ErrorAction SilentlyContinue
`$currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (`$currentPath -like "*$InstallDir*") {
    `$newPath = (`$currentPath -split ';' | Where-Object { `$_ -ne '$InstallDir' }) -join ';'
    [Environment]::SetEnvironmentVariable('Path', `$newPath, 'User')
}
Write-Host '[ok] ลบโฟลเดอร์ติดตั้งแล้ว และเอาออกจาก PATH แล้ว' -ForegroundColor Green
"@
    Set-Content -Path $tempRunner -Value $runnerScript -Encoding UTF8
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$tempRunner`"" -WindowStyle Normal
    Write-Host "[ok] เริ่มถอนการติดตั้งในหน้าต่างใหม่แล้ว (หน้าต่างนี้ปิดได้เลย)"
    exit 0
}

Remove-Item -Path $InstallDir -Recurse -Force
Write-Host "[ok] ลบโฟลเดอร์ติดตั้งแล้ว"

$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -like "*$InstallDir*") {
    $newPath = ($currentPath -split ";" | Where-Object { $_ -ne $InstallDir }) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "[ok] เอาออกจาก PATH แล้ว"
}

Write-Host "=== ถอนการติดตั้งเสร็จสมบูรณ์ ===" -ForegroundColor Cyan
