# พื้นทฤษฎีภาษาโปรแกรม — Python, C และอื่น ๆ (เข้าใจแก่น ไม่ใช่ท่องไวยากรณ์)

> แทร็กเรียนรู้ (docs/learn): เข้าใจ "ว่าภาษาทำงานยังไงจริง ๆ" แล้วการเลือกภาษา/เขียนให้เร็ว
> จะเป็นเหตุเป็นผล ไม่ใช่ท่องจำ. ผูกกับธีมโปรเจกต์: **คอขวดคือการขยับข้อมูล ไม่ใช่การคำนวณ**

## 0. แก่นเดียวที่ร้อยทุกภาษา
ทุกภาษาคือ **การแลก (trade-off) ระหว่าง 2 ขั้ว**:
- **คนเขียนสบาย/ปลอดภัย** (abstraction สูง, จัดการ memory ให้อัตโนมัติ) — Python
- **เครื่องวิ่งเร็ว/คุมได้ละเอียด** (ใกล้ฮาร์ดแวร์, จัดการ memory เอง) — C

ตรงกลางของการแลกนี้คือเรื่องเดียว: **ใครจัดการหน่วยความจำ (memory) — คนหรือเครื่อง?**
เข้าใจข้อนี้ข้อเดียว อธิบายได้เกือบทุกความต่างของภาษา

---

## 1. ภาษารันยังไง: compiled / interpreted / JIT
ซอร์สโค้ดที่เราเขียน CPU อ่านไม่รู้เรื่อง ต้องแปลงเป็นคำสั่งเครื่อง (machine code) ก่อน — ต่างกันที่ "แปลงเมื่อไร":

| แบบ | แปลงเมื่อไร | ตัวอย่าง | ผล |
|---|---|---|---|
| **Compiled** | ก่อนรัน (ครั้งเดียว → ไฟล์ binary) | C, C++, Rust, Go | รันเร็วสุด, error หลายอย่างเจอตอน compile |
| **Interpreted** | ขณะรัน (ทีละบรรทัด ผ่าน VM) | Python, Ruby | ช้ากว่า แต่เขียน/ทดลองไว, error เจอตอนรัน |
| **JIT** | ขณะรัน แต่ compile ส่วนที่วนบ่อยเป็น machine code | JavaScript(V8), Java, PyPy | เริ่มช้า แต่พอวอร์มแล้วเร็วใกล้ compiled |

> Python ที่เราใช้ (CPython) แปลงเป็น **bytecode** ก่อน แล้วให้ VM ตีความทีละคำสั่ง —
> นี่คือเหตุผลหลักที่ Python ช้ากว่า C หลายสิบเท่าในงานคำนวณล้วน

---

## 2. Memory model — หัวใจของความต่าง

### C: คนจัดการเอง (manual)
- ตัวแปรคือ "กล่องที่อยู่จริงใน RAM" — รู้ที่อยู่ (pointer) ได้
- **stack** (ตัวแปร local, เร็ว, คืนอัตโนมัติ) vs **heap** (`malloc`/`free`, คุมเอง)
- ลืม `free` = memory leak; `free` ซ้ำ/ใช้หลัง free = bug ร้าย (ช่องโหว่ security เพียบ)
- แลกกับ: **เร็วสุด + คุมได้ทุก byte** (เขียน OS/driver/เกมเอนจิน/kernel ได้)

```c
int *a = malloc(4 * sizeof(int));  // ขอ heap เอง
a[0] = 42;                          // เขียนลง RAM ตรง ๆ
free(a);                            // ต้องคืนเอง ไม่งั้น leak
```

### Python: เครื่องจัดการให้ (automatic)
- ทุกอย่างเป็น **object** บน heap — แม้แต่ `int` ก็เป็น object (มี header, refcount)
- จัดการคืนด้วย **reference counting + garbage collector** (คนไม่ต้อง free)
- `a = [1,2,3]` — `a` คือ *reference* ไปยัง list object ไม่ใช่กล่องข้อมูลเอง
- แลกกับ: **เขียนสบาย ปลอดภัย (ไม่มี dangling pointer)** แต่ช้า + กิน RAM กว่า
  (ทุก int เป็น object ~28 bytes ไม่ใช่ 4 bytes แบบ C)

```python
a = [1, 2, 3]   # object บน heap, a แค่ชี้ไป
b = a           # ไม่ copy! b ชี้ก้อนเดียวกับ a (เข้าใจผิดบ่อย)
b.append(4)     # a ก็เห็น [1,2,3,4] ด้วย
```

> **ทำไมเรื่องนี้โยงธีมโปรเจกต์:** Python ช้าเพราะทุกการอ่านตัวเลข = ตาม pointer ไปหยิบ
> object จาก RAM (ขยับข้อมูลเยอะ + cache miss บ่อย) ส่วน C วางตัวเลขเรียงติดกันใน array
> → CPU cache ทำงานดี. นี่คือ "data movement" ตัวเดียวกับที่ GPU/LLM ติดคอขวด

