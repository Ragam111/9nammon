@echo off
REM lca-update.bat - update Local Code Assistant in one step (latest GitHub Release, SHA-256 checked)
REM Everything is on one line with "exit /b": update.ps1 may overwrite this file while it runs.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" -InstallDir "%~dp0." -Pause %* & exit /b
