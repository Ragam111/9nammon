# ควบคุมเครื่อง LCA เครื่องที่ 2 ผ่านสาย LAN (OpenSSH)

เครื่อง A = PC เครื่องนี้ (ตัวสั่ง) เครื่อง B = เครื่องที่รัน LCA server
ใช้ของฟรีที่มากับ Windows: OpenSSH (key ed25519 อย่างเดียว ไม่ใช้รหัสผ่าน) + Scheduled Task + git bundle (ไม่ต้องมีเน็ต)

ไฟล์:
- `scripts/node_setup_server.ps1` รันครั้งเดียวบน B (admin)
- `scripts/node_setup_client.ps1` รันบน A
- `scripts/node_ctl.py` ให้ agent ใช้สั่ง B (stdlib อย่างเดียว)

## ส่วนที่ 1: เจ้าของทำเอง (ครั้งเดียว)

### 1. ต่อสายและตั้ง IP
- สายตรง A ↔ B: A = `10.42.0.1/24`, B = `10.42.0.2/24` ไม่ใส่ gateway ไม่ใส่ DNS (Wi-Fi ยังเป็นทางออกเน็ตตามเดิม)
- ข้อควรระวัง: Ethernet ของ A ตอนนี้เป็น 192.168.2.20 (อาจต่อ router อยู่) ถ้าย้ายสายไปต่อ B เส้นนั้นจะหายไป Wi-Fi 192.168.2.44 ยังใช้เน็ตได้
- ถ้าต่อผ่าน switch/router เดียวกันแทนสายตรง: ทำ DHCP reservation ให้ B ที่ router แล้วใช้ IP วง 192.168.2.x แทน 10.42.0.x ทุกที่ (ใส่ `-AllowFrom 192.168.2.0/24`)
- สคริปต์ตั้ง IP ให้ได้ แต่ค่าเริ่มต้นเป็น dry-run (แค่พิมพ์แผน) ต้องใส่ `-ApplyNetwork` ถึงจะแก้จริง

### 2. บนเครื่อง A (PowerShell ปกติ)
```powershell
cd D:\Desktop\9nammon-main
.\scripts\node_setup_client.ps1 -NodeIp 10.42.0.2 -RemoteUser lcaops
# ตั้ง IP สายด้วย (admin shell): .\scripts\node_setup_client.ps1 -Adapter Ethernet -StaticIp 10.42.0.1 -ApplyNetwork
```
- สร้าง `~\.ssh\lca_node_ed25519` (ssh-keygen ถาม passphrase เอง แนะนำให้ตั้ง แล้ว `ssh-add`)
- เขียน `Host lca-node` ใน `~\.ssh\config` (สำรองไฟล์เดิมก่อน)
- พิมพ์ public key ออกมา คัดลอกไปข้อ 3 (public key เท่านั้น ห้ามส่ง private key)

### 3. บนเครื่อง B (PowerShell แบบ Run as Administrator)
แนะนำสร้าง user ธรรมดาที่ไม่ใช่ admin ชื่อ `lcaops` ไว้ให้ agent ใช้ก่อน
```powershell
.\node_setup_server.ps1 -PublicKey "ssh-ed25519 AAAA... lca-agent" -User lcaops `
    -RepoPath C:\lca\repo -DataDir C:\Users\lcaops -WhatIf      # ดูแผนก่อน
.\node_setup_server.ps1 -PublicKey "ssh-ed25519 AAAA... lca-agent" -User lcaops `
    -Adapter Ethernet -StaticIp 10.42.0.2 -ApplyNetwork          # ทำจริง
```
สิ่งที่สคริปต์ทำ (รันซ้ำได้):
- ติดตั้ง/เปิด sshd (Automatic Delayed + restart เองเมื่อล้ม), DefaultShell = Windows PowerShell
- สำรอง `sshd_config` เป็น `.bak-<เวลา>` แล้วตั้ง `PasswordAuthentication no`, `PubkeyAuthentication yes`, `AllowUsers`, `MaxAuthTries 3`, `ListenAddress` (ถ้าใส่ `-StaticIp`) ตรวจด้วย `sshd -t` ถ้าไม่ผ่านคืนไฟล์เดิม
- ใส่ public key พร้อม `from="10.42.0.1",no-port-forwarding,...` (admin ใช้ `administrators_authorized_keys` + ACL)
- firewall: ปิดกฎ `OpenSSH-Server-In-TCP` เดิม เปิด 22 และ 8420 เฉพาะจาก `-AllowFrom` (ค่าเริ่มต้น 10.42.0.0/24) ไม่เปิด 11434 (Ollama)
- สร้าง `C:\lca\{inbox,logs,secrets}` และ `C:\lca\run-server.ps1`
- สร้าง scheduled task `LCA Server` (At startup, S4U ไม่ต้องเก็บรหัสผ่าน, ไม่จำกัดเวลา, restart 3 ครั้ง)

