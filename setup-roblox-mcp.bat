@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

echo ============================================
echo   Roblox Studio + Claude Code MCP Setup
echo ============================================
echo.

REM --- Check Node.js ---
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found.
    echo Download from: https://nodejs.org/
    echo Install Node.js LTS then re-run this script.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node -v') do echo [OK] Node.js %%v

REM --- Check npm ---
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] npm not found. Reinstall Node.js with npm included.
    pause
    exit /b 1
)

REM --- Install roblox-studio-mcp globally ---
echo.
echo Installing roblox-studio-mcp...
call npm list -g @anthropic-ai/roblox-studio-mcp >nul 2>&1
if %errorlevel% neq 0 (
    call npm install -g @anthropic-ai/roblox-studio-mcp
    if %errorlevel% neq 0 (
        echo.
        echo npm global install failed. Trying npx approach instead...
        goto :setup_npx
    )
    echo [OK] roblox-studio-mcp installed globally.
) else (
    echo [OK] roblox-studio-mcp already installed.
)

REM --- Setup Claude Code MCP config ---
:setup_config
echo.
echo Configuring Claude Code to use Roblox MCP...

set "CLAUDE_DIR=%USERPROFILE%\.claude"
if not exist "%CLAUDE_DIR%" mkdir "%CLAUDE_DIR%"

set "MCP_CONFIG=%CLAUDE_DIR%\mcp_servers.json"

REM Check if config already has roblox entry
if exist "%MCP_CONFIG%" (
    findstr /i "roblox" "%MCP_CONFIG%" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Roblox MCP already configured in %MCP_CONFIG%
        goto :setup_plugin
    )
)

REM Write MCP server config
echo Writing MCP config to %MCP_CONFIG%...
(
echo {
echo   "roblox-studio": {
echo     "command": "npx",
echo     "args": ["-y", "@anthropic-ai/roblox-studio-mcp"]
echo   }
echo }
) > "%MCP_CONFIG%"
echo [OK] MCP config written.

REM --- Install Roblox Studio Plugin ---
:setup_plugin
echo.
echo Checking Roblox Studio plugin...

set "PLUGINS_DIR=%LOCALAPPDATA%\Roblox\Plugins"
if not exist "%PLUGINS_DIR%" (
    mkdir "%PLUGINS_DIR%" 2>nul
    echo Created plugins directory: %PLUGINS_DIR%
)

set "PLUGIN_FILE=%PLUGINS_DIR%\ClaudeMCP.lua"
if exist "%PLUGIN_FILE%" (
    echo [OK] Claude MCP plugin already exists in Roblox Studio.
    goto :done
)

echo Installing Claude MCP plugin for Roblox Studio...
(
echo -- Claude MCP Bridge Plugin for Roblox Studio
echo -- Connects to the local MCP server for Claude Code integration
echo.
echo local HttpService = game:GetService^("HttpService"^)
echo local ServerUrl = "http://localhost:3000"
echo.
echo local toolbar = plugin:CreateToolbar^("Claude Code"^)
echo local button = toolbar:CreateButton^("Connect", "Connect to Claude Code", "rbxassetid://0"^)
echo.
echo local connected = false
echo.
echo local function checkConnection^(^)
echo     local ok, result = pcall^(function^(^)
echo         return HttpService:GetAsync^(ServerUrl .. "/health"^)
echo     end^)
echo     connected = ok
echo     if ok then
echo         button:SetActive^(true^)
echo     else
echo         button:SetActive^(false^)
echo     end
echo     return ok
echo end
echo.
echo local function pollServer^(^)
echo     while true do
echo         if checkConnection^(^) then
echo             local ok, result = pcall^(function^(^)
echo                 return HttpService:GetAsync^(ServerUrl .. "/pending"^)
echo             end^)
echo             if ok and result and result ~= "" then
echo                 local data = HttpService:JSONDecode^(result^)
echo                 if data and data.command then
echo                     local execOk, execResult = pcall^(function^(^)
echo                         return loadstring^(data.command^)^(^)
echo                     end^)
echo                     pcall^(function^(^)
echo                         HttpService:PostAsync^(ServerUrl .. "/result", HttpService:JSONEncode^({
echo                             id = data.id,
echo                             success = execOk,
echo                             result = tostring^(execResult or ""^)
echo                         }^)^)
echo                     end^)
echo                 end
echo             end
echo         end
echo         wait^(1^)
echo     end
echo end
echo.
echo button.Click:Connect^(function^(^)
echo     if checkConnection^(^) then
echo         print^("[Claude MCP] Connected to Claude Code"^)
echo     else
echo         warn^("[Claude MCP] Cannot connect. Make sure Claude Code is running."^)
echo     end
echo end^)
echo.
echo spawn^(pollServer^)
echo print^("[Claude MCP] Plugin loaded. Polling for commands..."^)
) > "%PLUGIN_FILE%"
echo [OK] Plugin installed to %PLUGIN_FILE%

:done
echo.
echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo Next steps:
echo   1. Open Roblox Studio
echo   2. Enable HttpService: Game Settings ^> Security ^> Allow HTTP Requests
echo   3. Open a terminal and run: claude
echo   4. Ask Claude to interact with Roblox Studio!
echo.
echo Examples:
echo   "Create a new Part in Workspace"
echo   "Add a Script to ServerScriptService"
echo   "List all objects in Workspace"
echo.
pause
exit /b 0

:setup_npx
echo.
echo Will use npx to run roblox-studio-mcp on demand.
goto :setup_config
