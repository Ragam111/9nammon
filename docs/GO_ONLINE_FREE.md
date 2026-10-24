# เอา LCA ขึ้นออนไลน์ให้ web users ใช้ — จดโดเมน + Cloud Server ฟรี (ทีละขั้น)

> **สิ่งที่ผม (Claude) ทำแทนไม่ได้:** จดโดเมน/สมัคร cloud server จริง — ต้องใช้ email/บัตร
> (ยืนยันตัวตน) ของพี่เอง. เอกสารนี้คือ "ทำตามทีละขั้น" + ไฟล์ deploy เตรียมไว้ให้พร้อมแล้ว.
>
> **ความจริงก่อนเลือก (9arm):** LCA = web/API + ตัว LLM (Ollama). ตัว LLM กิน RAM เยอะ —
> โฮสต์ฟรีจิ๋ว (256–512MB) รันไม่ได้. มี 3 เส้นทาง เลือกตามงบ/ความถาวรที่ต้องการ

---

## เปรียบเทียบ 3 เส้นทาง (เลือก 1)

| เส้นทาง | ค่าใช้จ่าย | โดเมน | รัน LLM ที่ไหน | เหมาะกับ |
|---|---|---|---|---|
| **A. Cloudflare Tunnel จากเครื่องตัวเอง** | ฟรี 100% | ฟรี (subdomain ให้) | เครื่องพี่ | เริ่มไว/ทดสอบ/เครื่องพี่เปิดอยู่แล้ว |
| **B. Oracle Cloud Always Free** | ฟรีถาวร | ต้องหาเอง (ดูล่าง) | บน VM ฟรี (24GB RAM) | ออนไลน์ 24 ชม. จริงจัง |
| **C. โฮสต์ฟรี (Render) + cloud LLM** | ฟรี/จ่ายตาม LLM | subdomain ให้ | cloud API ภายนอก | ไม่อยากดูแล server |

---

## เส้นทาง A — Cloudflare Tunnel (ฟรีสุด เริ่มได้ใน 5 นาที ไม่ต้องจดโดเมน)

เครื่องพี่ที่มี Ollama อยู่แล้ว → เปิดเป็น public URL ฟรี ไม่ต้องมี server/โดเมน/บัตร

```powershell
# 1) รัน LCA (ตั้ง token เสมอเมื่อเปิดออกนอกเครื่อง — บังคับด้านความปลอดภัย)
$env:LCA_HOST = "0.0.0.0"
$env:LCA_TOKEN = "ตั้งรหัสลับยาว ๆ"
python server.py . --port 8420

# 2) อีกหน้าต่าง: โหลด cloudflared (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
cloudflared tunnel --url http://localhost:8420
```
ได้ URL `https://xxxx.trycloudflare.com` ทันที — ส่งให้ web users เปิดได้เลย
**ข้อจำกัด:** URL สุ่มเปลี่ยนทุกครั้ง + เครื่องพี่ต้องเปิดค้าง. อยากได้โดเมนคงที่ → ทำข้อ "ผูกโดเมน" ล่าง

---

## เส้นทาง B — Oracle Cloud Always Free (ออนไลน์ 24 ชม. ฟรีถาวร รัน Ollama ได้จริง)

Oracle แจก VM ฟรีถาวร **ARM Ampere 4-core / 24GB RAM** (แรงกว่าฟรีเจ้าอื่นมาก รัน LLM เองได้)

### B1. สมัคร + สร้าง VM
1. สมัคร https://www.oracle.com/cloud/free/ (ใช้บัตรยืนยันตัวตน **ไม่ตัดเงิน** ในโควตาฟรี)
2. Console → **Compute → Instances → Create Instance**
3. Image: **Ubuntu 22.04**; Shape: **VM.Standard.A1.Flex** (เลือก 4 OCPU / 24GB — อยู่ในโควตา Always Free)
4. ตั้ง **SSH key** (เก็บ private key ไว้ดี) → Create
5. จด **Public IP** ที่ได้

### B2. เปิด port (ให้คนนอกเข้าถึงได้)
- VM's **Subnet → Security List → Add Ingress Rule**: Source `0.0.0.0/0`, TCP port `8420` (หรือ 443 ถ้าทำ HTTPS)
- บน VM เองก็เปิด firewall: `sudo iptables -I INPUT -p tcp --dport 8420 -j ACCEPT`

