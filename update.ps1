# update.ps1 — อัปเดต Local Code Assistant เป็นเวอร์ชันใหม่ (เพิ่ม/ทับ "ไฟล์โปรแกรม" เท่านั้น)
#
# หลักการ (ตาม 9arm — ไม่ทำลายข้อมูลผู้ใช้):
#   - อัปเดต = คัดลอกไฟล์โปรแกรมเวอร์ชันใหม่ทับ *เฉพาะโปรแกรม* (ทั้งโฟลเดอร์ app\ รวม
#     app\agent\* ที่เป็นสถาปัตยกรรมใหม่ + sysmanager\ + launcher) — ไม่ใช่ลบแล้วแทนที่ทั้งก้อน
#   - **ไม่แตะข้อมูลผู้ใช้เด็ดขาด**: config.json, *.json store (connections/skills/bots/
#     agent_jobs/agent_approvals/spaces/todos), *.db (usage.db/conn_usage.db/jobs.db ฯลฯ),
#     agent_workspace\, config_versions.json, CHANGELOG_local.md, .local_coder_backup\
#     — ไฟล์พวกนี้สร้างตอนรัน ไม่ได้อยู่ในแพ็กเกจ จึงไม่ถูกทับ (เราแค่ copy ของใหม่ทับของเดิม)
#
# วิธีใช้: วางไฟล์แพ็กเกจเวอร์ชันใหม่ไว้โฟลเดอร์นี้ แล้วรัน:
#   powershell -ExecutionPolicy Bypass -File update.ps1

$ErrorActionPreference = "Stop"

$InstallDir  = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant"
$ScriptRoot  = Split-Path -Parent $MyInvocation.MyCommand.Path
$VersionFile = Join-Path $InstallDir "version.txt"
$NewVersion  = "0.1.0"   # แก้เลขนี้เวลาปล่อยแพ็กเกจเวอร์ชันใหม่

Write-Host "=== Local Code Assistant — ตัวอัปเดต (v$NewVersion) ===" -ForegroundColor Cyan

if (-not (Test-Path $InstallDir)) {
    Write-Host "[error] ยังไม่เคยติดตั้ง — รัน install.ps1 ก่อน" -ForegroundColor Red
    exit 1
}

$oldVersion = if (Test-Path $VersionFile) { (Get-Content $VersionFile -Raw).Trim() } else { "ไม่ทราบ" }
Write-Host "[info] เวอร์ชันเดิม: $oldVersion"
Write-Host "[info] เวอร์ชันใหม่: $NewVersion"

if ($oldVersion -eq $NewVersion) {
    Write-Host "[info] เป็นเวอร์ชันล่าสุดอยู่แล้ว ไม่ต้องอัปเดต"
    exit 0
}

# ---------- เช็กพื้นที่ดิสก์ก่อน (กันก๊อปไม่ครบแล้วไฟล์พังครึ่งทาง เหมือนตอนแตก zip ไม่พอที่) ----------
try {
    $drive  = (Get-Item $InstallDir).PSDrive
    $freeMB = [math]::Round($drive.Free / 1MB)
    if ($freeMB -lt 50) {
        Write-Host "[error] ดิสก์ไดรฟ์ $($drive.Name): เหลือแค่ $freeMB MB — น้อยเกินจะอัปเดตปลอดภัย" -ForegroundColor Red
        Write-Host "        ลบไฟล์ให้ว่างอย่างน้อย ~100 MB ก่อน แล้วรันใหม่ (กันไฟล์โปรแกรมก๊อปไม่ครบ)" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[info] ดิสก์ว่าง: $freeMB MB — พอสำหรับอัปเดต"
} catch {
    Write-Host "[warn] เช็กพื้นที่ดิสก์ไม่ได้ ($($_.Exception.Message)) — ไปต่อแบบระวัง" -ForegroundColor Yellow
}

# ---------- คัดลอกไฟล์โปรแกรม (recursive — ครอบ app\agent\* + sysmanager\ ครบ) ----------
# ไฟล์เดี่ยวที่ root ของแพ็กเกจ (ข้ามอันที่ไม่มีแบบไม่ error)
$rootFiles = @(
    "local_coder.py", "server.py", "requirements.txt",
    "lca.bat", "start-lca.bat", "lca-desktop.bat", "lca-tray.bat", "lca-tray.ps1",
    "install.ps1", "uninstall.ps1"
)
foreach ($f in $rootFiles) {
    $src = Join-Path $ScriptRoot $f
    if (Test-Path $src) { Copy-Item -Path $src -Destination $InstallDir -Force }
}

# โฟลเดอร์ app\ ทั้งต้นไม้ (รวม app\agent\core.py/tools.py/bots-agent, connections.py,
# skills_store.py, conn_usage.py, store_schema.py, console.html ฯลฯ ที่เป็นของใหม่ทั้งหมด)
$AppDestDir = Join-Path $InstallDir "app"
if (-not (Test-Path $AppDestDir)) { New-Item -ItemType Directory -Path $AppDestDir | Out-Null }
Copy-Item -Path (Join-Path $ScriptRoot "app\*") -Destination $AppDestDir -Recurse -Force

# โฟลเดอร์ sysmanager\ (server.py import sysmanager.sysinfo / sysmanager.monitor)
$SysSrc = Join-Path $ScriptRoot "sysmanager"
if (Test-Path $SysSrc) {
    $SysDestDir = Join-Path $InstallDir "sysmanager"
    if (-not (Test-Path $SysDestDir)) { New-Item -ItemType Directory -Path $SysDestDir | Out-Null }
    Copy-Item -Path (Join-Path $SysSrc "*") -Destination $SysDestDir -Recurse -Force
}

Set-Content -Path $VersionFile -Value $NewVersion -Encoding UTF8

Write-Host "[ok] อัปเดตเป็นเวอร์ชัน $NewVersion แล้ว (ข้อมูลผู้ใช้/การตั้งค่าไม่ถูกแตะ)" -ForegroundColor Green
Write-Host "     เปิดใช้งาน: ดับเบิลคลิก start-lca.bat หรือ lca-desktop.bat ที่ $InstallDir" -ForegroundColor Green
