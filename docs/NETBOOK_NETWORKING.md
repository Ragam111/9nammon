# Netbook Networking Plan + Claude TODO — เข้าใจฮาร์ดแวร์เครือข่ายจริงก่อนวางแผน

> เครื่อง: HP 14-bs043TX (i3-6006U / 8GB / HDD) + NIC ออนบอร์ด + WiFi การ์ด
> หลัก 9arm: วางแผนจากฮาร์ดแวร์จริงที่วัดได้ ไม่ใช่จากคำว่า "High Performance"

---

## 0. ความจริงข้อเดียวที่เปลี่ยนทั้งแผน

**network ไม่ใช่คอขวดของการ serve LLM บนเครื่องนี้ — CPU ต่างหาก**

| | ตัวเลข |
|---|---|
| gen คำตอบ 200 token | ~12 วินาที (CPU 100%) |
| ขนาดข้อมูลที่ต้องส่งผ่านเน็ต | ~1–5 KB |
| เวลาส่ง 5KB บน WiFi ช้าสุด (72 Mbps) | < 0.001 วินาที |
| เน็ต Gigabit รับ request ได้ | หลายพัน/วินาที |
| CPU ตอบได้จริงพร้อมกัน | **1–2 request** |

→ **คอขวดคือ CPU gen speed** เน็ตเหลือเฟือเสมอ ลงทุนอัปเน็ต = เสียเงินเปล่า
ควรลงทุนที่ **SSD → RAM → CPU/cloud** (ตามคอขวดจริงใน BENCHMARK_RESULTS.md)

**HPC networking แท้ๆ** (InfiniBand/RDMA/100GbE) netbook ไม่มีและใส่ไม่ได้ — และงานนี้ไม่ต้องการ

---

## 1. เข้าใจฮาร์ดแวร์เครือข่ายจริง (พี่รันบนเครื่อง แล้วส่ง output ให้ Claude)

```powershell
# NIC ทั้งหมด + ความเร็ว link จริง
Get-NetAdapter | Format-Table Name,InterfaceDescription,LinkSpeed,Status

# IP ที่ถืออยู่
Get-NetIPAddress -AddressFamily IPv4 | Format-Table InterfaceAlias,IPAddress,PrefixLength

# ถ้าต่อ WiFi: ดู rate/สัญญาณจริง (เลขนี้บอกเพดานจริง ไม่ใช่สเปกกล่อง)
netsh wlan show interfaces
```

ได้ผลแล้วผมจะบอกได้ว่า เครื่องมี NIC/WiFi รุ่นอะไร, LinkSpeed เท่าไร, และยืนยันว่า "เกินพอ"
สำหรับ LCA (ซึ่งจะเป็นอย่างนั้นแทบแน่นอน)

---

## 2. สถาปัตยกรรม networking ของ LCA (ชั้น + ความปลอดภัย)

```
Client ──────────► [ reverse proxy (Caddy :443, HTTPS) ] ──► [ LCA server.py ] ──► [ Ollama :11434 ]
 LAN/WAN              ออก SSL อัตโนมัติ, หน้าด่านเดียว         bind 127.0.0.1 :8420     local เท่านั้น
                                                              + rate limit 300/60s/IP
```

**กฎความปลอดภัยที่โค้ดบังคับอยู่แล้ว (Rule 12):**
- default `bind 127.0.0.1` — เครื่องอื่นเข้าไม่ได้ (ปลอดภัยสุด)
- จะเปิดออกนอก 127.0.0.1 **ต้องใส่ `--token`** ไม่งั้น server ปฏิเสธไม่ยอมสตาร์ท
- เปิดสู่เน็ตจริง → ผ่าน reverse proxy (HTTPS) อย่าเปิดพอร์ต 8420 ตรงๆ

**3 ระดับการเปิด (เลือกตามต้องการ):**
| ระดับ | คำสั่ง | ใครเข้าได้ |
|---|---|---|
| เครื่องเดียว (default) | `python server.py . ` | เฉพาะเครื่องนี้ |
| ทั้ง LAN (บ้าน/ออฟฟิศ) | `python server.py . --host 0.0.0.0 --token SECRET` | อุปกรณ์ใน LAN เดียวกัน (มี token) |
| อินเทอร์เน็ต 24/7 | VPS + Caddy (ดู HOSTING.md) | ทุกที่ (ผ่าน HTTPS) |

---

## 3. Concurrency: ตั้งตามที่ "CPU ไหว" ไม่ใช่ "เน็ตไหว"

- เครื่องนี้ gen ได้จริง **1–2 คนพร้อมกัน** (ข้อ 0) — ThreadingHTTPServer รับ connection เยอะได้
  แต่ทุก request ไปแย่ง CPU 4 เธรดเดียวกัน → คนที่ 3 ขึ้นไปจะช้าลงเป็นเงาตามตัว
- มี **rate limit 300/60s/IP** กันยิงถี่อยู่แล้ว
- ถ้าคนเริ่มเยอะ: ไม่ใช่ปัญหาเน็ต → ย้ายโมเดลไป cloud GPU (HOSTING.md ตัวเลือก C)

---

## 4. Claude TODO — เรียงตามคุ้มค่า

| # | งาน | เจ้าของ | สถานะ |
|---|-----|--------|-------|
| N1 | รัน 3 คำสั่งข้อ 1 ส่ง output ให้ Claude → ยืนยัน NIC/LinkSpeed จริง | 👤 พี่ | ⏳ |
| N2 | ลง Ollama (P2-2) → chat จริงบน CPU | 👤 พี่ | ⏳ |
| N3 | ถ้าจะใช้ใน LAN: สตาร์ทด้วย `--host 0.0.0.0 --token` + เปิด firewall เฉพาะพอร์ต | 👤 พี่ | ⏳ |
| N4 | `/api/health` โชว์ bind host + โหมดเครือข่าย (local/LAN) + auth_required | 🤖 Claude | ✅ เสร็จ |
| N4b | **Auto-scale compute** — chat เลือกโมเดลตาม RAM อัตโนมัติ (ไม่ระบุ/`auto` → `pick_model()`) | 🤖 Claude | ✅ เสร็จ |
| N5 | เปิดสู่อินเทอร์เน็ต 24/7 → VPS + Caddy | 👤 พี่ (decision) | HOSTING.md ตัวเลือก B |
| N6 | ลงเงินที่คอขวดจริง: **SSD → RAM** ไม่ใช่ network | 👤 พี่ (decision) | — |

> N4 เป็นงานโค้ดเล็กๆ ที่ผมทำได้เลยถ้าพี่อยากได้ (โชว์ว่าตอนนี้เปิดโหมดไหน) — ที่เหลือรอเครื่องพี่/decision

---

## 5. ขอบเขต (ตรงๆ)

- ❌ ผม (cloud session) แตะเครื่องพี่ไม่ได้ → ข้อ 1/N1-N3 พี่รันเอง
- ❌ netbook ทำ HPC networking แท้ (InfiniBand/RDMA) ไม่ได้ — และไม่จำเป็น
- ✅ สิ่งที่ทำได้จริงและพอ: Gigabit/WiFi + bind ปลอดภัย + rate limit + reverse proxy (มีครบแล้ว)

*ต่อยอดจาก: HOSTING.md (เปิดสู่อินเทอร์เน็ต), NETBOOK_SOFTWARE_STACK.md (สแตกฝั่งเครื่อง), BENCHMARK_RESULTS.md (คอขวดจริง)*
