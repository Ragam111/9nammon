"""Chat conversations with three providers (claude, gemini, gpt), all over OpenAI-compatible streaming.

Routes sit under /api/chat and need a signed-in user. Every query filters by the owning user id.
Provider keys come only from environment variables (config.py). They are never stored, returned or logged.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import auth, quota
from .config import Settings
from .db import Database
from .errors import AppError, from_exception, is_retryable_exception
from .local_provider import DEFAULT_LOCAL_CATALOG, ModelInfo, ModelStatus, OllamaLocalProvider, installed_flag
from .logging_json import estimate_cost, log_event
from .model_client import StreamResult, estimate_tokens, iter_text
from .retry import with_retry

if TYPE_CHECKING:
    from .main import Context

NOT_FOUND = "ไม่พบการสนทนานี้ หรืออาจถูกลบไปแล้ว"
DEFAULT_TITLE = "สนทนาใหม่"
LIST_LIMIT = 200
HISTORY_LIMIT = 200  # newest messages loaded to build the model context; build_context trims further by characters
TITLE_FROM_MESSAGE_CHARS = 60
ANTHROPIC_VERSION = "2023-06-01"
_MODEL_ID = r"^[A-Za-z0-9._:/-]+$"

router = APIRouter(prefix="/api/chat")


# ---------- request bodies ----------

class ConversationIn(BaseModel):
    model: str = Field(min_length=1, max_length=120, pattern=_MODEL_ID)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class MessageIn(BaseModel):
    # No max_length here: the length check runs in the route so an over-long message gets a 400 with a Thai message.
    content: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1, max_length=120, pattern=_MODEL_ID)


# ---------- providers and model catalog ----------

@dataclass(frozen=True)
class Provider:
    name: str  # the name the API exposes: "claude", "gemini" or "gpt"
    base_url: str
    api_key: str = field(repr=False)
    models: tuple[str, ...]


@dataclass(frozen=True)
class ModelRef:
    id: str
    provider: Provider

    @property
    def configured(self) -> bool:
        return bool(self.provider.api_key)


def providers(s: Settings) -> list[Provider]:
    return [
        Provider("claude", s.chat_anthropic_base_url, s.chat_anthropic_api_key, tuple(s.chat_anthropic_models)),
        Provider("gemini", s.chat_gemini_base_url, s.chat_gemini_api_key, tuple(s.chat_gemini_models)),
        Provider("gpt", s.chat_openai_base_url, s.chat_openai_api_key, tuple(s.chat_openai_models)),
    ]


def catalog(s: Settings) -> list[ModelRef]:
    """Each model id once, in provider order. If two providers list the same id, a configured one wins."""
    chosen: dict[str, ModelRef] = {}
    for provider in providers(s):
        for model_id in provider.models:
            ref = ModelRef(model_id, provider)
            current = chosen.get(model_id)
            if current is None or (ref.configured and not current.configured):
                chosen[model_id] = ref
    return list(chosen.values())


def find_model(s: Settings, model_id: str) -> ModelRef:
    """The model for an id. Raises 400 when the id is unknown or its provider has no key."""
    ref = next((r for r in catalog(s) if r.id == model_id), None)
    if ref is None:
        raise AppError("validation", "ไม่พบโมเดลนี้ในรายการ — เลือกใหม่จากรายการ", http_status=400)
    if not ref.configured:
        raise AppError("validation", "ยังไม่ได้ตั้งค่า API key ของผู้ให้บริการนี้", http_status=400)
    return ref


# ---------- local models (Ollama on 127.0.0.1) ----------

LOCAL_PROVIDER_NAME = "ollama_local"  # the name written to logs for a local turn
LOCAL_API_PROVIDER = "ollama"  # the provider field of a local row in GET /api/chat/models
_LOCAL_SPECS = {spec.id: spec for spec in DEFAULT_LOCAL_CATALOG}
NOT_READY_MESSAGES: dict[ModelStatus, str] = {
    ModelStatus.NOT_INSTALLED: "ยังไม่ได้ติดตั้งโมเดลนี้ในเครื่อง — ติดตั้งด้วยคำสั่ง ollama pull {id}",
    ModelStatus.NOT_ENOUGH_MEMORY: "RAM ว่างไม่พอสำหรับโมเดลนี้ — ปิดโปรแกรมอื่นแล้วลองใหม่ หรือเลือกโมเดลอื่น",
    ModelStatus.UNREACHABLE: "ติดต่อ Ollama ในเครื่องไม่ได้ — ตรวจว่า Ollama ทำงานอยู่",
    ModelStatus.NOT_CONFIGURED: "ยังไม่ได้เปิดใช้โมเดลในเครื่อง",
}


async def local_info(ctx: Context, model_id: str) -> ModelInfo:
    """The current status of one local catalog model. Never raises when Ollama is down; that is UNREACHABLE."""
    spec = _LOCAL_SPECS[model_id]
    if ctx.local is None:
        return ModelInfo(spec.id, spec.label, ModelStatus.UNREACHABLE)
    infos = await ctx.local.list_models()
    return next((i for i in infos if i.id == model_id), ModelInfo(spec.id, spec.label, ModelStatus.NOT_CONFIGURED))


async def resolve_model(ctx: Context, model_id: str) -> tuple[ModelRef | None, ModelInfo | None]:
    """(cloud ref, None) for a cloud id, or (None, info) for a local catalog id.

    A local id is usable only when its status is READY. Anything else raises a 400 before any row is written.
    Only ids in the local catalog are local: raw tag names reported by Ollama are never routed.
    """
    if model_id in _LOCAL_SPECS:
        info = await local_info(ctx, model_id)
        if info.status is not ModelStatus.READY:
            raise AppError("validation", NOT_READY_MESSAGES[info.status].format(id=info.id), http_status=400)
        return None, info
    return find_model(ctx.settings, model_id), None


def _headers(provider: Provider) -> dict[str, str]:
    if provider.name == "claude":  # Anthropic's native auth header, sent with its API version
        return {"x-api-key": provider.api_key, "anthropic-version": ANTHROPIC_VERSION}
    return {"Authorization": f"Bearer {provider.api_key}"}


async def _open_stream(ctx: Context, ref: ModelRef, messages: list[dict[str, str]],
                       max_tokens: int) -> httpx.Response:
    """Open the upstream stream. Transient failures are retried, but only before the first byte arrives."""
    s = ctx.settings
    url = f"{ref.provider.base_url}/chat/completions"
    payload = {
        "model": ref.id,
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
        "stream_options": {"include_usage": True},
    }

    async def attempt() -> httpx.Response:
        request = ctx.http.build_request("POST", url, json=payload, headers=_headers(ref.provider))
        response = await ctx.http.send(request, stream=True)
        if not 200 <= response.status_code < 300:
            await response.aclose()
            raise httpx.HTTPStatusError("upstream error", request=request, response=response)
        if response.headers.get("content-type", "").startswith("application/json"):
            await response.aclose()  # a JSON body on a streaming request is an error object, not a stream
            raise AppError("upstream", "บริการโมเดลตอบกลับในรูปแบบที่ไม่ใช่ stream — ตรวจการตั้งค่าผู้ให้บริการ")
        return response

    return await with_retry(attempt, max_retries=s.model_max_retries, base_delay_s=s.retry_base_delay_s,
                            is_retryable=is_retryable_exception)


def build_context(history: list[dict[str, str]], content: str, limit: int) -> list[dict[str, str]]:
    """The most recent turns that fit `limit` characters together with the new message, oldest first.

    The client never supplies a system prompt, and none is added here.
    """
    budget = limit - len(content)
    kept: list[dict[str, str]] = []
    for turn in reversed(history):
        if len(turn["content"]) > budget:
            break
        budget -= len(turn["content"])
        kept.append({"role": turn["role"], "content": turn["content"]})
    kept.reverse()
    while kept and kept[0]["role"] != "user":  # a provider expects the conversation to open with a user turn
        kept.pop(0)
    kept.append({"role": "user", "content": content})
    return kept


# ---------- storage (every statement is parameterised and filtered by user_id) ----------

def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _auto_title(content: str) -> str:
    first_line = content.strip().splitlines()[0]
    return first_line[:TITLE_FROM_MESSAGE_CHARS] or DEFAULT_TITLE


def create_conversation(db: Database, user_id: int, model_id: str) -> dict[str, Any]:
    conv_id, now = _new_id("conv"), _now()
    with db.session() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, user_id, DEFAULT_TITLE, model_id, now, now),
        )
    return {"id": conv_id, "title": DEFAULT_TITLE, "model": model_id, "updated_at": now}


def list_conversations(db: Database, user_id: int) -> list[dict[str, Any]]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT id, title, model, updated_at FROM conversations WHERE user_id = ? "
            "ORDER BY updated_at DESC, rowid DESC LIMIT ?",
            (user_id, LIST_LIMIT),
        ).fetchall()
    return [dict(row) for row in rows]


def get_conversation(db: Database, user_id: int, conv_id: str) -> dict[str, Any] | None:
    with db.session() as conn:
        row = conn.execute(
            "SELECT id, title, model, updated_at FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def list_messages(db: Database, user_id: int, conv_id: str) -> list[dict[str, Any]]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT id, role, content, status, created_at FROM chat_messages "
            "WHERE conversation_id = ? AND user_id = ? ORDER BY created_at, rowid",
            (conv_id, user_id),
        ).fetchall()
    return [dict(row) for row in rows]


def recent_messages(db: Database, user_id: int, conv_id: str, limit: int) -> list[dict[str, Any]]:
    """The newest `limit` messages, oldest first. Used for the model context so a long chat is not fully loaded."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT id, role, content, status, created_at FROM chat_messages "
            "WHERE conversation_id = ? AND user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (conv_id, user_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def rename_conversation(db: Database, user_id: int, conv_id: str, title: str) -> bool:
    with db.session() as conn:
        cur = conn.execute("UPDATE conversations SET title = ? WHERE id = ? AND user_id = ?",
                           (title, conv_id, user_id))
    return cur.rowcount > 0