---

## 3. Type system — ตรวจเมื่อไร?
- **Static typing** (C, Rust, Go, Java): ประกาศชนิดตัวแปร, ตรวจตอน compile → เจอ bug เร็ว, เร็วกว่า
- **Dynamic typing** (Python, JS): ชนิดรู้ตอนรัน, ยืดหยุ่น เขียนไว แต่ bug ชนิดข้อมูลหลุดไปเจอตอนรัน
- **ตรงกลาง — gradual typing**: Python มี *type hints* (`def f(x: int) -> str`) ให้เครื่องมือ
  (mypy) ช่วยตรวจ แต่ตอนรันยังไม่บังคับ — ได้ความปลอดภัยบางส่วนโดยไม่เสียความยืดหยุ่น

---

## 4. แผนที่ภาษาอื่น ๆ บนแกนเดียวกัน
เรียงจาก "ใกล้เครื่อง/เร็ว/คุมเอง" → "ใกล้คน/สบาย/อัตโนมัติ":

```
  C  ─  C++  ─  Rust  ─  Go  ─  Java/C#  ─  JavaScript  ─  Python
 คุม memory เอง            ←——— GC ———→           ทุกอย่างอัตโนมัติ
 เร็วสุด/อันตรายสุด                                เขียนไวสุด/ช้าสุด
```
- **Rust**: เร็วเท่า C แต่ compiler บังคับความปลอดภัย memory ตอน compile (ownership/borrow)
  → ได้ทั้งเร็วและปลอดภัย แลกกับ "เรียนยาก/เขียนเข้มงวด"
- **Go**: มี GC แต่ compiled + goroutine ขนานง่าย → สาย backend/network (เน็ตคือคอขวด = เหมาะ)
- **JavaScript**: dynamic เหมือน Python แต่ JIT (V8) เร็วกว่ามากในงานวน
- **Java/C#**: static + JIT + GC → สมดุล enterprise

---

## 5. ของจริง: Python เรียก C (ทางลัดที่ทุกคนใช้)
ไม่ต้องเลือกข้างเดียว — **เขียน Python ให้สบาย แล้วให้ส่วนหนักวิ่งใน C**:
- `numpy` = Python API บน C/Fortran → array คำนวณเร็วระดับ C
- โมเดล AI: Python เรียก CUDA/C++ (PyTorch) ทำงานหนักบน GPU
- โปรเจกต์นี้: `server.py` เป็น Python (เขียน/ดูแลง่าย) ส่วน LLM จริงวิ่งใน `llama.cpp` (C++)
- notebook `kernel_optimization_101.ipynb`: Python สั่งงาน แต่ kernel เขียนระดับ C (CUDA)

> บทเรียน: **เลือกภาษาตามงานของแต่ละส่วน ไม่ใช่ทั้งโปรเจกต์** — ชั้นประสานงาน/ตรรกะใช้ Python,
> ชั้นคำนวณหนัก/คอขวดใช้ C/CUDA. นี่คือ heterogeneous แบบเดียวกับ docs/HETEROGENEOUS_COMPUTE.md

---

## 6. จะเก่งพื้นทฤษฎี ควรไล่ตามลำดับนี้
1. **โมเดลหน่วยความจำ**: stack vs heap, pointer, value vs reference (ลองใน C สักหน่อยจะเห็นชัดสุด)
2. **ภาษารันยังไง**: compile → assembly → machine code; ลอง `python -c "import dis; dis.dis(f)"` ดู bytecode จริง
3. **ชนิดข้อมูล + ชีวิตของ object**: refcount/GC ของ Python, ownership ของ Rust
4. **Big-O + โครงสร้างข้อมูล**: array vs linked list — ทำไม array เร็วกว่า (cache/locality = data movement อีกแล้ว)
5. **concurrency**: thread vs process vs async; ทำไม Python มี GIL (โยงกับ admission/worker ในโปรเจกต์)

**ลองทันทีในเครื่องนี้:**
```bash
python -c "import dis; dis.dis(lambda x: x*2 + 1)"   # เห็น bytecode ที่ VM ตีความจริง
python -c "import sys; print(sys.getsizeof(1), sys.getsizeof([1,2,3]))"  # int/list กิน RAM เท่าไร
```

---

## ถัดไป (ถ้าอยากเจาะ)
บอกได้ว่าจะให้เขียนเจาะลึกตัวไหนเป็น notebook/เอกสารต่อ เช่น
"pointer & memory ใน C ทีละขั้น", "GIL กับ concurrency ของ Python", หรือ "ทำไม Rust ปลอดภัยโดยไม่ต้อง GC"
