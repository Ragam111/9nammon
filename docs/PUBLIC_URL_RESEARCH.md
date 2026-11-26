# รายงาน Agent 4 นักวิจัย (ตรวจซ้ำแล้ว 2026-11-26)
หมายเหตุ: รอบนี้ค้นเว็บตรวจเฉพาะ Cloudflare Quick Tunnel, ngrok free และ Tailscale Funnel ส่วนตัวเลือกอื่นยังไม่ได้ตรวจ ป้าย [ยืนยันแล้ว] หมายถึงตรงกับเอกสารทางการ ส่วน [ยังไม่ยืนยัน] หมายถึงยังไม่ได้เช็กที่หน้าเว็บจริง

## A) URL HTTPS สาธารณะแบบไม่ต้องซื้อโดเมน

| ตัวเลือก | ฟรี | URL คงที่ | ใช้กับ Stripe webhook ได้ไหม | หน้าคั่น | ลิมิต / ToS | บัญชี | ความเสี่ยง |
|---|---|---|---|---|---|---|---|
| Cloudflare Quick Tunnel | ใช่ | ไม่คงที่ สุ่มใหม่ทุกครั้งที่รัน | ใช้ทดสอบได้ แต่ต้องแก้ endpoint ใน Stripe ทุกครั้ง | ไม่มี | **[ยืนยันแล้ว]** รับ request ที่ค้างอยู่พร้อมกันได้สูงสุด 200 ตัว ตัวที่เกินจะได้ 429, ไม่รองรับ SSE, ไม่รับประกัน uptime, ไว้ใช้ทดสอบและพัฒนาเท่านั้น https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/ (ลิงก์ในรายงานเดิมย้ายไปที่นี่แล้ว) | ไม่ต้อง | URL รั่วเมื่อไหร่ ใครก็เข้าได้ ต้องเปิด auth ของ LCA ไว้ |
| Cloudflare named tunnel | ใช่ | คงที่ | ได้ | ไม่มี | ถ้าจะเปิด hostname สาธารณะต้องมีโดเมนบน Cloudflare จึงใช้ไม่ได้ถ้าไม่มีโดเมน (ข้อนี้ไม่ได้ค้นซ้ำ แต่สอดคล้องกับเอกสาร) | ต้อง | ต่ำ |
| ngrok free | ใช่ | คงที่: ได้ dev domain ที่ระบบกำหนดให้ 1 ชื่อ **[ยืนยันแล้ว]** | ได้ หน้าคั่นแสดงกับผู้เข้าผ่าน browser ส่วน Stripe ไม่ใช่ browser จึงน่าจะผ่านได้ และข้ามหน้าคั่นได้ด้วย header `ngrok-skip-browser-warning` [ยังไม่ยืนยันกับเอกสาร] | มี (เอกสารมีหัวข้อวิธีเอาหน้าคั่นออก) จึงไม่เหมาะให้ลูกค้าเข้า | **แก้ไข:** request 20,000 ต่อเดือน, ข้อมูลขาออก 1 GB ต่อเดือน, 4,000 request ต่อนาที, เอกสารทางการบอกว่าไม่มี timeout ของ session (บทความภายนอกที่บอกว่าตัดที่ 2 ชั่วโมงขัดกับเอกสารทางการ จึงยังไม่ยืนยัน), จำนวน endpoint ที่ออนไลน์พร้อมกันเอกสารเขียนไม่ตรงกัน (1 หรือ 3) https://ngrok.com/docs/pricing-limits/free-plan-limits ; ToS ที่ว่า "ใช้พัฒนาเท่านั้น" ยังไม่ยืนยัน แต่ FAQ แนะนำแผน Pro สำหรับการทดสอบ webhook | ต้อง | ต่ำ-กลาง (20k request ต่อเดือนอาจหมดถ้ามีคน poll) |
| Tailscale Funnel | ใช่ (มีให้ทุกแผน) **[ยืนยันแล้ว]** | คงที่ `https://<เครื่อง>.<tailnet>.ts.net` | ได้ (ใบ cert ถูกต้อง) | ไม่มี | **[ยืนยันแล้ว]** เปิดสาธารณะได้เฉพาะพอร์ต 443/8443/10000 ส่วนพอร์ตปลายทางในเครื่องเป็นเลขอะไรก็ได้, มีลิมิตแบนด์วิดท์ที่ตั้งค่าไม่ได้และไม่ประกาศตัวเลข, ยังเป็น **beta**, ใช้ได้เฉพาะ TLS https://tailscale.com/kb/1223/funnel ; Personal plan ใช้ฟรีเฉพาะงานไม่ใช่เชิงพาณิชย์ (ข้อมูลจากแหล่งภายนอก) [ยังไม่ยืนยันกับ ToS] | ต้อง | กลาง: เป็น beta และใช้ค้าขายไม่ได้ |
| DuckDNS / No-IP + Let's Encrypt | ใช่ | คงที่ | ได้ ถ้าเข้าจากภายนอกได้ | ไม่มี | ต้อง port forward และมักติด CGNAT (100.64.x หรือ WAN IP ไม่ตรงกับ IP สาธารณะ) [ยังไม่ยืนยัน] | ต้อง | สูง: ขัดกับข้อห้ามแก้ firewall |
| localhost.run | ใช่ | ไม่คงที่ | แค่ทดสอบ | [ยังไม่ยืนยัน] | [ยังไม่ยืนยัน] | ไม่ต้อง | กลาง |
| Pinggy | ใช่ | ไม่คงที่ (หมดอายุราว 60 นาที) [ยังไม่ยืนยัน] | แค่ทดสอบ | [ยังไม่ยืนยัน] | https://pinggy.io/pricing | ไม่ต้อง | กลาง |
| zrok | ใช่ | reserved share | [ยังไม่ยืนยัน] | [ยังไม่ยืนยัน] | [ยังไม่ยืนยัน] | ต้อง | กลาง |
| serveo | ใช่ | บางส่วน | ไม่น่าเชื่อถือ | — | ไม่มี SLA | ไม่ต้อง | ไม่แนะนำ |
| GitHub Pages | ใช่ | `<user>.github.io` | ไม่ได้ (static อย่างเดียว) | ไม่มี | ใช้เป็นหน้าแนะนำธุรกิจได้ ห้ามใช้เป็นเว็บค้าขายหลัก [ยังไม่ยืนยัน] | ต้อง | ต่ำ |
| Stripe CLI `stripe listen --forward-to` | ใช่ | ไม่ต้องมี URL สาธารณะ | ใช้ได้ใน test mode ต้องเปิด CLI ค้างไว้ และใช้ `whsec_` ของ CLI | — | https://docs.stripe.com/stripe-cli | บัญชี Stripe | ต่ำที่สุด |

