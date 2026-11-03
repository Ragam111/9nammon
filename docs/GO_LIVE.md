# LCA — เปิดให้คนใช้จริง (Go Live)

เอกสารนี้บอกวิธี "เปิดเซิร์ฟเวอร์ให้คนเข้ามาใช้" อย่างปลอดภัย — ไล่จากเบาไปหนัก
**ต้องรันบนเครื่อง Nammon เอง** (ที่มี Ollama + โมเดล) — cloud session ของ Claude ทำแทนไม่ได้

เปิดด้วยคำสั่งเดียว: `./scripts/serve.sh` (ดู `--help`)

---

## เตรียมก่อนทุกครั้ง
```bash
ollama serve &                      # เปิด model service
ollama pull qwen2.5-coder:1.5b      # โหลดโมเดล (เครื่อง 8GB เอาตัวเล็กก่อน)
```
เครื่องเป้าหมาย 8GB: ไหวโมเดล ~0.5b–3b (quantized) และผู้ใช้พร้อมกันได้ไม่กี่คน — ดู `/dev`
(มิเตอร์ทรัพยากรสด) ถ้า RAM แตะ 90% = รับไม่ไหว ให้ลดขนาดโมเดลหรือจำกัดจำนวนคน

## ระดับ 1 — เฉพาะเครื่องตัวเอง (ลองใช้/เดโม)
```bash
./scripts/serve.sh
```
เปิด `http://127.0.0.1:8420` ได้จากเบราว์เซอร์บนเครื่องนี้. เซิร์ฟเวอร์สุ่ม **session token** ใหม่ทุกครั้งที่เปิด
แล้วฝังให้หน้าเว็บเอง (เทอร์มินัลพิมพ์ค่าเดียวกันสำหรับ `curl` / header `X-Auth-Token`).
ไม่ได้ตั้ง token แล้วไม่ได้สิทธิ์ CEO อีกต่อไป — กันเว็บอื่นยิงเข้า `127.0.0.1`.

### คำขอที่เซิร์ฟเวอร์ปฏิเสธ (2026-11-03)
- **Host** ต้องเป็น `127.0.0.1:<พอร์ต>`, `localhost:<พอร์ต>` หรือ `[::1]:<พอร์ต>`
  (ถ้า bind ออกนอก loopback ให้อนุญาตชื่อนั้นเพิ่ม — bind `0.0.0.0` รับชื่อจริงของเครื่องบนพอร์ตที่ฟัง เพราะบังคับ token อยู่แล้ว)
- **Origin** บน POST/PUT/PATCH/DELETE และ websocket upgrade ต้อง same-origin. ไม่มี Origin ได้เฉพาะไคลเอนต์ที่ไม่ใช่เบราว์เซอร์ (curl/CLI) และต้องมี token. ไม่เปิด CORS
- `GET /api/version` และ `GET /api/health` ยังเป็น public (ไม่มี token, path, หรือข้อมูลผู้ใช้). ฟิลด์ `python` คงไว้สำหรับ support

Tunnel เข้า loopback (`cloudflared --url http://localhost:8420`) จะโดน Host/Origin ปฏิเสธ
เพราะเบราว์เซอร์ส่งชื่อสาธารณะ ไม่ใช่ loopback. ต้องมีรายชื่อ host ที่อนุญาตเพิ่มภายหลังถ้าจะเปิดทางนี้.

## ระดับ 2 — เปิดให้คนในบ้าน/ออฟฟิศ (วง Wi-Fi/LAN เดียวกัน)
```bash
./scripts/serve.sh --lan            # สุ่ม token ให้ หรือใส่ --token เอง
```
- สคริปต์จะโชว์ IP ในวง (เช่น `http://192.168.1.x:8420`) ให้คนอื่นเปิด
- **ต้อง bootstrap + ออกคีย์ก่อน** (ดูด้านล่าง) เพราะทุก API ต้องมี token/key
- rate limit (300 req/60s ต่อ IP) + RBAC ทำงานอยู่แล้ว

