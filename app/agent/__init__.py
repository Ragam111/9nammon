"""app.agent — AI agent สายเทค: persona + harness + core loop + worker 24/7 + job queue

ต่อ LLM ผ่าน model_backend เดิม (default qwen2.5:0.5b บน Ollama). stdlib ล้วน.
jobs.py = คิวให้ n8n/automation ป้อนงานเข้า, worker.py = หยิบไปทำ 24/7, stats.py = วัดผล.
"""
