<#
.SYNOPSIS
  Setup on THIS PC (the controller) so agents can reach the second LCA machine over SSH.

.DESCRIPTION
  - creates ~/.ssh/lca_node_ed25519 if missing (ssh-keygen asks the passphrase itself)
  - optional static IP on the cable adapter: dry-run unless -ApplyNetwork (needs admin)
  - writes / updates a "Host lca-node" block in ~/.ssh/config (backup first)
  - prints the PUBLIC key to pass to node_setup_server.ps1 on the second machine
  Idempotent. Use -WhatIf to preview.

.EXAMPLE
  .\node_setup_client.ps1 -NodeIp 10.42.0.2 -RemoteUser lcaops
  .\node_setup_client.ps1 -Adapter Ethernet -StaticIp 10.42.0.1 -ApplyNetwork   # owner, admin shell
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$NodeIp = '10.42.0.2',
    [string]$RemoteUser = 'lcaops',
    [string]$Adapter = '',
    [string]$StaticIp = '10.42.0.1',
    [int]$PrefixLength = 24,
    [switch]$ApplyNetwork
)

$ErrorActionPreference = 'Stop'
$SshDir = Join-Path $HOME '.ssh'
$KeyPath = Join-Path $SshDir 'lca_node_ed25519'
$ConfigPath = Join-Path $SshDir 'config'

function Write-Plan([string]$Text) { Write-Host "[plan] $Text" -ForegroundColor Cyan }

function Assert-Inputs {
    if ($NodeIp -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw "NodeIp ไม่ถูกต้อง: $NodeIp" }
    if ($RemoteUser -notmatch '^[A-Za-z0-9._-]{1,64}$') { throw "RemoteUser ไม่ถูกต้อง: $RemoteUser" }
}

function New-NodeKey {
    if (Test-Path -LiteralPath $KeyPath) { Write-Host "มี key อยู่แล้ว: $KeyPath"; return }
    Write-Plan "สร้าง key ed25519 ที่ $KeyPath"
    Write-Host 'ssh-keygen จะถาม passphrase เอง แนะนำให้ตั้ง แล้วโหลดเข้า ssh-agent:' -ForegroundColor Yellow
    Write-Host '  Get-Service ssh-agent | Set-Service -StartupType Automatic; Start-Service ssh-agent   (admin)'
    Write-Host "  ssh-add $KeyPath"
    if ($PSCmdlet.ShouldProcess($KeyPath, 'ssh-keygen -t ed25519')) {
        New-Item -ItemType Directory -Force -Path $SshDir | Out-Null
        & ssh-keygen.exe -t ed25519 -f $KeyPath -C 'lca-agent'
        if ($LASTEXITCODE) { throw 'ssh-keygen ล้มเหลว' }
        icacls.exe $KeyPath /inheritance:r /grant "${env:USERNAME}:F" | Out-Null
    }
}

function Set-CableIp {
    if (-not $Adapter) { Write-Host 'ไม่ได้ระบุ -Adapter ข้ามการตั้ง IP (เจ้าของตั้งเองได้ตาม docs/REMOTE_NODE.md)'; return }
    $cur = Get-NetIPAddress -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction SilentlyContinue
    if ($cur | Where-Object { $_.IPAddress -eq $StaticIp }) { Write-Host "$Adapter มี $StaticIp แล้ว"; return }
    Write-Plan "ตั้ง $Adapter = $StaticIp/$PrefixLength ไม่มี gateway ไม่มี DNS (Wi-Fi ยังเป็นทางออกเน็ต)"
    Write-Plan "IP เดิมบน ${Adapter}: $(($cur | ForEach-Object IPAddress) -join ', ') จะหายไป"
    if (-not $ApplyNetwork) { Write-Host 'dry-run: ไม่ได้แก้ IP (เพิ่ม -ApplyNetwork ใน admin shell เพื่อทำจริง)' -ForegroundColor Yellow; return }
    if ($PSCmdlet.ShouldProcess($Adapter, "New-NetIPAddress $StaticIp")) {
        Set-NetIPInterface -InterfaceAlias $Adapter -Dhcp Disabled
        New-NetIPAddress -InterfaceAlias $Adapter -IPAddress $StaticIp -PrefixLength $PrefixLength | Out-Null
        Set-NetIPInterface -InterfaceAlias $Adapter -InterfaceMetric 50
    }
}

function Get-HostBlock {
    $keyFwd = $KeyPath -replace '\\', '/'
    return @('# BEGIN lca-node',
        'Host lca-node',
        "  HostName $NodeIp",
        "  User $RemoteUser",
        "  IdentityFile $keyFwd",
        '  IdentitiesOnly yes',
        '  StrictHostKeyChecking ask',
        '  ServerAliveInterval 15',
        '# END lca-node')
}

function Set-SshConfig {
    $old = if (Test-Path -LiteralPath $ConfigPath) { @(Get-Content -LiteralPath $ConfigPath) } else { @() }
    $kept = New-Object System.Collections.Generic.List[string]
    $skip = $false
    foreach ($l in $old) {
        if ($l -eq '# BEGIN lca-node') { $skip = $true; continue }
        if ($l -eq '# END lca-node') { $skip = $false; continue }
        if (-not $skip) { $kept.Add($l) }
    }
    $new = @(Get-HostBlock) + @($kept)
    if (($old -join "`n") -eq ($new -join "`n")) { Write-Host '~/.ssh/config ตรงแล้ว'; return }
    Write-Plan "เขียน Host lca-node -> $NodeIp ลง $ConfigPath"
    if ($PSCmdlet.ShouldProcess($ConfigPath, 'backup + write Host lca-node')) {
        New-Item -ItemType Directory -Force -Path $SshDir | Out-Null
        if (Test-Path -LiteralPath $ConfigPath) {
            Copy-Item -LiteralPath $ConfigPath -Destination "$ConfigPath.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        }
        Set-Content -LiteralPath $ConfigPath -Value $new -Encoding ascii
    }
}

# ---------- main ----------
Assert-Inputs
New-NodeKey
Set-CableIp
Set-SshConfig

Write-Host ''
if (Test-Path -LiteralPath "$KeyPath.pub") {
    Write-Host 'PUBLIC key (คัดลอกไปใช้กับ node_setup_server.ps1 -PublicKey บนเครื่องที่ 2):' -ForegroundColor Green
    Get-Content -LiteralPath "$KeyPath.pub"
}
Write-Host ''
Write-Host 'ครั้งแรกให้รัน  ssh lca-node hostname  แล้วเทียบ fingerprint กับที่ node_setup_server.ps1 พิมพ์ไว้ ก่อนตอบ yes'
Write-Host 'StrictHostKeyChecking ask จะถามเฉพาะครั้งแรก หลังจากนั้นถ้า key เครื่องที่ 2 เปลี่ยน ssh จะปฏิเสธ'
