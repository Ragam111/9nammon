"""Simulate two customers against a running LCA API before going live.

Checks: tenant isolation (RLS), API-key auth, per-tenant monthly quota,
usage accounting, and (optional) rate limiting.

pip install asyncpg httpx
Env:
  API_URL    default http://localhost:8000
  ADMIN_DSN  superuser DSN, used only to seed/clean test data
  APP_DSN    the lca_app DSN, used to prove RLS from the app's point of view
  RATE_TEST  set to 1 to also fire ~40 requests and expect HTTP 429
Run: python sim_customers.py
"""
import asyncio
import hashlib
import os
import sys
import uuid

import asyncpg
import httpx

API = os.getenv("API_URL", "http://localhost:8000")
ADMIN_DSN = os.getenv("ADMIN_DSN", "postgresql://postgres:pgpass@localhost:5432/lca")
APP_DSN = os.getenv("APP_DSN", "postgresql://lca_app:change-me@localhost:5432/lca")
RATE_TEST = os.getenv("RATE_TEST") == "1"

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def sha(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()


async def seed(admin, name: str, quota: int):
    run = uuid.uuid4().hex[:6]
    tid = await admin.fetchval(
        "INSERT INTO tenants (name, monthly_token_quota) VALUES ($1, $2) RETURNING id",
        f"sim-{name}-{run}", quota)
    uid = await admin.fetchval(
        "INSERT INTO users (tenant_id, email) VALUES ($1, $2) RETURNING id",
        tid, f"dev@{name.lower()}-{run}.test")
    key = f"sk-sim-{uuid.uuid4().hex}"
    await admin.execute(
        "INSERT INTO api_keys (tenant_id, user_id, key_hash) VALUES ($1, $2, $3)",
        tid, uid, sha(key))
    for i in range(3):
        await admin.execute(
            "INSERT INTO chat_sessions (tenant_id, user_id, title) VALUES ($1, $2, $3)",
            tid, uid, f"{name} secret session {i}")
    return {"id": tid, "user": uid, "key": key}


async def in_tenant(conn, tenant_id, fn):
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
        return await fn()


async def test_isolation(app, A, B):
    print("\n-- Tenant isolation (as lca_app) --")
    rows = await in_tenant(app, A["id"], lambda: app.fetch("SELECT tenant_id, title FROM chat_sessions"))
    check("A sees only its own 3 sessions", len(rows) == 3 and all(r["tenant_id"] == A["id"] for r in rows))

    rows = await in_tenant(app, B["id"], lambda: app.fetch("SELECT title FROM chat_sessions"))
    check("B never sees A's titles", len(rows) == 3 and all(r["title"].startswith("B ") for r in rows))

    n = await app.fetchval("SELECT count(*) FROM chat_sessions")
    check("no tenant context -> zero rows", n == 0)

    async def cross_update():
        return await app.execute(
            "UPDATE chat_sessions SET title='hacked' WHERE tenant_id = $1", B["id"])
    status = await in_tenant(app, A["id"], cross_update)
    check("A cannot update B's rows", status == "UPDATE 0", status)

    try:
        async with app.transaction():
            await app.execute("SELECT set_config('app.tenant_id', $1, true)", str(A["id"]))
            await app.execute("INSERT INTO chat_sessions (tenant_id, title) VALUES ($1, 'planted')", B["id"])
        check("A cannot insert rows into B", False, "insert succeeded")
    except asyncpg.PostgresError as e:
        check("A cannot insert rows into B", e.sqlstate == "42501", f"sqlstate={e.sqlstate}")


async def test_auth(http):
    print("\n-- Auth --")
    r = await http.post("/v1/chat", json={"prompt": "hi"})
    check("missing key rejected", r.status_code in (401, 422), str(r.status_code))
    r = await http.post("/v1/chat", json={"prompt": "hi"}, headers={"x-api-key": "sk-wrong"})
    check("wrong key -> 401", r.status_code == 401, str(r.status_code))


async def test_quota(http, A, B):
    print("\n-- Monthly quota (A has a tiny quota, B a large one) --")
    ok_a, blocked = 0, None
    for _ in range(15):
        r = await http.post("/v1/chat", json={"prompt": "explain python decorators"},
                            headers={"x-api-key": A["key"]})
        if r.status_code == 200:
            ok_a += 1
        else:
            blocked = r
            break
    check("A is blocked once quota is used", blocked is not None and blocked.status_code == 429
          and "quota" in blocked.text.lower(), f"after {ok_a} ok request(s)")

    r = await http.post("/v1/chat", json={"prompt": "still working for B?"},
                        headers={"x-api-key": B["key"]})
    check("B unaffected by A's quota", r.status_code == 200, str(r.status_code))
    return ok_a


async def test_accounting(admin, A, B, ok_a):
    print("\n-- Usage accounting --")
    for label, t in (("A", A), ("B", B)):
        ev = await admin.fetchval(
            "SELECT COALESCE(sum(prompt_tokens + completion_tokens), 0) FROM usage_events WHERE tenant_id=$1", t["id"])
        mo = await admin.fetchval(
            "SELECT COALESCE(sum(tokens_used), 0) FROM usage_monthly WHERE tenant_id=$1", t["id"])
        check(f"{label}: usage_events total == usage_monthly", ev == mo and ev > 0, f"{ev} vs {mo}")
    n = await admin.fetchval("SELECT count(*) FROM usage_events WHERE tenant_id=$1", A["id"])
    check("A: one usage row per successful request", n == ok_a, f"{n} rows, {ok_a} ok")


async def test_rate_limit(http, B):
    print("\n-- Rate limit (30/minute per key) --")
    sem = asyncio.Semaphore(10)

    async def one():
        async with sem:
            r = await http.post("/v1/chat", json={"prompt": "ping"}, headers={"x-api-key": B["key"]})
            return r.status_code

    codes = await asyncio.gather(*[one() for _ in range(40)])
    ok, limited = codes.count(200), codes.count(429)
    check("burst gets HTTP 429 from the limiter", limited > 0, f"{ok} ok, {limited} limited")


async def main() -> int:
    admin = await asyncpg.connect(ADMIN_DSN)
    app = await asyncpg.connect(APP_DSN)
    A = await seed(admin, "A", quota=500)          # tiny quota, ~2 requests
    B = await seed(admin, "B", quota=10_000_000)
    try:
        async with httpx.AsyncClient(base_url=API, timeout=180) as http:
            await test_isolation(app, A, B)
            await test_auth(http)
            ok_a = await test_quota(http, A, B)
            await test_accounting(admin, A, B, ok_a)
            if RATE_TEST:
                await test_rate_limit(http, B)
    finally:
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [A["id"], B["id"]])
        await admin.close()
        await app.close()
    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
