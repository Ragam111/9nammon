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
- `data-theme` ใส่บน element ใดก็ได้ เพื่อให้กล่องนั้นและลูกทั้งหมดใช้ theme นั้น (หน้า showcase ใช้วิธีนี้แสดงสองธีมคู่กัน) กล่องนั้นต้องตั้งพื้นหลังเองด้วย `bg-bg text-fg`
- ห้ามเขียนสีแยกใน dark mode ที่ component

## Motion
- ใช้ `--motion-fast` และ `--motion-base` เท่านั้น
- เมื่อผู้ใช้ตั้ง `prefers-reduced-motion` โทเคนจะเป็น 0 ms อัตโนมัติ

## Focus และ accessibility
- ทุก element ที่โต้ตอบได้ต้องมี focus ring จาก `:focus-visible` (ใช้ `--focus`)
- Mobile เริ่มที่ 360px ห้ามมี horizontal scroll
- Contrast ของ text ต่อพื้นหลังต้องถึง WCAG AA (4.5:1) ทั้งสอง theme

## Components
ทั้งหมดอยู่ใน [frontend/src/components/ui.tsx](frontend/src/components/ui.tsx) ใช้ Tailwind class ที่ map มาจากโทเคน (ดู `@theme inline` ใน `frontend/src/index.css`) ห้ามใช้สี Tailwind ตั้งต้น เช่น `bg-blue-500`

| Component | ใช้เมื่อ | หมายเหตุ |
|---|---|---|
| `Button` | ทุกปุ่ม | `variant`: primary (การกระทำหลักหนึ่งเดียวต่อหน้า), secondary, danger (ลบ/ทำแล้วย้อนไม่ได้), ghost; `loading` ปิดปุ่มและใส่ `aria-busy` |
| `Input` | ช่องกรอก | ต้องมี `label` เสมอ; `error` ตั้ง `aria-invalid` และผูกข้อความด้วย `aria-describedby` |
| `Select` | ตัวเลือกจากรายการ | `label` และ `options` |
| `Badge` | สถานะ | `status`: ok / warn / bad / neutral มีไอคอนและข้อความทุกครั้ง |
| `Card` | กลุ่มเนื้อหา | `title` และ `actions` ไม่บังคับ |
| `Dialog` | ยืนยันก่อนทำสิ่งที่ย้อนไม่ได้ | ใช้ `<dialog>` ของ browser ซึ่งจัด focus และปุ่ม Escape ให้ |
| `ToastProvider` / `useToast` | แจ้งผลสั้น ๆ | `show(status, text)` หายเองใน 4 วินาที อยู่ใน live region |
| `Tabs` | สลับมุมมองในหน้าเดียว | ลูกศรซ้าย/ขวา, Home, End |
| `Table` | ข้อมูลแบบแถว | คอลัมน์ `sortable`, `numeric` (ชิดขวา + tabular), `mono`; `empty` แสดงเมื่อไม่มีข้อมูล |
| `CodeBlock` | โค้ด, log, key ID | ปุ่ม copy; ถ้าใช้ clipboard ไม่ได้จะเลือกข้อความให้กด Ctrl+C |
| `Skeleton` | ระหว่างโหลด | ซ่อนจาก screen reader |
| `ErrorState` | เกิดข้อผิดพลาด | บอกว่าเกิดอะไร และมีปุ่มทำต่อ เช่น "ลองใหม่" |

ตัวอย่าง:

```tsx
<Badge status="warn">เตือน: quota เหลือ 10%</Badge>
<Button variant="danger" onClick={openConfirm}>ลบประวัติ</Button>
<ErrorState title="หมดเวลารอคำตอบ" detail="โมเดลไม่ตอบภายใน 30 วินาที" action={{ label: "ลองใหม่", onClick: retry }} />
```

## Showcase
หน้า showcase แสดงทุก component ในกล่องธีมสว่างและธีมมืดคู่กัน

```powershell
cd apps/backend-frontend/frontend
npm install
npm run dev
```

แล้วเปิด http://127.0.0.1:5173