## ระดับ 3 — เปิดให้คน "นอกวง" (อินเทอร์เน็ต)
**อย่าเปิดพอร์ต (port-forward) ตรง ๆ ออกเน็ต** — เครื่องบ้านโดนสแกน/ยิงทันที ใช้ **tunnel** แทน:
```bash
./scripts/serve.sh                  # รัน local ไว้ (127.0.0.1:8420)
cloudflared tunnel --url http://localhost:8420   # ได้ URL https ชั่วคราวให้คนนอกเข้า
```
- tunnel (Cloudflare/ngrok) ให้ **HTTPS + ซ่อน IP บ้าน** — ปลอดภัยกว่าเปิดพอร์ตเอง
- **ตอนนี้คำขอจาก tunnel โดน 403** เพราะ Host/Origin เป็นชื่อสาธารณะ ไม่ใช่ loopback (ดูหมายเหตุด้านบน). อย่าใช้ทางนี้จนกว่าจะมี allowlist ของชื่อ tunnel
- ยังต้อง bootstrap + ออกคีย์ + คุมโควตาเหมือนเดิม
- ถ้าจะจริงจังระยะยาว ค่อยย้ายไป VPS/คลาวด์ (ตอนนั้นเครื่อง 8GB จะเป็นคอขวด — ดู docs/ROADMAP.md เรื่องอัป RAM/GPU)

---

## bootstrap + ออก API key ให้ผู้ใช้ (ทำครั้งแรกตอนเปิดจริง)
สมมติ `$TOK` = master token ที่สคริปต์โชว์ (ระดับ 2/3), `$URL` = ที่อยู่ server
```bash
# 1) สร้าง CEO คนแรก
curl -X POST $URL/api/admin/users -H "X-Auth-Token: $TOK" \
  -d '{"username":"boss","password":"ตั้งรหัสยาว ๆ","role":"CEO"}'

# 2) สร้างผู้ใช้ + ออก API key (free/paid) ให้ลูกค้า
curl -X POST $URL/api/admin/users   -H "X-Auth-Token: $TOK" -d '{"username":"user1","password":"xxxxxxxx","role":"USER"}'
curl -X POST $URL/api/admin/apikeys -H "X-Auth-Token: $TOK" -d '{"owner":"user1","tier":"free"}'
# -> คืน key เต็มครั้งเดียว ส่งให้ลูกค้าไปใส่ header X-API-Key
```

## เช็กลิสต์ความปลอดภัยก่อนเปิดจริง (สไตล์ 9arm: อย่าข้าม)
- [ ] เปิดออกนอก 127.0.0.1 = **ต้องมี token** (สคริปต์บังคับให้แล้ว)
- [ ] `config.json`, `org.json`, `*.db` อยู่ใน `.gitignore` แล้ว — secret ไม่หลุดขึ้น git
- [ ] ออกเน็ตใช้ **tunnel + HTTPS** เท่านั้น ไม่ port-forward ดิบ
- [ ] ตั้งโควตา tier free ให้เหมาะ (กันคนยิงจนเครื่องตาย) — rate limit มีอยู่แล้ว
- [ ] จับตา `/dev` → มิเตอร์ RAM/CPU; แตะ 90% = ลดโมเดล/จำกัดคน
- [ ] อยากได้แจ้งเตือน (คนสมัคร/บั๊ก/เงิน) → ตั้ง `DISCORD_WEBHOOK_URL` ใน config.json (ดู docs/AGENT_ORG.md)

## สิ่งที่ยังไม่พร้อมสำหรับ "โปรดักชันจริงจัง" (พูดตรง)
- ยังไม่มีตัดเงินจริง (payment gateway) — มีแค่ usage ledger + บันทึก (รอเลือก provider)
- เครื่อง 8GB + iGPU = เดโม/ผู้ใช้จำนวนน้อยได้ แต่สเกลเยอะต้องมี GPU box / คลาวด์
- backup ข้อมูล (`*.db`) ควรตั้ง cron สำรองไป HDD ภายนอกก่อนเปิดรับผู้ใช้จริง
