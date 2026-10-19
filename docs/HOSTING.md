# Hosting / Go-Live — ให้ลูกค้าใช้ LCA จริง (โดยเจ้าของไม่ต้องเปิดเครื่องตลอด)

> สถานะ: **แผน** — ตัดสินใจเรื่องการ deploy; โค้ดฝั่ง app พร้อมอยู่แล้ว (token/HTTPS-ready/rate-limit)
> หลัก 9arm: ตัวเลขจริง ไม่ขายฝัน — รองรับได้เท่าที่ฮาร์ดแวร์ไหว ขยายตามลูกค้าจริง + รายได้จริง

---

## 0. ความจริง 2 ข้อที่ต้องรับก่อน

1. **บริการ 24 ชม. ต้องมีเครื่องเปิด 24 ชม.** — laptop ปิด = ลูกค้าใช้ไม่ได้ทันที
   cloud session (ผู้ช่วยพัฒนา) โฮสต์แทนไม่ได้ → ต้องเช่า **VPS** ที่เปิดตลอด
2. **จำนวนคนที่รับได้ = ฟังก์ชันของฮาร์ดแวร์** ไม่ใช่ของซอฟต์แวร์ — ยัดโค้ดเก่งแค่ไหน
   CPU/GPU ก็ประมวลได้เท่าที่มันมี

---

## 1. รับได้กี่คน? (ตัวเลขจริง — อย่าวางแผนเกินนี้)

สมมติโมเดล 0.5b, คำตอบ ~200 token:

| เครื่อง | ความเร็ว | **คนพร้อมกันจริง** | เหมาะกับ |
|---|---|---|---|
| **laptop i3/8GB (พี่)** | ~17 t/s, 1 คำตอบ ~12 วิ | **1–2 คน** | ทดสอบ / เดโม / เพื่อนกลุ่มเล็ก |
| **VPS 4GB CPU** | ใกล้เคียง (CPU ดีกว่านิด) | **2–5 คน** | ใช้จริงกลุ่มเล็ก 24/7 |
| **1x cloud GPU** (vLLM batching) | เร็วมาก + รับ batch | **หลายสิบคน** | ลูกค้าจริงเริ่มเยอะ |
| **หลาย GPU + load balancer** | scale แนวนอน | **หลักร้อย–พัน** | ระดับบริษัท (ค่าใช้จ่ายสูง) |

> **"1,000 คนพร้อมกัน" = ต้องมี GPU หลายตัว + orchestration = หลักพัน–หมื่นบาท/เดือนขึ้นไป**
> อย่ากระโดดไป 1,000 ทีเดียว — เริ่มเล็ก พิสูจน์ว่ามีลูกค้าจ่ายจริงก่อน แล้วค่อยขยาย (ตามรายได้)

---

## 2. สถาปัตยกรรม: แยกเว็บออกจากโมเดล (decouple)

```
                         (always-on, ถูก)              (หนัก, เลือกที่โฮสต์)
  ลูกค้า ──HTTPS──►  [ LCA web/API (server.py) ]  ──►  [ Model backend ]
                      login/ticket/usage/metrics        Ollama / llama.cpp / cloud GPU
                      rate-limit + token (มีแล้ว)        (สลับได้ผ่าน config)
```

- **เว็บ/API** = stdlib เบามาก → VPS จิ๋วก็รัน 24/7 ได้สบาย
- **โมเดล** = ตัวกินทรัพยากร → แยกออกไป เลือกที่โฮสต์ตามงบ/โหลด
- ข้อดี: ขยายโมเดล (เพิ่ม GPU worker) โดยไม่แตะเว็บ; `resource_budget.pick_backend()` เลือก backend ได้อยู่แล้ว

---

## 3. ตัวเลือก + ต้นทุน (≈ บาท/เดือน)

| | เครื่อง | โมเดล | ค่าใช้จ่าย | ตรงโจทย์ "ไม่ต้องเปิดเครื่องเอง"? |
|---|---|---|---|---|
| **A** | VPS 1GB + tunnel ไปเครื่องพี่ | เครื่องพี่ (ต้องเปิด) | ~150–250 | ❌ ยังต้องเปิดเครื่องตอน AI ตอบ |
| **B** ⭐ | VPS 4–8GB (เว็บ+โมเดลเล็ก) | 0.5b CPU | ~350–900 | ✅ ใช่ (รับ 2–5 คน) |
| **C** | VPS 1GB (เว็บ) + cloud GPU (โมเดล) | จ่ายต่อ use/ชม. | ~150 + ตาม use | ✅ ใช่ เร็วกว่า (รับหลายสิบ) |

