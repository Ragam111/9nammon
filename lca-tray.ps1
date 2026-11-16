# lca-tray.ps1 — LCA Tray App (Windows): วางไอคอนลง system tray ลูกศรบน taskbar
#
# ไอเดีย (ตามที่ user สั่ง): หลังติดตั้งเสร็จ แอปอยู่ใน tray เหมือน Discord/Steam —
#   คลิกไอคอน → เปิดหน้าต่างแอป, คลิกขวา → เมนู (เปิดคอนโซล / ดู logs / ออก).
#   ไม่มีหน้าต่างสีดำค้างแบบ .bat เดิม (เบื้องหลังสะอาด)
#
# ไม่มี deps: ใช้ System.Windows.Forms (built-in .NET บน Windows) + Python ที่ติดตั้งอยู่แล้ว.
# เริ่มโดย lca-tray.bat (ซ่อนหน้าต่าง PowerShell ไปในตัว)
#
# ไม่พูดเกินจริง: นี่ไม่ใช่ native .exe — เป็น PS script ที่ Windows มาพร้อม runtime อยู่แล้ว

$ErrorActionPreference = "Stop"

# โฟลเดอร์โปรเจกต์ (ที่สคริปต์นี้อยู่) — ใช้หา server.py ของ LCA
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant\data"
$LogFile = Join-Path $DataDir "lca-tray.log"
$Port = 8420
$Url = "http://127.0.0.1:$Port/"

# เตรียมโฟลเดอร์ data (เก็บ log + config ส่วนตัวของ user)
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $msg" | Out-File -FilePath $LogFile -Append -Encoding UTF8
}

# ---------- หา Python (อาจ "python" หรือ "py") ----------
function Find-Python {
    foreach ($cmd in @("python", "py")) {
        try {
            $p = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0) { return $cmd }
        } catch { }
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
    [System.Windows.Forms.MessageBox]::Show(
        "ไม่พบ Python บนเครื่อง — ติดตั้ง Python 3.10+ ก่อน (python.org)",
        "LCA Tray", "OK", "Error") | Out-Null
    exit 1
}

$ServerPy = Join-Path $ScriptDir "server.py"
if (-not (Test-Path $ServerPy)) {
    [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
    [System.Windows.Forms.MessageBox]::Show(
        "ไม่พบ server.py ที่: $ServerPy", "LCA Tray", "OK", "Error") | Out-Null
    exit 1
}

Write-Log "LCA tray starting at $ScriptDir (python=$Python)"

# ---------- เริ่มเซิร์ฟเวอร์แบบ hidden ----------
$ServerArgs = @("`"$ServerPy`"", "`"$env:USERPROFILE`"", "--port", "$Port")
$ServerProc = Start-Process -FilePath $Python -ArgumentList $ServerArgs `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $DataDir "lca-server.out.log") `
    -RedirectStandardError  (Join-Path $DataDir "lca-server.err.log")

Write-Log "server process PID=$($ServerProc.Id)"

# ---------- Tray icon (System.Windows.Forms.NotifyIcon) ----------
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ใช้ icon ของระบบ (SystemIcons.Information) — เบา ไม่ต้องแพ็กไฟล์ .ico
$icon = [System.Drawing.SystemIcons]::Information

$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = $icon
$tray.Text = "Local Code Assistant"
$tray.Visible = $true

# สร้างเมนูคลิกขวา
$menu = New-Object System.Windows.Forms.ContextMenuStrip

$openItem = New-Object System.Windows.Forms.ToolStripMenuItem "เปิดแอป"
$openItem.add_Click({
    param($s, $e)
    try {
        $edge = Get-Command msedge -ErrorAction SilentlyContinue
        if ($edge) {
            Start-Process -FilePath "msedge" -ArgumentList "--app=$Url"
        } else {
            Start-Process $Url
        }
        Write-Log "opened app window"
    } catch {
        Write-Log "open app error: $_"
    }
})
$menu.Items.Add($openItem) | Out-Null

$consoleItem = New-Object System.Windows.Forms.ToolStripMenuItem "เปิดคอนโซล"
$consoleItem.add_Click({ Start-Process "$Url`console" })
$menu.Items.Add($consoleItem) | Out-Null

$logsItem = New-Object System.Windows.Forms.ToolStripMenuItem "ดู logs"
$logsItem.add_Click({ Start-Process "notepad.exe" -ArgumentList "`"$LogFile`"" })
$menu.Items.Add($logsItem) | Out-Null

$menu.Items.Add([System.Windows.Forms.ToolStripSeparator]::new()) | Out-Null

$exitItem = New-Object System.Windows.Forms.ToolStripMenuItem "ออก"
$exitItem.add_Click({
    Write-Log "exiting (user requested)"
    try { if ($ServerProc -and -not $ServerProc.HasExited) { $ServerProc.Kill() } } catch {}
    $tray.Visible = $false
    $tray.Dispose()
    [System.Windows.Forms.Application]::Exit()
})
$menu.Items.Add($exitItem) | Out-Null

$tray.ContextMenuStrip = $menu

# คลิกซ้ายไอคอน → เปิดแอป (เหมือน Discord)
$tray.add_Click({
    param($s, $e)
    if ($e.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
        $openItem.PerformClick()
    }
})

# แจ้งว่าแอปพร้อม (balloon tip)
$tray.BalloonTipTitle = "LCA พร้อมใช้งาน"
$tray.BalloonTipText = "คลิกไอคอน LCA ใน tray เพื่อเปิดแอป (พอร์ต $Port)"
$tray.ShowBalloonTip(3000)

Write-Log "tray ready, entering message loop"

# รัน message loop (จำเป็นสำหรับ NotifyIcon)
[System.Windows.Forms.Application]::Run()

# ถ้าหลุดลูป (user กด "ออก") — เก็บกวาด
try { if ($ServerProc -and -not $ServerProc.HasExited) { $ServerProc.Kill() } } catch {}
Write-Log "tray exited cleanly"