def delete_conversation(db: Database, user_id: int, conv_id: str) -> bool:
    with db.session() as conn:
        conn.execute("DELETE FROM chat_messages WHERE conversation_id = ? AND user_id = ?", (conv_id, user_id))
        cur = conn.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id))
    return cur.rowcount > 0


def start_turn(db: Database, user_id: int, conv_id: str, content: str, model_id: str, first_turn: bool) -> None:
    """Store the user's message before the upstream call, and move the conversation to the model in use."""
    now = _now()
    title = _auto_title(content) if first_turn else None
    with db.session() as conn:
        conn.execute(
            "INSERT INTO chat_messages (id, conversation_id, user_id, role, content, status, created_at) "
            "VALUES (?, ?, ?, 'user', ?, 'complete', ?)",
            (_new_id("msg"), conv_id, user_id, content, now),
        )
        conn.execute(
            "UPDATE conversations SET model = ?, updated_at = ?, title = COALESCE(?, title) "
            "WHERE id = ? AND user_id = ?",
            (model_id, now, title, conv_id, user_id),
        )


def finish_turn(db: Database, user_id: int, conv_id: str, message_id: str, text: str, status: str) -> bool:
    """Store the answer. Returns False, and writes nothing, when the conversation was deleted mid-answer."""
    now = _now()
    with db.session() as conn:
        cur = conn.execute(
            "INSERT INTO chat_messages (id, conversation_id, user_id, role, content, status, created_at) "
            "SELECT ?, id, user_id, 'assistant', ?, ?, ? FROM conversations WHERE id = ? AND user_id = ?",
            (message_id, text, status, now, conv_id, user_id),
        )
        if cur.rowcount == 0:
            return False
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?", (now, conv_id, user_id))
    return True


