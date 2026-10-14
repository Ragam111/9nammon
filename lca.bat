@echo off
REM lca.bat — เรียกใช้ Local Code Assistant
REM ใช้ --model ระบุโมเดลเอง เช่น: lca --model qwen2.5-coder:1.5b C:\path\to\project
REM ถ้าไม่ระบุ --model จะใช้ค่า default ในตัวสคริปต์ (ดู README.md ว่าโมเดลไหนเหมาะกับ RAM คุณ)
python "%~dp0local_coder.py" %*
