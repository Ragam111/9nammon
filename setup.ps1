# setup.ps1 — the only supported setup path for this repo on Windows 10/11.
# Creates a repo-local .venv (or reuses a healthy one) and installs
# requirements.txt into that venv. Idempotent. Uses only the venv interpreter.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1

$ErrorActionPreference = "Stop"
# Native-command failures are checked via $LASTEXITCODE below. Do not let
# PowerShell 7 turn a failed probe (for example py -3.13 when 3.13 is absent)
# into a terminating error before the next candidate is tried.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$Root = $PSScriptRoot
if (-not $Root) {
    $Root = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $Root) {
    Write-Host "[error] Could not resolve the repository root." -ForegroundColor Red
    exit 1
}

$Requirements = Join-Path $Root "requirements.txt"
if (-not (Test-Path -LiteralPath $Requirements)) {
    Write-Host "[error] requirements.txt not found at $Requirements" -ForegroundColor Red
    exit 1
}

function Test-PythonRunnable {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [string[]]$Prefix = @()
    )
    $cmd = Get-Command $Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { return $false }
    # The Microsoft Store stub accepts "python" but does not run it.
    if ([string]$cmd.Source -like "*\WindowsApps\*") { return $false }
    try {
        & $Exe @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 1>$null 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$Launcher = $null
$LauncherArgs = @()
if (Test-PythonRunnable -Exe "py" -Prefix @("-3.13")) {
    $Launcher = "py"
    $LauncherArgs = @("-3.13")
} elseif (Test-PythonRunnable -Exe "py" -Prefix @("-3")) {
    $Launcher = "py"
    $LauncherArgs = @("-3")
} elseif (Test-PythonRunnable -Exe "python") {
    $Launcher = "python"
    $LauncherArgs = @()
} elseif (Test-PythonRunnable -Exe "python3") {
    $Launcher = "python3"
    $LauncherArgs = @()
} else {
    Write-Host "[error] Python 3.10+ was not found. Install it from https://www.python.org/downloads/ and select 'Add python.exe to PATH'." -ForegroundColor Red
    exit 1
}

$shown = @($Launcher) + $LauncherArgs
Write-Host "[ok] Using $($shown -join ' ')"

$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

$venvOk = $false
if (Test-Path -LiteralPath $VenvPython) {
    try {
        & $VenvPython -c "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)" 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) { $venvOk = $true }
    } catch {
        $venvOk = $false
    }
}

if (-not $venvOk) {
    if (Test-Path -LiteralPath $VenvDir) {
        Write-Host "[info] Replacing a broken .venv"
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    } else {
        Write-Host "[info] Creating .venv"
    }
    & $Launcher @LauncherArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) {
        Write-Host "[error] Could not create the venv interpreter at $VenvPython" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[info] Reusing existing .venv"
}

# Keep the install inside this venv even if PIP_USER or a pip.ini sets user=true.
# --no-user is the explicit override; do not pass --user.
if (Test-Path Env:PIP_USER) { Remove-Item Env:PIP_USER }
$env:PIP_REQUIRE_VIRTUALENV = "1"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PIP_NO_INPUT = "1"

& $VenvPython -m pip install --disable-pip-version-check --no-input --no-user --require-virtualenv -r $Requirements
if ($LASTEXITCODE -ne 0) {
    Write-Host "[error] Dependency install into .venv failed." -ForegroundColor Red
    exit 1
}

Write-Host "[ok] Dependencies from requirements.txt are installed in $VenvPython" -ForegroundColor Green
exit 0