# ---------- HTTP helpers ----------

def _ctx(request: Request) -> Context:
    return request.app.state.ctx


def _current_user(request: Request) -> auth.User:
    """Same rule as main.current_user (copied to avoid importing main, which imports this module)."""
    user = auth.user_for_token(_ctx(request).db, request.cookies.get(auth.SESSION_COOKIE))
    request.state.user_id = user.id
    return user


def _not_found() -> AppError:
    return AppError("validation", NOT_FOUND, http_status=404)


def _owned(db: Database, user_id: int, conv_id: str) -> dict[str, Any]:
    conv = get_conversation(db, user_id, conv_id)
    if conv is None:
        raise _not_found()
    return conv


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------- routes ----------

@router.get("/models")
async def list_models(request: Request, _: auth.User = Depends(_current_user)) -> dict[str, Any]:
    """Cloud rows (key status only, keys are never shown) and local catalog rows (status from Ollama).

    Each row has the same six keys. required_ram_gb and available_ram_gb are additive and None when unknown.
    No base URL is ever returned.
    """
    ctx = _ctx(request)
    cloud_rows = [
        {
            "id": r.id,
            "provider": r.provider.name,
            "label": r.id,
            "configured": r.configured,
            "provider_kind": "cloud",
            "status": (ModelStatus.READY if r.configured else ModelStatus.NOT_CONFIGURED).value,
            "required_ram_gb": None,
            "available_ram_gb": None,
        }
        for r in catalog(ctx.settings)
    ]
    return {"models": cloud_rows + await _local_rows(ctx)}