### 4. ใส่ token ด้วยมือบน B
เปิด `notepad C:\lca\secrets\token.txt` วางค่า `LCA_TOKEN` (ค่าเดียวกับเครื่อง A ดู `docs/CREDENTIALS_GUIDE.md`) แล้วบันทึก
wrapper อ่าน token จากไฟล์นี้เอง token จึงไม่อยู่ใน argument ของ task หรือ process list

### 5. เชื่อมครั้งแรก + ทดสอบ (บน A)
```powershell
ssh lca-node hostname     # เทียบ fingerprint กับที่ node_setup_server.ps1 พิมพ์ไว้ ก่อนตอบ yes
python scripts\node_ctl.py deploy
python scripts\node_ctl.py start
python scripts\node_ctl.py status
```
ตรวจบน B: `netstat -ano | findstr :22` ควรเห็นแค่ `10.42.0.2:22`

## ส่วนที่ 2: สิ่งที่ agent ทำได้ (บนเครื่อง A)
```powershell
python scripts\node_ctl.py status                       # ssh ได้ไหม, /api/health, RAM ว่าง, ollama list
python scripts\node_ctl.py deploy                       # git bundle ของ HEAD -> scp -> fetch + checkout --detach (ไม่ใช้เน็ต)
python scripts\node_ctl.py rollback <sha>               # กลับไป commit เดิม (deploy พิมพ์ previous ไว้)
python scripts\node_ctl.py start | stop | restart       # ผ่าน scheduled task (stop ฆ่าเฉพาะ PID ใน C:\lca\server.pid)
python scripts\node_ctl.py logs --lines 200             # log ล่าสุดใน C:\lca\logs
python scripts\node_ctl.py pull-model qwen2.5-coder:0.5b   # อนุญาต: qwen2.5-coder:0.5b, qwen2.5-coder:1.5b, qwen2.5:1.5b
python scripts\node_ctl.py --host lca-node --remote-repo C:/lca/repo status
```
ลำดับ deploy ที่แนะนำ: `deploy` → (ถ้า requirements.txt เปลี่ยน ดูด้านล่าง) → `restart` → `status` ต้องได้ health ok ถ้าไม่ผ่าน `rollback <previous>` แล้ว `restart`

cluster บนเครื่อง A (ต้องส่ง `base_ip` วงสายทุกครั้ง ไม่อย่างนั้นจะสแกนวง Wi-Fi):
```powershell
curl.exe -H "X-Auth-Token: $env:LCA_TOKEN" "http://127.0.0.1:8420/api/nodes/sync?base_ip=10.42.0.1&port=8420"
```

### กติกาความปลอดภัยของ node_ctl.py
- ใช้ `subprocess` แบบ list ไม่ใช้ shell, ทุกค่าที่ใส่ในคำสั่งฝั่ง B ผ่านการตรวจก่อน (host, path ห้ามมี `..`/ช่องว่าง/อักขระพิเศษ, sha 40 hex, โมเดลต้องอยู่ใน allowlist)
- มี timeout ทุกคำสั่ง, error เป็นภาษาไทย, output ผ่าน `redact()` ปิดค่า token ก่อนพิมพ์
- ไม่อ่าน token, `config.json`, `.env` หรือ private key, ไม่ `reset --hard`, ไม่ฆ่า python ทั้งหมด

### ข้อจำกัดที่รู้อยู่
- `pull-model` ต้องให้ B มีเน็ต ถ้าไม่มี: pull บน A แล้ว scp `%USERPROFILE%\.ollama\models\{blobs,manifests}` ที่ต้องการไป B หรือเปิด Wi-Fi ของ B ชั่วคราว ห้ามเปิด ICS บน A
- dependency ไม่มีเน็ต: บน A `pip download -r requirements.txt -d wheels` แล้ว `scp -r wheels lca-node:C:/lca/inbox/` บน B `pip install --no-index --find-links C:\lca\inbox\wheels -r C:\lca\repo\requirements.txt`
- ถ้า user ssh ไม่ใช่ admin และไม่ใช่ principal ของ task อาจ `Start-ScheduledTask` ไม่ได้ ให้ใช้ user เดียวกัน (`-User lcaops`) ตอนรัน setup
- ถ้าพอร์ต 8420 ไม่ว่าง wrapper จะไม่เปิด server และเขียน `port 8420 busy` ลง log
- ส่วนของ Microsoft OpenSSH (ชื่อ capability, ACL ของ administrators_authorized_keys, DefaultShell, S4U) เขียนจากความรู้เดิม ยังไม่ได้ทดสอบบนเครื่องจริง ให้รันด้วย `-WhatIf` ก่อน
- ทางสำรองถ้า ssh ล้ม: เข้าเครื่อง B โดยตรง
