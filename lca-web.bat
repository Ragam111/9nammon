@echo off
REM lca-web.bat — เปิดหน้าเว็บ Chat UI ของ Local Code Assistant
REM วิธีใช้: lca-web C:\path\to\project
python "%~dp0server.py" %*
