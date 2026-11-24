"""Fake Ollama /api/chat for dry-run tests (no GPU, no model download).

Run: uvicorn fake_ollama:app --port 11434
Returns fixed token counts so quota maths is predictable.
"""
from fastapi import FastAPI, Request

app = FastAPI()


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    prompt = body["messages"][-1]["content"]
    return {
        "model": body.get("model", "fake"),
        "message": {"role": "assistant", "content": f"(fake answer) {prompt[:40]}"},
        "done": True,
        "prompt_eval_count": 100 + len(prompt.split()),
        "eval_count": 200,
    }
