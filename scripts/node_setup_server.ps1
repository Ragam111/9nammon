<#
.SYNOPSIS
  One-time setup of the SECOND machine (the one that runs the LCA server).
  Run by the owner in an elevated PowerShell (Run as Administrator) ON THAT MACHINE.

.DESCRIPTION
  - installs / enables Windows OpenSSH Server (sshd)
  - key-only auth (PasswordAuthentication no), backs up sshd_config first
  - installs ONE public key given as a parameter (never generates keys here)
  - firewall: SSH 22 and LCA 8420 only from -AllowFrom subnet; Ollama 11434 is never opened
  - optional static IP on -Adapter (dry-run unless -ApplyNetwork)
  - scheduled task 'LCA Server' that runs the server detached from any ssh session
  Idempotent: safe to run again. Use -WhatIf to preview every change.

.EXAMPLE
  .\node_setup_server.ps1 -PublicKey (Get-Content .\lca_node_ed25519.pub -Raw) -User lcaops -Adapter Ethernet
  .\node_setup_server.ps1 -PublicKey "ssh-ed25519 AAAA... lca-agent" -Adapter Ethernet -StaticIp 10.42.0.2 -ApplyNetwork
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)] [string]$PublicKey,
    [string]$User = $env:USERNAME,
    [string]$AllowFrom = '10.42.0.0/24',
    [string]$ClientIp = '10.42.0.1',
    [Parameter(Mandatory = $true)] [string]$Adapter,
    [string]$StaticIp = '',
    [int]$PrefixLength = 24,
    [switch]$ApplyNetwork,
    [switch]$AllowDefaultRouteAdapter,
    [string]$RepoPath = 'C:\lca\repo',
    [string]$DataDir = '',
    [string]$PythonExe = 'python',
    [int]$Port = 8420
)

$ErrorActionPreference = 'Stop'
# B8-3: default data dir = profile of -User (the account the task runs as), not the
# admin running this script. Resolve via Win32_UserProfile, fall back to C:\Users\<User>.
function Get-UserProfileDir([string]$Name) {
    try {
        $sid = (New-Object Security.Principal.NTAccount($Name)).Translate([Security.Principal.SecurityIdentifier]).Value
        $p = (Get-CimInstance Win32_UserProfile -Filter "SID='$sid'" -ErrorAction Stop).LocalPath
        if ($p) { return $p }
    } catch { }
    return (Join-Path 'C:\Users' $Name)
}
if (-not $DataDir) { $DataDir = Get-UserProfileDir $User }
$LcaRoot = 'C:\lca'
$SshdConfig = Join-Path $env:ProgramData 'ssh\sshd_config'
$TaskName = 'LCA Server'

function Write-Plan([string]$Text) { Write-Host "[plan] $Text" -ForegroundColor Cyan }

function Assert-Admin {
    $id = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $id.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'ต้องเปิด PowerShell แบบ Run as Administrator'
    }
}

function Assert-PublicKey {
    if ($PublicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]{60,} ?[^\r\n"]*$') {
        throw 'PublicKey ต้องเป็นบรรทัดเดียวขึ้นต้นด้วย ssh-ed25519 (ไฟล์ .pub จากเครื่องนี้ ไม่ใช่ private key)'
    }
    if ($PublicKey -match 'PRIVATE KEY') { throw 'ห้ามใส่ private key' }
}