**คำแนะนำ:** เริ่ม **B** (คุ้ม + ตรงโจทย์) → ลูกค้าเยอะค่อยขยับ **C** → โตจริงค่อยหลาย GPU

---

## 4. Runbook — deploy LCA ขึ้น VPS (ตัวเลือก B)

> ทำบน VPS Ubuntu 22.04 (เช่น Hetzner CX22 / DigitalOcean / VPS ไทย) — การสมัคร+จ่ายเงิน เจ้าของทำเอง

```bash
# 1) ติดตั้งของจำเป็น
sudo apt update && sudo apt install -y python3 python3-pip git
curl -fsSL https://ollama.com/install.sh | sh          # Ollama (Linux)
ollama pull qwen2.5-coder:0.5b

# 2) ดึงโค้ด LCA
git clone https://github.com/Ragam111/9nammon.git /opt/lca
cd /opt/lca && pip3 install -r requirements.txt

# 3) ตั้ง config (token บังคับเมื่อเปิดสาธารณะ)
mkdir -p /opt/lca-project
# ใส่ DISCORD_WEBHOOK_URL ฯลฯ ใน /opt/lca-project/config.json ตามต้องการ

# 4) รันเป็น service ให้ค้าง 24/7 (systemd)
sudo tee /etc/systemd/system/lca.service >/dev/null <<'UNIT'
[Unit]
Description=LCA server
After=network.target
[Service]
WorkingDirectory=/opt/lca
ExecStart=/usr/bin/python3 /opt/lca/server.py /opt/lca-project --host 127.0.0.1 --port 8420 --token CHANGE_ME_SECRET
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl enable --now lca
```

**เปิดสู่อินเทอร์เน็ตอย่างปลอดภัย (HTTPS + โดเมน):** ใช้ Caddy (ง่ายสุด, ออก SSL อัตโนมัติ)
```bash
sudo apt install -y caddy
# /etc/caddy/Caddyfile:
#   your-domain.com {
#       reverse_proxy 127.0.0.1:8420
#   }
sudo systemctl reload caddy
```
> LCA bind `127.0.0.1` เสมอ แล้วให้ Caddy เป็นหน้าด่าน HTTPS → ไม่เปิด 8420 ตรงสู่เน็ต

---

## 5. Checklist ความปลอดภัยก่อนเปิดจริง (ทำครบก่อน go-live)

- [ ] `--token` ตั้งเป็นความลับจริง (ไม่ใช่ CHANGE_ME) — บังคับเมื่อ host ≠ 127.0.0.1
- [ ] HTTPS ผ่าน Caddy/Cloudflare (อย่าส่ง token ผ่าน http เปล่า)
- [ ] rate limit เปิดอยู่ (มีแล้ว — 300 req/60s ต่อ IP) ปรับตามจริง
- [ ] `config.json` / `*.db` อยู่ใน .gitignore (ความลับไม่ขึ้น git) ✅ มีแล้ว
- [ ] backup `*.db` (ลูกค้า/usage/ticket) เป็นงวด
- [ ] firewall: เปิดแค่ 80/443 (+22 ssh) ปิด 8420

---

## 6. เส้นทางขยาย (เมื่อลูกค้าโตจริง)

1. **คอขวดที่เจอ** → ดูจาก `/api/metrics` + `/api/health` (มีแล้ว) ว่าติด CPU/RAM/คิว
2. **คนเยอะขึ้น** → ย้ายโมเดลไป cloud GPU (ตัวเลือก C) + `pick_backend` ชี้ไป endpoint นั้น
3. **เยอะมาก** → หลาย GPU worker หลัง load balancer; เว็บ/API ขยายแนวนอนได้ (stateless + SQLite→Postgres เมื่อถึงจุด)
4. ตัดสินใจลงเงินจาก **ข้อมูลจริง** (usage metering + metrics) ไม่ใช่เดา — ของพวกนี้เราทำไว้แล้ว

---

## สรุป

- **ให้ลูกค้าใช้โดยไม่ต้องเปิดเครื่องเอง = เช่า VPS (ตัวเลือก B)** — เริ่มเล็ก ~หลักร้อย/เดือน รับ 2–5 คน
- **เครื่อง laptop ของพี่ = ทดสอบ/เดโม 1–2 คนเท่านั้น** ไม่ใช่ 1,000
- ขยายทีละขั้นตามลูกค้าจริง + รายได้จริง — มีเครื่องมือวัด (metrics/usage/health) ครบแล้ว

*ต่อยอดจาก GO_LIVE.md (local/LAN) — ไฟล์นี้ว่าด้วยการ host สาธารณะ 24/7*
