# ไฟล์สั่งงาน Tools (REA)

สถานะ ณ 2026-11-19 — ผู้ใช้เรียกใช้เอง ห้าม commit/push โดยไม่ได้รับอนุมัติ

## งานที่เสร็จแล้ว
- Dev server LCA รันที่ http://localhost:9431 (`.claude/launch.json` ชี้ branch ที่ merge แล้ว)
- หน้า Software Engineer: `docs/architecture-poster.html` (ยังไม่เปิดดูในเบราว์เซอร์)
- บันทึก memory: dev server, หน้า architecture, ดัชนี MEMORY.md

## งานที่ค้าง
1. `gh auth login` ยังไม่สำเร็จ (`gh auth status` ยังไม่ login) — ผู้ใช้ต้องรันเอง
2. รอยืนยัน: commit เฉพาะ `docs/architecture-poster.html` บน branch ใหม่ → push → เปิด PR ไป `main`
3. ไฟล์ค้างที่ไม่เกี่ยว ห้าม commit: `Python-3.12.16/`, `src/`, `frontend/`, `50-backend/`, `main.py`, `.claude/launch.json`

## เครื่องมือที่ใช้ได้
- Bash (git, gh, curl)
- Workflow (ตรวจหลายรอบ, ต้องได้รับอนุมัติ)
- Artifact (publish หน้าเว็บ, เมื่อผู้ใช้ขอ)
- Memory ที่ `C:\Users\Hello\.claude\projects\D--Desktop-9nammon-main\memory\`
