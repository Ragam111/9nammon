"""LCA example: API-key auth -> tenant context (RLS) -> rate limit -> monthly token quota -> Ollama.

pip install fastapi uvicorn slowapi "sqlalchemy[asyncio]" asyncpg httpx
Run: uvicorn main:app --reload
"""
import hashlib
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DB_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://lca_app:change-me@localhost:5432/lca")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("LCA_MODEL", "qwen2.5-coder:1.5b")   # small default for 8 GB RAM / CPU-only machines
NUM_CTX = int(os.getenv("LCA_NUM_CTX", "4096"))          # bigger context = more RAM; keep small on weak PCs
# Use redis://redis:6379 when running more than one worker; memory:// is per-process.
RATE_STORAGE = os.getenv("RATE_LIMIT_STORAGE", "memory://")

engine = create_async_engine(DB_URL, pool_size=10)
Session = async_sessionmaker(engine, expire_on_commit=False)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def rate_key(request: Request) -> str:
    """Rate-limit per API key (hashed), fall back to client IP."""
    key = request.headers.get("x-api-key")
    return hash_key(key)[:16] if key else request.client.host


limiter = Limiter(key_func=rate_key, storage_uri=RATE_STORAGE)
app = FastAPI(title="LCA API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@dataclass
class Auth:
    tenant_id: str
    user_id: str | None
async def authenticate(x_api_key: str | None = Header(None)) -> Auth:
    if not x_api_key:
        raise HTTPException(401, "Missing API key")
    async with Session() as s:
        row = (
            await s.execute(
                text("SELECT tenant_id, user_id FROM api_keys "
                     "WHERE key_hash = :h AND revoked_at IS NULL"),
                {"h": hash_key(x_api_key)},
            )
        ).first()
    if not row:
        raise HTTPException(401, "Invalid API key")
    return Auth(str(row.tenant_id), str(row.user_id) if row.user_id else None)


@asynccontextmanager
async def tenant_tx(tenant_id: str):
    """One transaction with app.tenant_id set; RLS filters every query inside it.
    set_config(..., true) is transaction-local, so it never leaks across pooled connections."""
    async with Session() as s, s.begin():
        await s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
        yield s


class ChatIn(BaseModel):
    prompt: str


@app.post("/v1/chat")
@limiter.limit("30/minute")          # per API key; the `request` arg is required by slowapi
async def chat(request: Request, body: ChatIn, auth: Auth = Depends(authenticate)):
    month = date.today().replace(day=1)

    # 1) Quota check (short transaction, so no DB connection is held during inference)
    async with tenant_tx(auth.tenant_id) as s:
        quota = (await s.execute(text("SELECT monthly_token_quota FROM tenants"))).scalar_one()
        used = (
            await s.execute(
                text("SELECT COALESCE(tokens_used, 0) FROM usage_monthly WHERE month = :m"),
                {"m": month},
            )
        ).scalar() or 0
    if used >= quota:
        raise HTTPException(429, "Monthly token quota exceeded")

    # 2) Inference
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": MODEL, "stream": False,
                      "options": {"num_ctx": NUM_CTX},
                      "messages": [{"role": "user", "content": body.prompt}]},
            )
    except httpx.TimeoutException:
        raise HTTPException(504, "Inference backend timed out")
    except httpx.HTTPError:
        raise HTTPException(502, "Inference backend unreachable")
    if r.status_code != 200:
        raise HTTPException(502, "Inference backend error")
    data = r.json()
    p_tokens = data.get("prompt_eval_count", 0)
    c_tokens = data.get("eval_count", 0)

    # 3) Record usage
    async with tenant_tx(auth.tenant_id) as s:
        await s.execute(
            text("INSERT INTO usage_events (tenant_id, user_id, model, prompt_tokens, completion_tokens) "
                 "VALUES (:t, :u, :m, :p, :c)"),
            {"t": auth.tenant_id, "u": auth.user_id, "m": MODEL, "p": p_tokens, "c": c_tokens},
        )
        await s.execute(
            text("INSERT INTO usage_monthly (tenant_id, month, tokens_used) VALUES (:t, :mo, :n) "
                 "ON CONFLICT (tenant_id, month) "
                 "DO UPDATE SET tokens_used = usage_monthly.tokens_used + EXCLUDED.tokens_used"),
            {"t": auth.tenant_id, "mo": month, "n": p_tokens + c_tokens},
        )

    return {
        "answer": data["message"]["content"],
        "tokens": {"prompt": p_tokens, "completion": c_tokens, "used_this_month": used + p_tokens + c_tokens},
    }