### ข้อแนะนำ (ปรับแล้ว)
- **เปิดตัว 28 พ.ย. (ลูกค้าใน LAN + Stripe test mode):** ใช้ `http://<IP ใน LAN>:8420` คู่กับ `stripe listen` วิธีนี้ปลอดภัยที่สุดและไม่ต้องเปิดพอร์ต (ไม่เปลี่ยนจากเดิม)
- **ต้องการ HTTPS สาธารณะฟรีที่ URL คงที่:** Tailscale Funnel ยังเป็นอันดับ 1 แต่ต้องบอกไว้ว่าเป็น **beta** แบนด์วิดท์ไม่ประกาศตัวเลข และ Personal plan เป็นแบบไม่ใช่เชิงพาณิชย์ ส่วน ngrok dev domain เหมาะกับ webhook อย่างเดียว ลิมิตคือ 20k request และ 1 GB ต่อเดือน
- **เปิด live mode จริง:** free tier ไม่มี SLA ระยะยาวควรซื้อโดเมนแล้วใช้ Cloudflare named tunnel (ราคาโดเมน ~300–400 บาท/ปี [ยังไม่ยืนยัน])

### สิ่งที่โค้ด LCA ต้องมี/ต้องเช็ก
(ไม่เปลี่ยนจากเดิม ข้อ 1–7 เป็นแนวปฏิบัติ ไม่ได้เป็นข้อเท็จจริงเรื่องบริการที่ต้องตรวจ: raw body + HMAC-SHA256 + `compare_digest` + กันเวลา 300 วินาที, แยก secret ตามโหมด, idempotency ด้วย `event.id`, `LCA_TRUST_PROXY` เชื่อ `CF-Connecting-IP` หรือ `X-Forwarded-For` เฉพาะเมื่อคำขอมาจาก 127.0.0.1, ตั้ง Secure cookie และ HSTS เฉพาะเมื่อเป็น HTTPS, เพิ่ม redirect URI ของ OAuth, bind ที่ 127.0.0.1) หมายเหตุเพิ่ม: Quick Tunnel ไม่รองรับ SSE ถ้า LCA stream คำตอบด้วย SSE จะใช้ผ่าน Quick Tunnel ไม่ได้

## B) ทดสอบระบบควบคุมเครื่องผ่าน LAN ก่อนมีเครื่องที่ 2
ส่วนนี้ไม่ได้ตรวจซ้ำ (ไม่อยู่ในขอบเขตเรื่อง free tier/URL/ToS) ให้ใช้ตาราง 6 วิธี แผนทดสอบ 8 ขั้น และ checklist ตามรายงานเดิม จุดที่ยังติดป้าย [ยังไม่ยืนยัน] ยังคงอยู่ คือ Windows Sandbox อาจโหลด OpenSSH capability ไม่ได้ และยังไม่รู้ว่าสคริปต์มีโหมด dry-run หรือ `-WhatIf` หรือไม่ ต้องอ่าน D:\Desktop\9nammon-main\scripts\node_setup_server.ps1 ก่อน

ไฟล์ที่อ้างถึง: D:\Desktop\9nammon-main\docs\REMOTE_NODE.md, D:\Desktop\9nammon-main\scripts\node_setup_server.ps1, D:\Desktop\9nammon-main\scripts\node_setup_client.ps1, D:\Desktop\9nammon-main\scripts\node_ctl.py

แหล่งข้อมูล: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/), [ngrok free plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits), [ngrok licensing FAQ](https://ngrok.com/docs/guides/licensing/), [Tailscale Funnel](https://tailscale.com/kb/1223/funnel), [Tailscale funnel CLI](https://tailscale.com/kb/1311/funnel)