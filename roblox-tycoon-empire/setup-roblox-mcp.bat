@echo off
echo ==========================================
echo   Roblox Studio x Claude Code - Auto Setup
echo ==========================================
echo.

:: Check if Claude Code settings directory exists
if not exist "%USERPROFILE%\.claude" (
    mkdir "%USERPROFILE%\.claude"
    echo [OK] Created .claude folder
)

:: Check if Roblox MCP exists
if not exist "%LOCALAPPDATA%\Roblox\mcp.bat" (
    echo [!] Roblox Studio MCP not found at %LOCALAPPDATA%\Roblox\mcp.bat
    echo.
    echo Please update Roblox Studio to the latest version first.
    echo Open Roblox Studio ^> File ^> Check for Updates
    echo.
    echo After updating, run this script again.
    pause
    exit /b 1
)

echo [OK] Found Roblox MCP at %LOCALAPPDATA%\Roblox\mcp.bat

:: Create or update settings.json
set SETTINGS_FILE=%USERPROFILE%\.claude\settings.json

:: Check if settings.json exists
if exist "%SETTINGS_FILE%" (
    echo [i] settings.json already exists - backing up to settings.json.bak
    copy "%SETTINGS_FILE%" "%SETTINGS_FILE%.bak" >nul
)

:: Write the MCP config
echo Writing Claude Code settings with Roblox MCP...

(
echo {
echo   "mcpServers": {
echo     "Roblox_Studio": {
echo       "command": "cmd.exe",
echo       "args": ["/c", "cd /d %%LOCALAPPDATA%%\\Roblox ^&^& .\\mcp.bat"]
echo     }
echo   }
echo }
) > "%SETTINGS_FILE%"

echo [OK] Settings written to %SETTINGS_FILE%
echo.
echo ==========================================
echo   Setup Complete!
echo ==========================================
echo.
echo Next steps:
echo   1. Open Roblox Studio
echo   2. Open a terminal and run: claude
echo   3. Claude Code can now control Roblox Studio directly!
echo.
echo Try saying: "Open TycoonEmpire.rbxlx and add more plots"
echo.
pause
