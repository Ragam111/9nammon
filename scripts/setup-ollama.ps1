<#
README — setup-ollama.ps1 (LCA, i3-6006U / RAM 8GB / HDD, CPU เท่านั้น)
1. ติดตั้ง Ollama for Windows ก่อน: https://ollama.com/download (ไม่ต้องใช้สิทธิ์ admin)
2. รัน: powershell -ExecutionPolicy Bypass -File .\setup-ollama.ps1   (เพิ่ม -SkipModelfile ถ้าไม่อยากสร้างโมเดล lca-*)
3. สคริปต์ตั้งค่าตัวแปรระดับผู้ใช้, รีสตาร์ท Ollama, ดาวน์โหลด qwen2.5:1.5b + qwen2.5-coder:1.5b และสร้าง lca-chat / lca-coder (num_ctx 2048)
4. รันซ้ำได้ (idempotent): ค่าที่ตั้งแล้ว/โมเดลที่มีแล้วจะข้าม
5. คำสั่ง Defender exclusion จะถูก "พิมพ์" ออกมาเท่านั้น ต้องเปิด PowerShell แบบ Administrator แล้วรันเอง
#>
[CmdletBinding()]
param(
    [string]$KeepAlive = "5m",
    [switch]$SkipModelfile
)
$ErrorActionPreference = "Stop"

# --- 1) ตรวจว่ามี ollama ในเครื่อง ---
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "ไม่พบ ollama — ติดตั้งจาก https://ollama.com/download แล้วรันสคริปต์นี้ใหม่" -ForegroundColor Red
    exit 1
}

# --- 2) ตัวแปรสภาพแวดล้อมระดับผู้ใช้ (ไม่ต้อง admin) ---
$envVars = [ordered]@{
    "OLLAMA_NUM_PARALLEL"       = "1"        # ตอบทีละคำขอ ประหยัดแรม
    "OLLAMA_MAX_LOADED_MODELS"  = "1"        # โหลดโมเดลค้างไว้แค่ตัวเดียว
    "OLLAMA_FLASH_ATTENTION"    = "1"        # ลดหน่วยความจำของ attention
    "OLLAMA_KV_CACHE_TYPE"      = "q8_0"     # KV cache แบบ 8-bit (ต้องเปิด flash attention)
    "OLLAMA_KEEP_ALIVE"         = $KeepAlive # ปล่อยแรมคืนเมื่อไม่ใช้ตามเวลานี้
}
$changed = $false
foreach ($k in $envVars.Keys) {
    $cur = [Environment]::GetEnvironmentVariable($k, "User")
    if ($cur -ne $envVars[$k]) {
        [Environment]::SetEnvironmentVariable($k, $envVars[$k], "User")
        Write-Host "ตั้งค่า $k = $($envVars[$k])"
        $changed = $true
    } else {
        Write-Host "ข้าม $k (ตั้งไว้แล้ว)"
    }
    Set-Item -Path "Env:$k" -Value $envVars[$k]   # ให้มีผลใน session นี้ด้วย
}

# --- 3) รีสตาร์ท Ollama ถ้าค่าเปลี่ยน เพื่อให้อ่านค่าใหม่ ---
if ($changed) {
    Write-Host "รีสตาร์ท Ollama เพื่อใช้ค่าใหม่..."
    Get-Process -Name "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    $app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
    if (Test-Path $app) { Start-Process $app } else { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden }
}

# รอให้ API พร้อม (สูงสุด ~60 วินาที เพราะ HDD ช้า)
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 | Out-Null; $ready = $true; break }
    catch { Start-Sleep -Seconds 2 }
}
if (-not $ready) { Write-Host "Ollama ยังไม่ตอบที่ 127.0.0.1:11434 — เปิดแอป Ollama แล้วลองใหม่" -ForegroundColor Red; exit 1 }

# --- 4) ดาวน์โหลดโมเดล (ข้ามถ้ามีแล้ว) ---
$installed = (ollama list) -join "`n"
foreach ($m in @("qwen2.5:1.5b", "qwen2.5-coder:1.5b")) {   # แท็ก 1.5b ค่าเริ่มต้นเป็น Q4_K_M
    if ($installed -match [regex]::Escape($m)) { Write-Host "ข้าม $m (มีแล้ว)" }
    else { Write-Host "ดาวน์โหลด $m ..."; ollama pull $m }
}

# --- 5) Modelfile แบบเบา (เลือกได้) ---
if (-not $SkipModelfile) {
    $dir = Join-Path $env:LOCALAPPDATA "LocalCodeAssistant\modelfiles"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $targets = @{ "lca-chat" = "qwen2.5:1.5b"; "lca-coder" = "qwen2.5-coder:1.5b" }
    foreach ($name in $targets.Keys) {
        $file = Join-Path $dir "$name.Modelfile"
        $body = @(
            "FROM $($targets[$name])",
            "PARAMETER num_ctx 2048",
            "PARAMETER num_predict 512",
            "PARAMETER num_thread 2"
        ) -join "`n"
        $old = if (Test-Path $file) { Get-Content $file -Raw } else { "" }
        $exists = $installed -match "(?m)^$name(:latest)?\s"
        if ($old.Trim() -eq $body.Trim() -and $exists) { Write-Host "ข้าม $name (เหมือนเดิม)"; continue }
        Set-Content -Path $file -Value $body -Encoding UTF8
        ollama create $name -f $file
        Write-Host "สร้าง $name จาก $file"
    }
}

# --- 6) Defender exclusion: พิมพ์อย่างเดียว ไม่รัน (ต้องใช้ admin) ---
$models = Join-Path $env:USERPROFILE ".ollama\models"
Write-Host ""
Write-Host "ทางเลือก: ให้ Defender ไม่สแกนโฟลเดอร์โมเดล (โหลดเร็วขึ้นบน HDD) — เปิด PowerShell แบบ Administrator แล้วรัน:" -ForegroundColor Yellow
Write-Host "  Add-MpPreference -ExclusionPath `"$models`""
Write-Host ""
Write-Host "เสร็จแล้ว ลองใช้: ollama run lca-chat" -ForegroundColor Green
