# docs/learn — บทเรียนเจาะลึก (เขียน + วัดผล + เข้าใจ)

ไม่ใช่โค้ดโปรดักชัน แต่เป็นห้องทดลองไว้ "พิสูจน์ด้วยมือตัวเอง" ตามปรัชญาโปรเจกต์:
**วัดก่อนเชื่อ, คอขวดจริงสำคัญกว่าสเปคสวย** (ดู `docs/9ARM_PRINCIPLES.md`)

## kernel_optimization_101.ipynb
เขียน CUDA kernel จริง 2 แบบ (naive vs tiled/shared-memory) วัดผล เทียบ cuBLAS

**รันที่ไหน:** Google Colab → Runtime → Change runtime type → GPU (T4)
K600 รันไม่ได้ (Kepler CC 3.0 เก่าเกินกว่า CUDA ปัจจุบัน) — นี่เองเป็นเหตุผลว่าทำไมเราพิสูจน์แล้วว่า CPU ชนะ K600 สำหรับ LLM

**ได้อะไร:**
- เห็นกับตาว่า tiled เร็วกว่า naive หลายเท่า **ทั้งที่คำนวณเท่าเดิม** — ลดแค่การอ่าน memory
- เข้าใจ arithmetic intensity + ลำดับขั้น optimize (global → shared → register → tensor core)
- เชื่อมกับ LLM: inference เป็น matmul ที่ memory-bound → VRAM เล็ก/ช้าแพ้ แม้ FLOP พอ

> ธีมเดียวกับทั้งโปรเจกต์: **the bottleneck is data movement, not compute.**
