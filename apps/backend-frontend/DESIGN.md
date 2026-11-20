# DESIGN.md — backend-frontend

ทิศทาง: workbench เงียบ ๆ เน้นอ่านข้อมูลได้ชัด ไม่หวือหวา

ไฟล์โทเคนหลักคือ [frontend/src/styles/tokens.css](frontend/src/styles/tokens.css) ทุกสีและระยะในโค้ดต้องมาจากโทเคนนี้ ห้ามใส่ hex หรือ px ตรง ๆ ใน component

## Color
- **Neutral (1 ชุด):** `--bg`, `--surface`, `--surface-2`, `--line`, `--fg`, `--muted`
- **Accent (1 สี):** `--accent`, `--accent-fg`, `--accent-weak`
- **สถานะ 3 แบบ:** สำเร็จ `--ok` / เตือน `--warn` / ล้มเหลว `--bad` พร้อมพื้นหลัง `--*-bg`
  - กฎ: ทุกสถานะต้องมี **ไอคอนหรือข้อความกำกับ** ควบคู่สี เช่น "สำเร็จ", "เตือน: quota ใกล้เต็ม", "ล้มเหลว: key ไม่ถูกต้อง"
  - ห้ามใช้สีอย่างเดียวบอกสถานะ
- ไม่ใช้ gradient เป็นพื้นหลังหลัก

## Type
- เนื้อหา: `--font-sans` (ไทยเป็นหลัก ศัพท์เทคนิคคงภาษาอังกฤษ เช่น API key, token, deploy)
- โค้ด key ID และ log: `--font-mono` (class `.mono`)
- ตัวเลขทุกชนิดใช้ `.tabular` เพื่อให้คอลัมน์ตรงกัน
- ขนาด: xs 12 / sm 14 / md 16 / lg 20 / xl 24 px

## Spacing และ radius
- ระยะใช้ scale 4px: `--space-1` ถึง `--space-16` เท่านั้น
- Radius มีแค่สองระดับ: `--radius-sm` (6px) และ `--radius-md` (10px)
- Shadow มีระดับเดียว: `--shadow-1`

## Theme
- รองรับ light และ dark ผ่านโทเคนเท่านั้น
- ค่าเริ่มต้นตาม `prefers-color-scheme`; ผู้ใช้สลับได้ด้วย `data-theme="light"` หรือ `data-theme="dark"` บน `<html>`
- ห้ามเขียนสีแยกใน dark mode ที่ component

## Motion
- ใช้ `--motion-fast` และ `--motion-base` เท่านั้น
- เมื่อผู้ใช้ตั้ง `prefers-reduced-motion` โทเคนจะเป็น 0 ms อัตโนมัติ

## Focus และ accessibility
- ทุก element ที่โต้ตอบได้ต้องมี focus ring จาก `:focus-visible` (ใช้ `--focus`)
- Mobile เริ่มที่ 360px ห้ามมี horizontal scroll
- Contrast ของ text ต่อพื้นหลังต้องถึง WCAG AA (4.5:1) ทั้งสอง theme

## Component ที่วางแผนไว้ (ยังไม่สร้าง)
Button (primary, secondary, danger, ghost, loading), Input พร้อม validation, Select, Table (sort, empty state), Badge สถานะ, Card, Dialog, Toast, Tabs, Code block พร้อมปุ่ม copy, Skeleton, Error state (บอกว่าเกิดอะไร และทำอะไรต่อได้)

หน้า showcase จะแสดงทุก component ทั้งสอง theme หลังจากสร้าง component เสร็จ (ขั้นที่ 4)