### B3. ติดตั้ง LCA + Ollama บน VM
```bash
ssh ubuntu@<PUBLIC_IP>
# ติดตั้งของจำเป็น
sudo apt update && sudo apt install -y python3 python3-pip git
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:1.5b        # เลือกตามที่ 24GB ไหว (ลองตัวใหญ่ขึ้นได้)

# ดึง LCA จาก GitHub (repo นี้)
git clone https://github.com/Ragam111/9nammon.git && cd 9nammon
pip3 install psutil

# รัน (ตั้ง token เสมอ — Rule 12 บังคับเมื่อ bind ออกนอก 127.0.0.1)
export LCA_HOST=0.0.0.0
export LCA_TOKEN="ตั้งรหัสลับยาว ๆ"
python3 server.py . --port 8420
```
เปิด `http://<PUBLIC_IP>:8420` จากที่ไหนก็ได้ → ใช้งานได้ 24 ชม.

> รันค้างแม้ปิด SSH: ใช้ `tmux` หรือทำเป็น systemd service (บอกผมถ้าอยากได้ไฟล์ service)

---

## เส้นทาง C — Render (ฟรี) + cloud LLM

Render build จาก `Dockerfile` ในรีโปให้เอง. เครื่องฟรี RAM น้อย → **ไม่รัน Ollama เอง** แต่ชี้ LLM ไป cloud
ตั้ง env บน Render: `LCA_HOST=0.0.0.0`, `LCA_TOKEN=<secret>`, `MODEL_BACKEND=openai`,
`OPENAI_BASE_URL=https://<cloud-llm>/v1`, `OPENAI_API_KEY=<key>` (ดู `docs/DEPLOY.md`)

---

## จดโดเมน (อยากได้ชื่อคงที่ เช่น lca.example.com)

**ความจริง:** โดเมนฟรีจริง ๆ (.tk/.ml เดิม) ตอนนี้เลิก/ไม่เสถียรแล้ว. ทางที่เวิร์ก:

| ตัวเลือก | ราคา | ได้อะไร |
|---|---|---|
| **DuckDNS** (https://www.duckdns.org) | ฟรี | subdomain `ชื่อคุณ.duckdns.org` ชี้ไป IP ได้ (เหมาะกับเส้นทาง B) |
| **Cloudflare + โดเมนจริง** | ~$1–12/ปี (.xyz/.com) | โดเมนคงที่ + HTTPS ฟรี + ผูก Tunnel ได้ |

### ผูกโดเมนคงที่กับ Cloudflare Tunnel (เส้นทาง A แบบ URL ไม่เปลี่ยน)
1. จดโดเมน(เช่น Cloudflare Registrar / Namecheap) แล้วเพิ่มเข้า Cloudflare (ฟรี)
2. `cloudflared tunnel login` → `cloudflared tunnel create lca`
3. `cloudflared tunnel route dns lca lca.yourdomain.com`
4. รัน: `cloudflared tunnel run --url http://localhost:8420 lca`
→ ได้ `https://lca.yourdomain.com` คงที่ + HTTPS ฟรี

### ชี้ DuckDNS ไป Oracle VM (เส้นทาง B)
- DuckDNS → ตั้งค่า subdomain ให้ชี้ **Public IP** ของ VM → เข้าผ่าน `http://ชื่อคุณ.duckdns.org:8420`
- อยาก HTTPS: ลง Caddy บน VM (`caddy reverse-proxy --to :8420 --from ชื่อคุณ.duckdns.org`) ได้ cert ฟรีอัตโนมัติ

---

## สรุปแนะนำ (9arm-honest)
- **เริ่มวันนี้ ไม่เสียเงิน ไม่ต้องจดอะไร** → เส้นทาง A (Cloudflare Tunnel) ได้ URL ใช้งานทันที
- **จริงจัง ออนไลน์ 24 ชม. ฟรีถาวร** → เส้นทาง B (Oracle Always Free) + DuckDNS/โดเมนถูก ๆ
- **โดเมนสวยคงที่** → ซื้อโดเมน ~$1–12/ปี + Cloudflare (ไม่มีฟรีที่เสถียรกว่านี้แล้วจริง ๆ)

> ตั้ง `LCA_TOKEN` ทุกครั้งที่เปิดออกนอกเครื่อง (server ปฏิเสธถ้าไม่ตั้ง) + สร้าง CEO ด้วย "รหัสไททัน"
> แล้วให้ลูกน้อง login — ดู RBAC ใน README/SKILL ของโปรเจกต์