async def _local_rows(ctx: Context) -> list[dict[str, Any]]:
    local: OllamaLocalProvider | None = ctx.local
    infos = (await local.list_models()) if local is not None else [
        ModelInfo(spec.id, spec.label, ModelStatus.UNREACHABLE) for spec in DEFAULT_LOCAL_CATALOG
    ]
    available = local.free_ram_gb() if local is not None else None
    rows: list[dict[str, Any]] = []
    for info in infos:
        spec = _LOCAL_SPECS.get(info.id)
        rows.append({
            "id": info.id,
            "provider": LOCAL_API_PROVIDER,
            "label": info.label,
            "configured": info.status is ModelStatus.READY,
            "provider_kind": "local",
            "status": info.status.value,
            "required_ram_gb": spec.required_ram_gb if spec else None,
            "available_ram_gb": available,
        })
    return rows


def _health_payload(reachable: bool, names: list[str], available_ram: float | None) -> dict[str, Any]:
    """Health body: the P1 keys plus RAM and one detail row per catalog model. Read-only; no decision is made here."""
    detail = [
        {"id": spec.id, "installed": installed_flag(spec.id, names), "required_ram_gb": spec.required_ram_gb}
        for spec in DEFAULT_LOCAL_CATALOG
    ]
    return {
        "reachable": reachable,
        "models": names,
        "available_ram_gb": available_ram,
        "models_detail": detail,
    }


@router.get("/local/health")
async def local_health(request: Request, _: auth.User = Depends(_current_user)) -> dict[str, Any]:
    """Whether the local Ollama answers, which models it has, and the RAM it reports. Takes no address."""
    ctx = _ctx(request)
    if ctx.local is None:
        return _health_payload(False, [], None)
    reachable, names = await ctx.local.installed_models()
    return _health_payload(reachable, names, ctx.local.free_ram_gb())


@router.get("/conversations")
def conversations(request: Request, user: auth.User = Depends(_current_user)) -> dict[str, Any]:
    return {"conversations": list_conversations(_ctx(request).db, user.id)}


@router.post("/conversations", status_code=201)
async def create(body: ConversationIn, request: Request, user: auth.User = Depends(_current_user)) -> dict[str, Any]:
    ctx = _ctx(request)
    await resolve_model(ctx, body.model)  # raises 400 for an unknown, unconfigured or not-ready model
    return create_conversation(ctx.db, user.id, body.model)


@router.get("/conversations/{conv_id}")
def conversation(conv_id: str, request: Request, user: auth.User = Depends(_current_user)) -> dict[str, Any]:
    db = _ctx(request).db
    conv = _owned(db, user.id, conv_id)
    return {**conv, "messages": list_messages(db, user.id, conv_id)}


@router.patch("/conversations/{conv_id}")
def rename(conv_id: str, body: RenameIn, request: Request, user: auth.User = Depends(_current_user)) -> dict[str, Any]:
    title = body.title.strip()
    if not title:
        raise AppError("validation", "ชื่อการสนทนาต้องไม่ว่าง", http_status=400)
    if not rename_conversation(_ctx(request).db, user.id, conv_id, title):
        raise _not_found()
    return {"id": conv_id, "title": title}


@router.delete("/conversations/{conv_id}", status_code=204)
def delete(conv_id: str, request: Request, user: auth.User = Depends(_current_user)) -> Response:
    if not delete_conversation(_ctx(request).db, user.id, conv_id):
        raise _not_found()
    return Response(status_code=204)


