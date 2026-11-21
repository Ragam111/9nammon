"""FastAPI app: health, auth (httpOnly session cookie), key onboarding, streaming run, history, settings.

Run locally:  uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TextIO
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import auth, history, oauth, quota
from .clientip import parse_networks, resolve_client_ip
from .config import Settings, load_settings
from .db import Database
from .errors import AppError, from_exception
from .keystore import KeyStore
from .logging_json import estimate_cost, log_event
from .model_client import StreamResult, estimate_tokens, iter_text, list_models, open_stream, require_key
from .ratelimit import RateLimiter

MAX_BODY_BYTES = 256 * 1024
NOT_FOUND = "ไม่พบประวัตินี้ หรืออาจถูกลบไปแล้ว"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Context:
    settings: Settings
    db: Database
    keys: KeyStore
    limiter: RateLimiter
    http: httpx.AsyncClient
    log_stream: TextIO | None = None


def ctx_of(request: Request) -> Context:
    return request.app.state.ctx


def current_user(request: Request) -> auth.User:
    ctx = ctx_of(request)
    user = auth.user_for_token(ctx.db, request.cookies.get(auth.SESSION_COOKIE))
    request.state.user_id = user.id
    return user


def admin_user(user: auth.User = Depends(current_user)) -> auth.User:
    if user.role != "admin":
        raise AppError("auth", "เฉพาะผู้ดูแลระบบเท่านั้นที่ทำรายการนี้ได้", http_status=403)
    return user


def error_response(err: AppError, request: Request) -> JSONResponse:
    request.state.error_type = err.type
    headers = {"Retry-After": str(err.retry_after_s)} if err.retry_after_s else None
    rid = getattr(request.state, "request_id", "")
    return JSONResponse({"error": err.to_dict(rid)}, status_code=err.status, headers=headers)


# ---------- request bodies ----------

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)


class KeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)


class RunIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    model: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:/-]+$")
    max_output_tokens: int | None = Field(default=None, ge=1, le=100_000)


# ---------- routes ----------

router = APIRouter(prefix="/api")


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    ctx = ctx_of(request)
    return {"status": "ok", "model": ctx.settings.model_name, "model_key_configured": ctx.keys.status().configured}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    ctx = ctx_of(request)
    ctx.limiter.hit(f"login:{client_ip(request)}", ctx.settings.login_per_ip_per_min)
    ctx.limiter.hit(f"login-user:{body.username.lower()}", ctx.settings.login_per_user_per_min)  # many IPs, one account
    token = auth.login(ctx.db, body.username, body.password, ctx.settings.session_ttl_hours)
    response.set_cookie(
        auth.SESSION_COOKIE, token, httponly=True, samesite="lax", secure=ctx.settings.cookie_secure,
        max_age=ctx.settings.session_ttl_hours * 3600, path="/",
    )
    user = auth.user_for_token(ctx.db, token)
    return {"user": {"username": user.username, "role": user.role}}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    auth.logout(ctx_of(request).db, request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(user: auth.User = Depends(current_user)) -> dict[str, Any]:
    return {"user": {"username": user.username, "role": user.role}}


@router.get("/settings/key")
def key_status(request: Request, _: auth.User = Depends(current_user)) -> dict[str, object]:
    return ctx_of(request).keys.status().to_dict()


@router.put("/settings/key")
def save_key(body: KeyIn, request: Request, _: auth.User = Depends(admin_user)) -> dict[str, object]:
    return ctx_of(request).keys.save(body.api_key).to_dict()


@router.delete("/settings/key")
def clear_key(request: Request, _: auth.User = Depends(admin_user)) -> dict[str, object]:
    return ctx_of(request).keys.clear().to_dict()


@router.get("/settings")
def settings_view(request: Request, user: auth.User = Depends(current_user)) -> dict[str, Any]:
    ctx = ctx_of(request)
    s = ctx.settings
    return {
        "user": {"username": user.username, "role": user.role},
        "model": s.model_name,
        "key": ctx.keys.status().to_dict(),
        "quota": {"window_hours": quota.WINDOW_HOURS, "buckets": [
            {"name": b.name, "used": quota.used(ctx.db, user.id, b.key), "limit": b.limit, "resets_at": b.resets_at}
            for b in quota.plan(s, heavy=bool(s.heavy_models))
        ]},
        "rate_limit": {"user_per_min": s.rate_limit_user_per_min, "ip_per_min": s.rate_limit_ip_per_min,
                       "user_remaining": ctx.limiter.remaining(f"user:{user.id}", s.rate_limit_user_per_min)},
        "limits": {"max_input_chars": s.max_input_chars, "max_output_tokens": s.max_output_tokens},
    }


@router.get("/models")
async def models(request: Request, _: auth.User = Depends(current_user)) -> dict[str, Any]:
    """Models the configured server really has, so the UI never shows a made-up list."""
    ctx = ctx_of(request)
    names = await list_models(ctx.http, ctx.settings, ctx.keys.get())
    return {"current": ctx.settings.model_name, "available": names}


def _oauth_client(ctx: Context, provider: str) -> tuple[oauth.Provider, str, str]:
    """The provider and its credentials, or a 404 when the provider is unknown or not configured."""
    spec = oauth.PROVIDERS.get(provider)
    pair = ctx.settings.oauth_client(provider) if spec else None
    if spec is None or pair is None:
        raise AppError("validation", "ยังไม่ได้เปิดใช้การเข้าสู่ระบบด้วยผู้ให้บริการนี้", http_status=404)
    return spec, pair[0], pair[1]


@router.get("/auth/oauth/providers")
def oauth_providers(request: Request) -> dict[str, Any]:
    """Only the providers that have credentials configured. Never returns the secrets."""
    ctx = ctx_of(request)
    return {"providers": [name for name in oauth.PROVIDERS if ctx.settings.oauth_client(name)]}


@router.get("/auth/oauth/{provider}/start")
def oauth_start(provider: str, request: Request, link: str = "") -> RedirectResponse:
    ctx = ctx_of(request)
    spec, client_id, _ = _oauth_client(ctx, provider)
    linking = link == "1"
    if linking:  # only a signed-in user can link a provider; send anyone else to the login page
        try:
            auth.user_for_token(ctx.db, request.cookies.get(auth.SESSION_COOKIE))
        except AppError:
            return RedirectResponse("/#/login?error=session", status_code=302)
    state = oauth.new_state()
    target = oauth.authorize_url(spec, client_id, oauth.redirect_uri(ctx.settings.public_base_url, provider), state)
    response = RedirectResponse(target, status_code=302)
    response.set_cookie(
        oauth.STATE_COOKIE, state, httponly=True, samesite="lax", secure=ctx.settings.cookie_secure,
        max_age=600, path=oauth.STATE_COOKIE_PATH,
    )
    if linking:
        response.set_cookie(oauth.LINK_COOKIE, "1", httponly=True, samesite="lax",
                            secure=ctx.settings.cookie_secure, max_age=600, path=oauth.STATE_COOKIE_PATH)
    else:  # a link attempt that was abandoned must not turn the next normal sign-in into a link
        response.delete_cookie(oauth.LINK_COOKIE, path=oauth.STATE_COOKIE_PATH)
    return response


@router.get("/auth/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request, code: str = "", state: str = "") -> RedirectResponse:
    """Finish the sign-in. Any failure sends the browser back to the login page with a flag, not an API error."""
    ctx = ctx_of(request)
    s = ctx.settings
    linking = request.cookies.get(oauth.LINK_COOKIE) == "1"
    token = None
    try:
        spec, client_id, client_secret = _oauth_client(ctx, provider)
        if not code or not oauth.states_match(request.cookies.get(oauth.STATE_COOKIE), state):
            raise AppError("auth", "คำขอเข้าสู่ระบบไม่ถูกต้องหรือหมดอายุ")
        subject, display = await oauth.fetch_profile(
            ctx.http, spec, client_id, client_secret, code, oauth.redirect_uri(s.public_base_url, provider),
        )
        if linking:
            me = auth.user_for_token(ctx.db, request.cookies.get(auth.SESSION_COOKIE))
            auth.link_oauth(ctx.db, me.id, provider, subject)
        else:
            token = auth.login_oauth(ctx.db, provider, subject, display, s.session_ttl_hours)
    except AppError as exc:
        log_event("oauth", ctx.log_stream, request_id=request.state.request_id, provider=provider,
                  status="failed", error_type=exc.type, linking=linking)
        if linking:  # the reason is shown on the Settings page, so the user can act on it
            response = RedirectResponse("/#/settings?link=error&msg=" + quote(exc.user_message), status_code=302)
        else:
            response = RedirectResponse("/#/login?error=oauth", status_code=302)
    else:
        if linking:
            response = RedirectResponse(f"/#/settings?linked={provider}", status_code=302)
        else:
            response = RedirectResponse("/#/", status_code=302)
            response.set_cookie(
                auth.SESSION_COOKIE, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                max_age=s.session_ttl_hours * 3600, path="/",
            )
    response.delete_cookie(oauth.STATE_COOKIE, path=oauth.STATE_COOKIE_PATH)
    response.delete_cookie(oauth.LINK_COOKIE, path=oauth.STATE_COOKIE_PATH)
    return response


class DeleteAccountIn(BaseModel):
    confirm: str = Field(max_length=120)


@router.get("/account")
def account(request: Request, user: auth.User = Depends(current_user)) -> dict[str, Any]:
    ctx = ctx_of(request)
    return {
        "username": user.username,
        "role": user.role,
        "password": auth.has_password(ctx.db, user.id),
        "providers": auth.linked_providers(ctx.db, user.id),
        "available_providers": [name for name in oauth.PROVIDERS if ctx.settings.oauth_client(name)],
    }


@router.post("/account/unlink/{provider}")
def unlink_provider(provider: str, request: Request, user: auth.User = Depends(current_user)) -> dict[str, Any]:
    ctx = ctx_of(request)
    auth.unlink_oauth(ctx.db, user.id, provider)
    return {"providers": auth.linked_providers(ctx.db, user.id)}


@router.delete("/account")
def delete_account(body: DeleteAccountIn, request: Request, response: Response,
                   user: auth.User = Depends(current_user)) -> dict[str, bool]:
    """Permanently delete the signed-in account. The user must type the username to confirm."""
    if body.confirm != user.username:
        raise AppError("validation", "พิมพ์ชื่อผู้ใช้ให้ตรงทุกตัวอักษรเพื่อยืนยันการลบบัญชี")
    ctx = ctx_of(request)
    auth.delete_user(ctx.db, user.id)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"deleted": True}


@router.get("/history")
def history_list(
    request: Request,
    q: str = Query("", max_length=200),
    status: str = Query("", pattern=r"^(|ok|partial|error)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: auth.User = Depends(current_user),
) -> dict[str, Any]:
    return history.list_runs(ctx_of(request).db, user.id, q=q, status=status, limit=limit, offset=offset)


@router.get("/history/{run_id}")
def history_get(run_id: str, request: Request, user: auth.User = Depends(current_user)) -> dict[str, Any]:
    run = history.get(ctx_of(request).db, user.id, run_id)
    if run is None:
        raise AppError("validation", NOT_FOUND, http_status=404)
    return run


@router.delete("/history/{run_id}")
def history_delete(run_id: str, request: Request, user: auth.User = Depends(current_user)) -> dict[str, bool]:
    if not history.delete(ctx_of(request).db, user.id, run_id):
        raise AppError("validation", NOT_FOUND, http_status=404)
    return {"ok": True}


async def _check_model(ctx: Context, requested: str | None, api_key: str) -> str:
    """Use the requested model only when the server really lists it; otherwise the configured one."""
    if not requested or requested == ctx.settings.model_name:
        return ctx.settings.model_name
    if requested not in await list_models(ctx.http, ctx.settings, api_key):
        raise AppError("validation", "ไม่พบโมเดลนี้บนเซิร์ฟเวอร์ — เลือกใหม่จากรายการ")
    return requested


@router.post("/run")
async def run(body: RunIn, request: Request, user: auth.User = Depends(current_user)) -> StreamingResponse:
    ctx = ctx_of(request)
    s = ctx.settings
    if len(body.prompt) > s.max_input_chars:
        raise AppError("validation", f"ข้อความยาวเกิน {s.max_input_chars} ตัวอักษร — ย่อให้สั้นลง")
    if body.max_output_tokens is not None and body.max_output_tokens > s.max_output_tokens:
        raise AppError("validation", f"ความยาวคำตอบสูงสุดคือ {s.max_output_tokens} token")
    cap = body.max_output_tokens or s.max_output_tokens
    ctx.limiter.hit(f"user:{user.id}", s.rate_limit_user_per_min)
    api_key = ctx.keys.get()
    require_key(api_key, s.model_base_url)
    model = await _check_model(ctx, body.model, api_key)
    buckets = quota.plan(s, heavy=model in s.heavy_models)
    quota.check_all(ctx.db, user.id, buckets, need=estimate_tokens(body.prompt) + cap)
    started = time.perf_counter()
    run_id = history.start(ctx.db, user.id, model, body.prompt)
    try:
        upstream = await open_stream(ctx.http, s, api_key, body.prompt, model=model, max_tokens=cap)
    except Exception as exc:
        err = from_exception(exc)
        _finish(ctx, run_id, user.id, StreamResult(), body.prompt, err, started, request.state.request_id, buckets)
        raise err from exc
    stream = _relay(ctx, run_id, user.id, upstream, body.prompt, started, request.state.request_id, cap, buckets)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _relay(ctx: Context, run_id: str, user_id: int, upstream: httpx.Response, prompt: str,
                 started: float, request_id: str, max_tokens: int, buckets: list[quota.Bucket]) -> AsyncIterator[str]:
    """Forward deltas as SSE. On a mid-stream failure keep what arrived and report a retryable error."""
    result = StreamResult()
    err: AppError | None = None
    completed = False
    budget_s = max(1.0, ctx.settings.model_timeout_s - (time.perf_counter() - started))
    yield _sse("start", {"run_id": run_id})
    try:
        async with asyncio.timeout(budget_s):  # total time for the whole answer, not just per chunk
            async for delta in iter_text(upstream, result, max_tokens * 8):
                yield _sse("delta", {"text": delta})
        completed = True
    except Exception as exc:  # network drop, timeout or a bad chunk after streaming began
        err = from_exception(exc)
        yield _sse("error", {**err.to_dict(request_id), "partial": bool(result.text)})
    finally:
        if not completed and err is None:  # the browser went away before the end
            err = AppError("unknown", "การเชื่อมต่อถูกปิดก่อนได้คำตอบครบ")
        usage = _finish(ctx, run_id, user_id, result, prompt, err, started, request_id, buckets)
    if err is None:
        yield _sse("done", {"run_id": run_id, "truncated": result.truncated, **usage})


def _finish(ctx: Context, run_id: str, user_id: int, result: StreamResult, prompt: str,
            err: AppError | None, started: float, request_id: str, buckets: list[quota.Bucket]) -> dict[str, int]:
    """Record history, quota and a JSON log line for one run. Returns the token usage."""
    tokens_in = result.tokens_in or estimate_tokens(prompt)
    tokens_out = result.tokens_out or estimate_tokens(result.text)
    if err is None:
        status = "partial" if result.truncated else "ok"  # cut at the output cap: keep it, but say so
    else:
        status = "partial" if result.text else "error"
    latency_ms = int((time.perf_counter() - started) * 1000)
    history.finish(ctx.db, run_id, status=status, output=result.text, error_type=err.type if err else None,
                   tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms)
    if status != "error":
        quota.record_all(ctx.db, user_id, buckets, tokens_in + tokens_out)
    cost = estimate_cost(tokens_in + tokens_out, ctx.settings.cost_per_1k_tokens)
    log_event("run", ctx.log_stream, request_id=request_id, run_id=run_id, user_id=user_id, status=status,
              error_type=err.type if err else None, latency_ms=latency_ms, tokens_in=tokens_in,
              tokens_out=tokens_out, cost_estimate=cost)
    return {"tokens_in": tokens_in, "tokens_out": tokens_out, "latency_ms": latency_ms}


# ---------- app wiring ----------

def client_ip(request: Request) -> str:
    """The rate-limit identity of the caller. See clientip.py for when forwarded headers count."""
    peer = request.client.host if request.client else None
    return resolve_client_ip(peer, request.headers, request.app.state.trusted_nets)


def _check_request(request: Request, ctx: Context) -> None:
    """Body size, Origin for state-changing calls, and the per-IP rate limit."""
    if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
        raise AppError("validation", "ข้อมูลที่ส่งมามีขนาดใหญ่เกินไป", http_status=413)
    if "content-length" not in request.headers and "transfer-encoding" in request.headers:
        # A chunked body has no size up front; browsers always send Content-Length for these calls.
        raise AppError("validation", "ต้องระบุขนาดข้อมูล (Content-Length)", http_status=411)
    origin = request.headers.get("origin")
    same = f"{request.url.scheme}://{request.url.netloc}"
    if request.method in _UNSAFE and origin and origin not in ctx.settings.cors_origins and origin != same:
        raise AppError("auth", "คำขอนี้มาจากโดเมนที่ไม่ได้รับอนุญาต")
    if request.url.path != "/api/health":
        ctx.limiter.hit(f"ip:{client_ip(request)}", ctx.settings.rate_limit_ip_per_min)


def _install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def observe(request: Request, call_next):  # type: ignore[no-untyped-def]
        ctx: Context = app.state.ctx
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if _REQUEST_ID.match(incoming) else secrets.token_hex(8)
        started = time.perf_counter()
        try:
            _check_request(request, ctx)
            response = await call_next(request)
        except AppError as err:
            response = error_response(err, request)
        except OSError:  # the browser closed the connection; nothing left to send
            request.state.error_type = "client_disconnect"
            response = Response(status_code=499)
        except Exception as exc:  # unexpected: answer here so the request id, CORS and access log still apply
            log_event("unhandled", ctx.log_stream, request_id=request.state.request_id, exception=type(exc).__name__)
            response = error_response(AppError("unknown"), request)
        response.headers["X-Request-ID"] = request.state.request_id
        log_event("http", ctx.log_stream, request_id=request.state.request_id, method=request.method,
                  path=request.url.path, status=response.status_code,
                  latency_ms=int((time.perf_counter() - started) * 1000),
                  user_id=getattr(request.state, "user_id", None),
                  error_type=getattr(request.state, "error_type", None))
        return response


def _install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def on_app_error(request: Request, err: AppError) -> JSONResponse:
        return error_response(err, request)

    @app.exception_handler(RequestValidationError)
    async def on_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        if any(e.get("type") == "json_invalid" for e in errors):
            return error_response(AppError("validation", "รูปแบบ JSON ไม่ถูกต้อง"), request)
        fields = sorted({str(loc) for e in errors for loc in e.get("loc", ())[-1:] if isinstance(loc, str)})
        message = f"ข้อมูลไม่ถูกต้องในช่อง: {', '.join(fields)}" if fields else ""
        return error_response(AppError("validation", message), request)

    @app.exception_handler(Exception)
    async def on_unknown(request: Request, exc: Exception) -> JSONResponse:
        log_event("unhandled", app.state.ctx.log_stream, request_id=getattr(request.state, "request_id", ""),
                  exception=type(exc).__name__)
        return error_response(AppError("unknown"), request)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None,
               log_stream: TextIO | None = None) -> FastAPI:
    """Build the app. Tests pass `transport` to fake the model and `log_stream` to read logs."""
    s = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        timeout = httpx.Timeout(s.model_timeout_s, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            app.state.ctx = Context(s, Database(s.data_dir / "app.db"), KeyStore(s.model_api_key, s.data_dir),
                                    RateLimiter(), client, log_stream)
            yield

    app = FastAPI(title="backend-frontend API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.trusted_nets = parse_networks(s.trusted_proxies)
    app.include_router(router)
    _install_handlers(app)
    _install_middleware(app)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", "X-Request-ID"])
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """`uvicorn app.main:app` builds the app on first access (once), so importing has no side effects."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
