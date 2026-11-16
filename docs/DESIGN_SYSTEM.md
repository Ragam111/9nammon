# LCA — Design System

ระบบดีไซน์กลางของ LCA อยู่ไฟล์เดียว: **`app/app.css`** เสิร์ฟที่ `GET /app.css`
ทุกหน้า (`index.html`, `dev.html`) ลิงก์ไฟล์นี้แทนการเขียน CSS ซ้ำในแต่ละหน้า

## ทำไมต้องรวมเป็นไฟล์เดียว
เดิมแต่ละหน้าเขียนสี/ฟอนต์ของตัวเอง (hardcode `#101014`, `#5b9dff` ฯลฯ) — แก้ธีมทีต้องไล่
หลายไฟล์ และหน้าตาเพี้ยนกันเอง. รวมเป็น `app.css` ชุดเดียว = แก้ที่เดียวทั้งระบบเปลี่ยนตาม
และเบราว์เซอร์ cache ไฟล์ CSS ไว้ โหลดหน้าถัดไปไม่ต้องดึงซ้ำ

## เป้าหมายประสิทธิภาพ: เครื่องอ่อนต้องไม่สะดุด
เครื่องเป้าหมายคือโน้ตบุ๊ก Intel U-series รุ่นเก่า (iGPU) + RAM 8GB — ของพวกนี้วาดภาพช้าและ
แรมจำกัด กฎที่ `app.css` ยึด:

1. **ฟอนต์ระบบล้วน** — `system-ui, "Segoe UI", "Leelawadee UI", "Thonburi", "Noto Sans Thai", "Sarabun"`
   ไม่ดึง webfont จากเน็ตเลย → ไม่มีตัวหนังสือกระพริบตอนโหลด (FOIT), ไม่กินเน็ต, ไม่กินแรม
   โหลดฟอนต์. ฝั่ง mono ใช้ `ui-monospace, "Cascadia Mono", "Consolas"`
2. **ไม่มี `backdrop-filter` / `filter: blur` / เงาหนา** — effect พวกนี้ให้ GPU วาด เครื่อง iGPU
   เก่าจะกระตุกและเปลืองแบต. ใช้ **เส้นขอบ (border) แทนเงา** ในลิสต์ที่สกรอล (รีเพนต์ถูกกว่า)
3. **ไม่มีอนิเมชันวนตลอด** ยกเว้นจุด "กำลังคิด" กระพริบเบา ๆ อันเดียว
4. **`prefers-reduced-motion: reduce`** → ปิด transition/animation ทั้งหมด (ช่วยเครื่องอ่อน + accessibility)
5. **light/dark ตาม OS โดยไม่ใช้ JS** — ลดงาน main thread ไม่มีสคริปต์คอยสลับธีม

## โทเคน (CSS custom properties)
ประกาศบน `:root` (ค่าธีมสว่าง) แล้ว override เป็นธีมมืดใน `@media (prefers-color-scheme: dark)`
และ `:root[data-theme="dark"]`. ใช้ prefix `--lca-` กันชนกับของอื่น

| กลุ่ม | โทเคน |
|------|-------|
| พื้น | `--lca-bg`, `--lca-surface`, `--lca-surface-2` |
| เส้น/ตัวอักษร | `--lca-line`, `--lca-fg`, `--lca-muted` |
| แอคเซนต์ | `--lca-accent`, `--lca-accent-weak`, `--lca-accent-fg` |
| สถานะ | `--lca-ok`, `--lca-warn`, `--lca-bad` |
| แชท | `--lca-user`, `--lca-user-line` |
| ฟอนต์/รูปทรง | `--lca-sans`, `--lca-mono`, `--lca-r`, `--lca-r-lg`, `--lca-gutter` |

**กติกา**: ห้าม hardcode สีในหน้าใด ๆ อีก — ใช้โทเคนเสมอ สีใหม่ให้เพิ่มเป็นโทเคนก่อน

## คอมโพเนนต์
- ใช้ร่วม: `.chip` (+`.ok/.warn/.bad`), `.lca-btn` (+`.primary`), `.lca-mono`, `.lca-num`, `.lca-muted`
- หน้าแชท: scope ด้วย `body.page-chat` — `#sidebar`, `#chat`, `.msg` (+`.user/.assistant/.system-note`), `#input-bar` ฯลฯ
- หน้า dev: scope ด้วย `body.page-dev` — `header`, `.card`, `.kv`, `.tag`, `table` ฯลฯ
  (scope ใต้ `.page-dev` เพื่อไม่ให้ไปชนปุ่ม/อินพุตของหน้าแชท)

## วิธีเพิ่มหน้าใหม่
1. ใส่ `<link rel="stylesheet" href="/app.css">` ใน `<head>`
2. ใส่ `class="page-xxx"` ที่ `<body>` แล้ว scope สไตล์เฉพาะหน้าใต้ `.page-xxx`
3. ใช้โทเคน `--lca-*` และคอมโพเนนต์ร่วม ไม่ hardcode สี