@router.post("/conversations/{conv_id}/messages")
async def send(conv_id: str, body: MessageIn, request: Request,
               user: auth.User = Depends(_current_user)) -> StreamingResponse:
    ctx = _ctx(request)
    s = ctx.settings
    started = time.perf_counter()
    conv = _owned(ctx.db, user.id, conv_id)
    content = body.content
    if not content.strip():
        raise AppError("validation", "ข้อความว่างเปล่า", http_status=400)
    if len(content) > s.max_input_chars:
        raise AppError("validation", f"ข้อความยาวเกิน {s.max_input_chars} ตัวอักษร — ย่อให้สั้นลง", http_status=400)
    ctx.limiter.hit(f"user:{user.id}", s.rate_limit_user_per_min)  # same budget as /api/run, local or cloud
    model_id = body.model or conv["model"]
    ref, _ = await resolve_model(ctx, model_id)  # a local id must be ready here, before any row is written
    cap = s.max_output_tokens
    history = recent_messages(ctx.db, user.id, conv_id, HISTORY_LIMIT)
    context = build_context([{"role": m["role"], "content": m["content"]} for m in history], content,
                            s.max_input_chars)
    if ref is None:
        return _send_local(ctx, request, user.id, conv_id, model_id, context, content, history, started, cap)
    buckets = quota.plan(s, heavy=ref.id in s.heavy_models)
    need = estimate_tokens(_joined(context)) + cap
    # Check and hold in one synchronous step: no await runs between them, so a concurrent send sees the hold.
    quota.check_all(ctx.db, user.id, buckets, need=need)
    quota.reserve_all(ctx.db, user.id, buckets, need)
    try:
        start_turn(ctx.db, user.id, conv_id, content, ref.id, first_turn=not history)
    except BaseException:  # nothing was sent upstream: give the whole hold back before failing
        quota.settle_all(ctx.db, user.id, buckets, reserved=need, charged=0)
        raise
    message_id = _new_id("msg")
    try:
        upstream = await _open_stream(ctx, ref, context, cap)
    except BaseException as exc:  # no answer was produced: give the hold back, even if the request was cancelled
        quota.settle_all(ctx.db, user.id, buckets, reserved=need, charged=0)
        if not isinstance(exc, Exception):
            raise
        err = from_exception(exc)
        _log_turn(ctx, user.id, conv_id, ref.provider.name, ref.id, request.state.request_id, started, "error", err)
        raise err from exc
    result = StreamResult()
    stream = _relay(ctx, user.id, conv_id, ref.provider.name, ref.id, iter_text(upstream, result, cap * 8), result,
                    upstream.aclose, _joined(context), started, request.state.request_id, buckets, message_id, need)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _send_local(ctx: Context, request: Request, user_id: int, conv_id: str, model_id: str,
                context: list[dict[str, str]], content: str, history: list[dict[str, Any]], started: float,
                cap: int) -> StreamingResponse:
    """A turn on a local model: no cloud quota bucket, no cloud key, and the base URL is the provider's fixed one.

    The Ollama provider yields text deltas, so they are recorded here to keep a partial answer for _settle.
    """
    local = ctx.local
    if local is None:  # resolve_model only lets a READY model through, and READY needs a provider
        raise AppError("validation", NOT_READY_MESSAGES[ModelStatus.UNREACHABLE], http_status=400)
    buckets = quota.plan_local(ctx.settings)
    need = estimate_tokens(_joined(context)) + cap
    # Local runs have their own buckets; they never touch the cloud ones. Check and hold in one synchronous step.
    quota.check_all(ctx.db, user_id, buckets, need=need)
    quota.reserve_all(ctx.db, user_id, buckets, need)
    try:
        start_turn(ctx.db, user_id, conv_id, content, model_id, first_turn=not history)
    except BaseException:  # nothing was sent to Ollama: give the whole hold back before failing
        quota.settle_all(ctx.db, user_id, buckets, reserved=need, charged=0)
        raise
    message_id = _new_id("msg")
    result = StreamResult()
    deltas = _record_text(local.stream(context, model_id, cap), result)
    stream = _relay(ctx, user_id, conv_id, LOCAL_PROVIDER_NAME, model_id, deltas, result, _noop, _joined(context),
                    started, request.state.request_id, buckets, message_id, need)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _record_text(deltas: AsyncIterator[str], result: StreamResult) -> AsyncIterator[str]:
    """Pass deltas through and keep their text in `result`, so a partial local answer can be stored."""
    try:
        async for delta in deltas:
            result.text_parts.append(delta)
            yield delta
    finally:
        await deltas.aclose()


