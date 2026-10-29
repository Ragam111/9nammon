# ตัวติดตั้ง GUI ไฟล์เดียว — TokenLCAlimit.exe

> ไอเดีย: ผู้ใช้ได้ไฟล์ **.exe ไฟล์เดียว** → ดับเบิลคลิก → หน้าต่างติดตั้ง (เลือกโฟลเดอร์ +
> จะสร้าง icon บน Desktop ไหม) → กด "ติดตั้ง" → แถบวิ่งขึ้นจน **เขียวเต็มหลอด** → กด **Close**
> พร้อมใช้งาน. ไม่ต้องแตะเทอร์มินัลเลย.

## ซอร์ส
`installer_gui.py` (Python stdlib: tkinter + urllib + zipfile + shutil + threading)
- ดาวน์โหลดซอร์สล่าสุดจาก GitHub (`main.zip`) → แตก → คัดลอก `app/`,`sysmanager/`,`server.py`,
  launcher ต่าง ๆ ลงโฟลเดอร์ที่เลือก
- สร้าง `start-lca.bat` (ดับเบิลคลิกเปิด server + เด้งเบราว์เซอร์)
- ถ้าติ๊ก "icon บน Desktop" → วางทางลัดบน Desktop
- แถบ progress เป็น **สีเขียว** เมื่อ 100% แล้วปุ่ม Close ค่อยกดได้

ทดสอบตรรกะ (ไม่แตะ GUI/เน็ต) แล้วใน `tests/test_installer_gui.py` (mock การดาวน์โหลด)

## วิธีที่แนะนำ: ให้ GitHub build+แปะ Release ให้อัตโนมัติ

มี workflow `.github/workflows/build-exe.yml` ที่ build `.exe` บน **Windows runner** ให้เอง
(ไม่ต้องมีเครื่อง Windows ของตัวเอง):

**ปล่อยเวอร์ชันใหม่ให้คนโหลด** — push tag ขึ้นต้นด้วย `v`:
```bash
git tag v0.1.0
git push origin v0.1.0
```
GitHub จะ: build `TokenLCAlimit.exe` → สร้าง **Release** `v0.1.0` → แปะ `.exe` ไว้ให้
ดาวน์โหลดจากหน้า Releases (พร้อมโน้ตเตือนเรื่องต้องมี Python+Ollama) โดยอัตโนมัติ

**แค่อยากได้ไฟล์มาลองก่อน (ไม่ปล่อย Release)** — ไปแท็บ **Actions → build-exe → Run workflow**
แล้วโหลด `.exe` จาก **Artifacts** ของ run นั้น

## หรือแพ็กเองบน Windows (ถ้าอยากทำมือ)
```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --name TokenLCAlimit installer_gui.py
```
ได้ `dist\TokenLCAlimit.exe` — ไฟล์เดียว แจก/อัปโหลดขึ้น GitHub Releases ได้เลย

> `--onefile` = รวมเป็นไฟล์เดียว · `--windowed` = ไม่เปิดหน้าต่าง console (เป็น GUI ล้วน)

## ข้อควรรู้ (ซื่อตรง)
- ต้องแพ็ก + ทดสอบ .exe **บนเครื่อง Windows** (แซนด์บ็อกซ์ที่สร้างไฟล์นี้เป็น Linux ไม่มี
  tkinter display/นามสกุล .exe) — ตรรกะติดตั้งเทสผ่านแล้ว แต่หน้าต่าง GUI จริงต้องลองบน Windows
- ตัว .exe ยัง **ต้องมี Python + Ollama บนเครื่องปลายทาง** เพื่อรัน LCA (ตัวติดตั้งแค่ติดตั้ง
  ตัวโปรแกรม ไม่ได้ฝัง Python runtime). ถ้าต้องการ .exe ที่รันได้โดยไม่ต้องมี Python แยก
  เป็นงานใหญ่กว่า (ฝัง Python embeddable) — บอกได้ถ้าต้องการ
- Windows SmartScreen อาจเตือน "ไม่รู้จักผู้พัฒนา" ครั้งแรก (เพราะยังไม่ได้ code-sign) —
  กด More info → Run anyway; จะหายเตือนถ้าซื้อ code-signing certificate
