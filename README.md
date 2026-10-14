# Local Code Assistant — Windows Package

ตัวติดตั้ง AI Coding Assistant แบบฟรี รันด้วย Ollama บนเครื่อง (Windows 10/11, AMD64)

## ติดตั้ง

**วิธีง่ายที่สุด**: ดับเบิลคลิก `install.bat`

**หรือถ้าถนัด PowerShell**:
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

สคริปต์จะ:
1. เช็คว่ามี Python และ Ollama ติดตั้งแล้วหรือยัง (ถ้าไม่มีจะบอกลิงก์ให้ไปโหลด)
2. ตรวจ RAM เครื่องอัตโนมัติ แล้วแนะนำโมเดล Ollama ที่เหมาะสม:
   | RAM | โมเดลแนะนำ |
   |---|---|
   | ต่ำกว่า 8GB | `qwen2.5-coder:0.5b` |
   | 8–16GB | `qwen2.5-coder:1.5b` |
   | 16–32GB | `qwen2.5-coder:7b` |
   | 32–64GB | `qwen2.5-coder:14b` |
   | 64GB+ | `qwen2.5-coder:32b` |
3. ติดตั้งไฟล์ไปที่ `%LOCALAPPDATA%\LocalCodeAssistant`
4. สร้างคำสั่ง `lca` ให้เรียกใช้จาก terminal ไหนก็ได้ (เพิ่มเข้า PATH อัตโนมัติ)

**หลังติดตั้ง** ต้องดึงโมเดลด้วยตัวเองอีก 1 ครั้ง (สคริปต์ไม่ pull ให้อัตโนมัติ
เพราะไฟล์โมเดลมีขนาดหลาย GB ควรให้ผู้ใช้กดยืนยันเอง):
```
ollama pull qwen2.5-coder:1.5b
```
(เปลี่ยนชื่อโมเดลตามที่ install.ps1 แนะนำ/ที่คุณเลือกไว้)

## ใช้งาน

เปิด terminal ใหม่ (CMD หรือ PowerShell) แล้ว:
```
lca C:\path\to\your\project
```
หรือเปิดหน้าเว็บ Chat UI:
```
lca-web C:\path\to\your\project
```
แล้วเปิดเบราว์เซอร์ที่ `http://127.0.0.1:8420`

## แนะนำ Terminal setup (ไม่บังคับ)

`lca` ใช้ ANSI escape code ธรรมดาแสดงสี (ดู `Color` class ใน `local_coder.py`)
รันได้ในทุก terminal อยู่แล้ว (CMD, PowerShell, Windows Terminal) — รายการด้านล่าง
เป็นแค่ **ตัวเลือกเสริมสำหรับคนที่อยากได้ประสบการณ์ใช้ terminal ที่ลื่นขึ้น**
ไม่เกี่ยวกับการรัน `lca` ให้ได้ผลลัพธ์ถูกต้อง ไม่ติดตั้งก็ใช้งานได้ปกติ:

| ส่วนประกอบ | ตัวเลือกที่แนะนำ | เหตุผล |
|---|---|---|
| Terminal Emulator | [Alacritty](https://github.com/alacritty/alacritty), [Kitty](https://sw.kovidgoyal.net/kitty/), [Warp](https://www.warp.dev/) | รองรับ True Color เต็มรูปแบบ, render เร็วกว่า CMD เดิม |
| Shell | [Zsh](https://www.zsh.org/) (WSL/macOS/Linux), [Fish](https://fishshell.com/) | มี auto-suggest และจัดการธีมง่ายกว่า `cmd.exe`/PowerShell เปล่าๆ |
| Prompt Framework | [Starship](https://starship.rs/) | โชว์สถานะ Git/Node ในบรรทัดคำสั่งแบบมินิมอล ใช้ได้ทั้ง PowerShell/Zsh/Fish |
| Font | [Nerd Fonts](https://www.nerdfonts.com/) เช่น JetBrainsMono Nerd Font | ต้องมีถ้าจะใช้ไอคอนของ Starship/theme อื่นๆ ไม่งั้นจะเห็นเป็นกล่องเปล่า `▯` |

หมายเหตุ: Alacritty/Kitty/Zsh/Fish/Starship ไม่ใช่ของทีมนี้เขียนเอง เป็นเครื่องมือ
โอเพนซอร์สทั่วไปที่แนะนำแยกต่างหาก — ยังไม่ได้ทดสอบร่วมกับ `lca` จริงบน Windows
(ทดสอบแค่ CMD/PowerShell ธรรมดา ดูหัวข้อ "สถานะที่ยังไม่ทดสอบจริง" ด้านล่าง)

## ถอนการติดตั้ง

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```
ลบเฉพาะไฟล์โปรแกรม ไม่แตะไฟล์โปรเจกต์ของคุณ (todos.json / CHANGELOG_local.md
อยู่แยกในแต่ละโฟลเดอร์โปรเจกต์ที่คุณใช้งาน ไม่ได้อยู่ใน install directory)

## อัปเดต

1. ดาวน์โหลดแพ็กเกจเวอร์ชันใหม่มาทับโฟลเดอร์นี้
2. รัน:
   ```powershell
   powershell -ExecutionPolicy Bypass -File update.ps1
   ```
อัปเดตเฉพาะไฟล์โปรแกรม ไม่ลบไฟล์งานของคุณ

## หมายเหตุด้านความปลอดภัย

- `lca-web` เปิด server ที่ `127.0.0.1` (เฉพาะเครื่องนี้) เป็นค่าเริ่มต้นเท่านั้น
- ถ้าต้องการให้มือถือ/เครื่องอื่นใน Wi-Fi เดียวกันเข้าถึงได้ ต้องรัน
  `server.py --host <IP ของเครื่องนี้ใน LAN> --token <รหัสลับที่ตั้งเอง>` เอง
  (ห้ามเปิดโดยไม่ตั้ง token — ดูรายละเอียดใน `SKILL.md` ของโปรเจกต์หลัก)

## สถานะที่ยังไม่ทดสอบจริง

สคริปต์ PowerShell ชุดนี้เขียนและตรวจ syntax แบบ static แล้ว แต่ **ยังไม่ได้รันจริง
บนเครื่อง Windows** (แซนด์บ็อกซ์ที่สร้างไฟล์นี้เป็น Linux ไม่มี PowerShell ให้ทดสอบ)
ส่วน `local_coder.py`/`server.py` ที่อยู่ในแพ็กเกจนี้ทดสอบแล้วว่ารันได้ถูกต้องบน Linux
กรุณาทดสอบ `install.ps1` บนเครื่อง Windows จริงอีกครั้งก่อนแจกจ่ายให้คนอื่นใช้