async def _noop() -> None:
    """Nothing to close: a local turn has no upstream response object of its own."""


def _joined(context: list[dict[str, str]]) -> str:
    return "".join(turn["content"] for turn in context)


async def _relay(ctx: Context, user_id: int, conv_id: str, provider: str, model_id: str,
                 deltas: AsyncIterator[str], result: StreamResult, closer: Callable[[], Awaitable[None]],
                 context_text: str, started: float, request_id: str, buckets: list[quota.Bucket],
                 message_id: str, reserved: int) -> AsyncIterator[str]:
    """Forward deltas as SSE, then store the answer. Keeps partial text when the stream fails part way.

    The start event is inside the try, so a client that leaves at any yield still reaches _settle.
    `closer` closes the upstream response (cloud) or does nothing (local), in the finally.
    """
    err: AppError | None = None
    completed = False
    budget_s = max(1.0, ctx.settings.model_timeout_s - (time.perf_counter() - started))
    try:
        yield _sse("start", {"message_id": message_id})
        async with asyncio.timeout(budget_s):  # total time for the whole answer, not just per chunk
            async for delta in deltas:
                yield _sse("delta", {"text": delta})
        completed = True
    except Exception as exc:  # network drop, timeout or a bad chunk after streaming began
        err = from_exception(exc)
    finally:
        if not completed and err is None:  # the browser went away before the end
            err = AppError("unknown", "การเชื่อมต่อถูกปิดก่อนได้คำตอบครบ")
        stored_id, usage = _settle(ctx, user_id, conv_id, provider, model_id, message_id, context_text, result,
                                   err, started, request_id, buckets, reserved)
        await deltas.aclose()  # the generator may never have started, so also close the response directly
        await closer()
    if err is None:
        yield _sse("done", {"message_id": stored_id, **usage})
    else:
        yield _sse("error", {"code": err.type, "message": err.user_message, "partial": bool(result.text),
                             "message_id": stored_id, "retryable": err.retryable})


def _settle(ctx: Context, user_id: int, conv_id: str, provider: str, model_id: str, message_id: str,
            context_text: str, result: StreamResult, err: AppError | None, started: float, request_id: str,
            buckets: list[quota.Bucket], reserved: int) -> tuple[str | None, dict[str, int]]:
    """Store the answer if there is any text, settle the quota hold like /api/run, and write one log line.

    A local turn has no buckets, so no cloud usage row is touched for it.
    """
    text = result.text
    stored_id: str | None = None
    tokens_in = result.tokens_in or estimate_tokens(context_text)
    tokens_out = result.tokens_out or estimate_tokens(text)
    # A failed run with no output is not charged, the same rule as /api/run: the hold is given back in full.
    charged = tokens_in + tokens_out if (err is None or text) else 0
    # Settle before saving the answer, so a failed save cannot leave the hold in place.
    if buckets:
        quota.settle_all(ctx.db, user_id, buckets, reserved=reserved, charged=charged)
    if text:  # never store an empty assistant message
        status = "complete" if err is None and not result.truncated else "partial"
        if finish_turn(ctx.db, user_id, conv_id, message_id, text, status):  # False: conversation deleted mid-answer
            stored_id = message_id
    if err is None:
        log_status = "partial" if result.truncated else "ok"
    else:
        log_status = "partial" if text else "error"
    _log_turn(ctx, user_id, conv_id, provider, model_id, request_id, started, log_status, err,
              tokens_in=tokens_in, tokens_out=tokens_out)
    return stored_id, {"tokens_in": tokens_in, "tokens_out": tokens_out}


def _log_turn(ctx: Context, user_id: int, conv_id: str, provider: str, model_id: str, request_id: str,
              started: float, status: str, err: AppError | None, tokens_in: int = 0, tokens_out: int = 0) -> None:
    """One JSON log line per chat turn. Message text and keys are never logged."""
    latency_ms = int((time.perf_counter() - started) * 1000)
    log_event("chat", ctx.log_stream, request_id=request_id, user_id=user_id, conversation_id=conv_id,
              provider=provider, model=model_id, status=status, error_type=err.type if err else None,
              latency_ms=latency_ms, tokens_in=tokens_in, tokens_out=tokens_out,
              cost_estimate=estimate_cost(tokens_in + tokens_out, ctx.settings.cost_per_1k_tokens))
