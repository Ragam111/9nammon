# LCA (9nammon) — cloud-deployable image
# รันได้บน Render / Fly.io / Hugging Face Spaces / Google Cloud Run / Oracle Cloud
#
# หมายเหตุสำคัญ (9arm honesty): image นี้รัน web/API ของ LCA — *ไม่ได้* รวม Ollama
# เพราะโฮสต์ฟรีส่วนใหญ่ RAM ไม่พอรัน LLM. ตั้ง MODEL_BACKEND=openai แล้วชี้ไป cloud LLM
# (adapter OpenAI-compatible) หรือ deploy บนเครื่องที่มี RAM พอแล้วรัน Ollama แยก.
#
# build : docker build -t lca .
# run   : docker run -p 8420:8420 -e LCA_HOST=0.0.0.0 -e LCA_TOKEN=<secret> lca

FROM python:3.11-slim

WORKDIR /app

# ติดตั้ง dependency ก่อน (ชั้น cache แยก — โค้ดเปลี่ยนไม่ต้องลงใหม่)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดโค้ดเข้ามา
COPY . .

# cloud host จะ inject $PORT; bind 0.0.0.0 เพื่อรับ traffic จากนอก container
# LCA_TOKEN ต้องตั้งผ่าน env ตอน run (bind นอก localhost โดยไม่มี token = ปฏิเสธ)
ENV LCA_HOST=0.0.0.0
EXPOSE 8420

# project_dir = /app (ใช้เก็บ todo/config); server อ่าน $PORT/$LCA_HOST/$LCA_TOKEN เอง
CMD ["python", "server.py", "/app"]
