# update.ps1 — อัปเดต Local Code Assistant เป็นเวอร์ชันใหม่
# วิธีใช้: วางไฟล์แพ็กเกจเวอร์ชันใหม่ทับโฟลเดอร์นี้ (windows-package/) แล้วรัน:
#   powershell -ExecutionPolicy Bypass -File update.ps1

$ErrorActionPreference = "Stop"

$InstallDir = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VersionFile = Join-Path $InstallDir "version.txt"
$NewVersion = "0.0.2"   # แก้เลขนี้เวลาปล่อยแพ็กเกจเวอร์ชันใหม่

Write-Host "=== Local Code Assistant — ตัวอัปเดต ===" -ForegroundColor Cyan

if (-not (Test-Path $InstallDir)) {
    Write-Host "[error] ยังไม่เคยติดตั้ง — รัน install.ps1 ก่อน" -ForegroundColor Red
    exit 1
}

$oldVersion = if (Test-Path $VersionFile) { Get-Content $VersionFile -Raw } else { "ไม่ทราบ" }
Write-Host "[info] เวอร์ชันเดิม: $oldVersion"
Write-Host "[info] เวอร์ชันใหม่: $NewVersion"

if ($oldVersion.Trim() -eq $NewVersion) {
    Write-Host "[info] เป็นเวอร์ชันล่าสุดอยู่แล้ว ไม่ต้องอัปเดต"
    exit 0
}

# คัดลอกเฉพาะไฟล์โปรแกรม — ห้ามแตะไฟล์ข้อมูลผู้ใช้ (todos.json, CHANGELOG_local.md,
# .local_coder_backup, default_model.txt ที่ผู้ใช้อาจแก้เอง) ตาม Rule "Idempotency /
# ห้ามทำลายข้อมูลผู้ใช้" ในหลักการเดียวกับ workflow 4 ขั้นตอนที่ backup ก่อนเขียนทับ
Copy-Item -Path (Join-Path $ScriptRoot "local_coder.py") -Destination $InstallDir -Force
Copy-Item -Path (Join-Path $ScriptRoot "server.py") -Destination $InstallDir -Force
$AppDestDir = Join-Path $InstallDir "app"
Copy-Item -Path (Join-Path $ScriptRoot "app\*.py") -Destination $AppDestDir -Force
Copy-Item -Path (Join-Path $ScriptRoot "app\*.html") -Destination $AppDestDir -Force

# folder_trust.py / context_manager.py อยู่ที่ root ของแพ็กเกจ (ไม่ใช่ใน app\)
# แต่ import ผ่าน sys.path ที่ชี้ไปโฟลเดอร์ app\ — ต้องอัปเดตไฟล์นี้ทุกครั้งด้วย
# (นี่คือสาเหตุ ModuleNotFoundError ที่เจอจริงบนเครื่องผู้ใช้ — แก้ที่ install.ps1 ด้วยแล้ว)
Copy-Item -Path (Join-Path $ScriptRoot "folder_trust.py") -Destination $AppDestDir -Force
Copy-Item -Path (Join-Path $ScriptRoot "context_manager.py") -Destination $AppDestDir -Force

Set-Content -Path $VersionFile -Value $NewVersion -Encoding UTF8

Write-Host "[ok] อัปเดตเป็นเวอร์ชัน $NewVersion แล้ว" -ForegroundColor Green