function Install-Sshd {
    $cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
    if ($cap.State -ne 'Installed' -and $PSCmdlet.ShouldProcess($cap.Name, 'Add-WindowsCapability')) {
        Add-WindowsCapability -Online -Name $cap.Name | Out-Null
    }
    if ($PSCmdlet.ShouldProcess('sshd', 'Set startup Automatic (Delayed), keep STOPPED until config is key-only')) {
        Set-Service -Name sshd -StartupType Automatic
        sc.exe config sshd start= delayed-auto | Out-Null
        sc.exe failure sshd reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null
        # Never let sshd run with default config (PasswordAuthentication yes) while we work.
        Stop-Service sshd -ErrorAction SilentlyContinue
    }
    $shellKey = 'HKLM:\SOFTWARE\OpenSSH'
    if ($PSCmdlet.ShouldProcess($shellKey, 'DefaultShell = Windows PowerShell')) {
        if (-not (Test-Path $shellKey)) { New-Item -Path $shellKey -Force | Out-Null }
        New-ItemProperty -Path $shellKey -Name DefaultShell -PropertyType String -Force `
            -Value "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" | Out-Null
    }
}

function Get-NewSshdConfig([string[]]$Lines, [string]$ListenIp) {
    # Drop our previous block and any auth lines we own, keep everything else.
    $owned = '^\s*#?\s*(PubkeyAuthentication|PasswordAuthentication|KbdInteractiveAuthentication|ChallengeResponseAuthentication|PermitEmptyPasswords|AllowUsers|MaxAuthTries|LoginGraceTime|ListenAddress)\b'
    $out = New-Object System.Collections.Generic.List[string]
    $skip = $false
    foreach ($l in $Lines) {
        if ($l -eq '# BEGIN LCA') { $skip = $true; continue }
        if ($l -eq '# END LCA') { $skip = $false; continue }
        if ($skip -or $l -match $owned) { continue }
        $out.Add($l)
    }
    $block = @('# BEGIN LCA',
        'PubkeyAuthentication yes',
        'PasswordAuthentication no',
        'KbdInteractiveAuthentication no',
        'PermitEmptyPasswords no',
        "AllowUsers $User",
        'MaxAuthTries 3',
        'LoginGraceTime 30')
    if ($ListenIp) { $block += "ListenAddress $ListenIp" }
    $block += '# END LCA'
    # Our block must come before any 'Match' block to apply globally.
    $idx = ($out | Select-String -Pattern '^\s*Match\s' | Select-Object -First 1).LineNumber
    if ($idx -eq 1) { return @($block) + @($out) }
    if ($idx) { return @($out[0..($idx - 2)]) + $block + @($out[($idx - 1)..($out.Count - 1)]) }
    return @($out) + $block
}

function Get-ListenIp {
    if ($StaticIp) { return $StaticIp }
    $ip = Get-NetIPAddress -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1 -ExpandProperty IPAddress
    if ($ip) { return $ip }
    Write-Warning "!!! ไม่พบ IPv4 บน $Adapter และไม่ได้ส่ง -StaticIp: sshd จะฟังทุก interface รวม Wi-Fi เหลือแค่ firewall กั้น !!!"
    return ''
}

function Set-SshdConfig {
    $old = if (Test-Path -LiteralPath $SshdConfig) { Get-Content -LiteralPath $SshdConfig } else { @() }
    $new = Get-NewSshdConfig $old (Get-ListenIp)
    if (($old -join "`n") -eq ($new -join "`n")) { Write-Host 'sshd_config ตรงแล้ว ไม่ต้องแก้'; return }
    $backup = "$SshdConfig.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Write-Plan "สำรอง sshd_config -> $backup แล้วเขียนบล็อก LCA (key-only)"
    if ($PSCmdlet.ShouldProcess($SshdConfig, 'backup + write')) {
        if (Test-Path -LiteralPath $SshdConfig) { Copy-Item -LiteralPath $SshdConfig -Destination $backup }
        Set-Content -LiteralPath $SshdConfig -Value $new -Encoding ascii
        $sshdExe = Join-Path $env:SystemRoot 'System32\OpenSSH\sshd.exe'
        if (Test-Path $sshdExe) { & $sshdExe -t; if ($LASTEXITCODE) { Copy-Item -LiteralPath $backup -Destination $SshdConfig -Force; throw 'sshd_config ใหม่ไม่ผ่าน sshd -t คืนไฟล์เดิมแล้ว' } }
    }
}

function Test-UserIsAdmin([string]$Name) {
    $members = Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction SilentlyContinue
    return [bool]($members | Where-Object { $_.Name -match "\\$([regex]::Escape($Name))$" })
}

function Install-PublicKey {
    $line = "from=`"$ClientIp`",no-port-forwarding,no-agent-forwarding,no-X11-forwarding $($PublicKey.Trim())"
    if (Test-UserIsAdmin $User) {
        $file = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
    } else {
        $file = "C:\Users\$User\.ssh\authorized_keys"
    }
    $existing = if (Test-Path -LiteralPath $file) { Get-Content -LiteralPath $file } else { @() }
    $keyBody = ($PublicKey.Trim() -split ' ')[1]
    $hits = @($existing | Where-Object { $_ -like "*$keyBody*" })
    if ($hits.Count -and -not ($hits | Where-Object { $_ -notlike "from=`"$ClientIp`",*" })) { Write-Host "มี key นี้ใน $file แล้ว (from=$ClientIp)"; return }
    Write-Plan "เขียน public key ลง $file (จำกัด from=$ClientIp แทนที่บรรทัดเดิมของ key นี้ถ้ามี)"
    if ($PSCmdlet.ShouldProcess($file, 'backup + write public key + fix ACL')) {
        New-Item -ItemType Directory -Force -Path (Split-Path $file) | Out-Null
        if ($hits.Count) {
            Copy-Item -LiteralPath $file -Destination "$file.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
            $kept = @($existing | Where-Object { $_ -notlike "*$keyBody*" })
            Set-Content -LiteralPath $file -Value (@($kept) + $line) -Encoding ascii
        } else {
            Add-Content -LiteralPath $file -Value $line -Encoding ascii
        }
        if ($file -like '*administrators_authorized_keys') {
            icacls.exe $file /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
        } else {
            icacls.exe $file /inheritance:r /grant "${User}:F" /grant 'SYSTEM:F' /grant 'Administrators:F' | Out-Null
        }
    }
}

function Set-LcaFirewall {
    Write-Plan "firewall: TCP 22 และ $Port รับเฉพาะ $AllowFrom (ไม่เปิด 11434)"
    if (-not $PSCmdlet.ShouldProcess('Windows Firewall', 'LCA rules')) { return }
    Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue | Disable-NetFirewallRule
    foreach ($n in 'LCA-SSH', 'LCA-HTTP') { Remove-NetFirewallRule -Name $n -ErrorAction SilentlyContinue }
    New-NetFirewallRule -Name 'LCA-SSH' -DisplayName 'LCA SSH (cable)' -Direction Inbound -Protocol TCP -LocalPort 22 -RemoteAddress $AllowFrom -InterfaceAlias $Adapter -Profile Any -Action Allow | Out-Null
    New-NetFirewallRule -Name 'LCA-HTTP' -DisplayName 'LCA server' -Direction Inbound -Protocol TCP -LocalPort $Port -RemoteAddress $AllowFrom -Profile Any -Action Allow | Out-Null
}

function Assert-CableAdapter {
    # Refuse adapters that carry the internet route or are Wi-Fi, so a typo cannot cut the internet.
    $na = Get-NetAdapter -Name $Adapter -ErrorAction SilentlyContinue
    if (-not $na) { throw "ไม่พบ adapter ชื่อ '$Adapter' (ดูชื่อด้วย Get-NetAdapter)" }
    Write-Plan "route เดิมบน ${Adapter}:"
    Get-NetRoute -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Format-Table DestinationPrefix, NextHop, RouteMetric -AutoSize | Out-String | Write-Host
    if ($AllowDefaultRouteAdapter) { Write-Warning "-AllowDefaultRouteAdapter: ข้ามการตรวจ default route/Wi-Fi บน $Adapter"; return }
    if ($na.PhysicalMediaType -match '802\.11' -or "$($na.NdisPhysicalMedium)" -match '^(9|Native802_11)$') {
        throw "$Adapter เป็น Wi-Fi ห้ามตั้ง static IP (ใส่ -AllowDefaultRouteAdapter ถ้าตั้งใจจริง)"
    }
    if (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -InterfaceAlias $Adapter -ErrorAction SilentlyContinue) {
        throw "$Adapter ถือ default route (ทางออกเน็ต) ห้ามแก้ (ใส่ -AllowDefaultRouteAdapter ถ้าตั้งใจจริง)"
    }
}

function Set-CableIp {
    if (-not $StaticIp) { Write-Host 'ไม่ได้ระบุ -StaticIp ข้ามการตั้ง IP'; return }
    $cur = Get-NetIPAddress -InterfaceAlias $Adapter -AddressFamily IPv4 -ErrorAction SilentlyContinue
    if ($cur | Where-Object { $_.IPAddress -eq $StaticIp }) { Write-Host "$Adapter มี $StaticIp แล้ว"; return }
    Write-Plan "ตั้ง $Adapter = $StaticIp/$PrefixLength ไม่มี gateway ไม่มี DNS, InterfaceMetric 50"
    Write-Plan "IP เดิมบน ${Adapter}: $(($cur | ForEach-Object IPAddress) -join ', ')"
    Assert-CableAdapter
    if (-not $ApplyNetwork) { Write-Host 'dry-run: ไม่ได้แก้ IP (เพิ่ม -ApplyNetwork เพื่อทำจริง)' -ForegroundColor Yellow; return }
    if ($PSCmdlet.ShouldProcess($Adapter, "New-NetIPAddress $StaticIp")) {
        Set-NetIPInterface -InterfaceAlias $Adapter -Dhcp Disabled
        New-NetIPAddress -InterfaceAlias $Adapter -IPAddress $StaticIp -PrefixLength $PrefixLength | Out-Null
        Set-NetIPInterface -InterfaceAlias $Adapter -InterfaceMetric 50
    }
}

function Get-RunServerScript {
    # Wrapper: token from file (never in task args), log rotation (keep 7), PID file, port check.
    return @"
`$ErrorActionPreference = 'Stop'
`$root = '$LcaRoot'
`$logDir = Join-Path `$root 'logs'
New-Item -ItemType Directory -Force -Path `$logDir | Out-Null
Get-ChildItem `$logDir -Filter 'server-*' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 14 | Remove-Item -Force
`$log = Join-Path `$logDir ("server-" + (Get-Date -Format yyyyMMdd-HHmmss) + ".log")
`$tokenFile = Join-Path `$root 'secrets\token.txt'
if (-not (Test-Path `$tokenFile)) { "token.txt missing" | Out-File `$log -Append; exit 1 }
`$env:LCA_TOKEN = (Get-Content -LiteralPath `$tokenFile -TotalCount 1).Trim()
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { "port $Port busy" | Out-File `$log -Append; exit 1 }
`$p = Start-Process -FilePath '$PythonExe' -ArgumentList @('server.py', '"$DataDir"', '--host', '0.0.0.0', '--port', '$Port') -WorkingDirectory '$RepoPath' -RedirectStandardOutput `$log -RedirectStandardError (`$log + '.err') -NoNewWindow -PassThru
Set-Content -LiteralPath (Join-Path `$root 'server.pid') -Value `$p.Id
`$p.WaitForExit()
exit `$p.ExitCode
"@
}

function New-LcaDirs {
    if (-not $PSCmdlet.ShouldProcess($LcaRoot, 'create dirs + secrets ACL')) { return }
    foreach ($d in 'inbox', 'logs', 'secrets') { New-Item -ItemType Directory -Force -Path (Join-Path $LcaRoot $d) | Out-Null }
    icacls.exe $LcaRoot /grant "${User}:(OI)(CI)M" | Out-Null
    icacls.exe (Join-Path $LcaRoot 'secrets') /inheritance:r /grant "${User}:(OI)(CI)F" /grant 'SYSTEM:(OI)(CI)F' /grant 'Administrators:(OI)(CI)F' | Out-Null
    Set-Content -LiteralPath (Join-Path $LcaRoot 'run-server.ps1') -Value (Get-RunServerScript) -Encoding utf8
}

function Register-LcaTask {
    Write-Plan "scheduled task '$TaskName' (At startup, ผู้ใช้ $User แบบ S4U ไม่ต้องเก็บรหัส, restart 3 ครั้ง)"
    if (-not $PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) { return }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File $LcaRoot\run-server.ps1"
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType S4U -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
}

# ---------- main ----------
Assert-Admin
Assert-PublicKey
Write-Plan "เครื่องนี้: $env:COMPUTERNAME ผู้ใช้ ssh: $User รับจาก: $AllowFrom"
Set-CableIp
$sshdReady = $false
try {
    # sshd stays stopped until key-only config + firewall are in place.
    Install-Sshd
    Set-SshdConfig
    Install-PublicKey
    Set-LcaFirewall
    if ($PSCmdlet.ShouldProcess('sshd', 'Start-Service (config passed sshd -t)')) { Start-Service sshd }
    $sshdReady = $true
} finally {
    if (-not $sshdReady -and -not $WhatIfPreference) {
        Write-Warning 'setup ล้มเหลวกลางทาง: หยุด sshd เพื่อไม่ให้รับรหัสผ่านค้างอยู่'
        Stop-Service sshd -ErrorAction SilentlyContinue
    }
}
New-LcaDirs
Register-LcaTask

Write-Host ''
Write-Host 'เสร็จ ขั้นต่อไป (ทำด้วยมือ):' -ForegroundColor Green
Write-Host "1. clone/วาง repo ไว้ที่ $RepoPath หรือให้ node_ctl.py deploy สร้างให้"
Write-Host "2. ใส่ LCA_TOKEN ลง $LcaRoot\secrets\token.txt ด้วยมือ (notepad) ห้ามวางในแชต"
Write-Host '3. fingerprint ของเครื่องนี้ (เทียบตอน ssh ครั้งแรก):'
$hostKey = Join-Path $env:ProgramData 'ssh\ssh_host_ed25519_key.pub'
if (Test-Path $hostKey) { & ssh-keygen.exe -lf $hostKey }
Write-Host "4. ตรวจ: netstat -ano | findstr :22  (ควรเห็นแค่ IP สาย ถ้าตั้ง -StaticIp)"
