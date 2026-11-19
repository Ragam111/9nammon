"""Route chat turns through ``app.providers``, with ``model_backend`` as fallback.

A request that names a provider uses that provider for this turn only. The
transcript comes from the conversation row, so the next turn can name a
different provider and still see the same thread. Requests that name neither
a provider nor a conversation stay on the existing ``model_backend`` path in
``server.py``.

Local targets take the admission gate and, when more than one is in a compare
set, run one at a time. Cloud targets in a compare set run together. "Local"
means the endpoint host is localhost, 127.0.0.1 or ::1 (see
``app.providers.locality``); an Ollama or OpenAI-compatible base_url on any
other host (LAN IP, remote server, tunnel) counts as cloud.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs

from app import chat_store
from app.chat_store import ChatStoreError

# Adapters that *can* be local; whether one is depends on its base_url host.
LOCAL_PROVIDERS = {"ollama", "openai_compat"}
MAX_COMPARE = 4

SUGGESTED_MODELS = {
    "ollama": ["qwen2.5-coder:0.5b", "qwen2.5-coder:1.5b", "qwen2.5-coder:3b"],
    "openai_compat": ["local-model"],
    "openai": ["gpt-4o-mini", "gpt-4.1-mini"],
    "anthropic": ["claude-haiku-4-5", "claude-sonnet-4-5"],
    "gemini": ["gemini-2.5-flash"],
    "xai": ["grok-4.3"],
}
LABELS = {
    "ollama": "Ollama",
    "openai_compat": "OpenAI-compatible",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Gemini",
    "xai": "xAI",
}

GET_PATHS = {
    "/api/chat/conversations",
    "/api/chat/search",
    "/api/chat/folders",
    "/api/chat/personas",
    "/api/chat/providers",
    "/api/chat/export",
}
POST_PATHS = {
    "/api/chat/branch",
    "/api/chat/regen",
    "/api/chat/compare",
    "/api/chat/switch",
    "/api/chat/edit",
    "/api/chat/conversations",
    "/api/chat/conversations/update",
    "/api/chat/conversations/delete",
    "/api/chat/folders",
    "/api/chat/personas",
    "/api/chat/import",
    "/api/chat/save",
}


def wants_get(path: str) -> bool:
    return path in GET_PATHS


def wants_post(path: str) -> bool:
    return path in POST_PATHS


def _is_local(provider, project_root=None) -> bool:
    from app.providers.locality import is_local_provider
    return is_local_provider(provider, project_root)


def is_local_provider(provider, project_root=None) -> bool:
    """public: provider นี้รันในเครื่อง (ไม่เสียเงิน/ข้อมูลไม่ออก) ไหม — server ใช้กัน guest"""
    try:
        return _is_local(_canonical(provider), project_root)
    except Exception:
        return False


class ChatAccessError(ChatStoreError):
    """ผู้ใช้ไม่มีสิทธิ์ในการสนทนานี้ (→ 403) — แยกจาก ChatStoreError ทั่วไป (→ 400)"""


def _can_see(conv_owner, ident) -> bool:
    """กฎพื้นที่: owner=NULL = พื้นที่บริษัท (ทุกคนที่ล็อกอินเห็น), owner=ชื่อ = พื้นที่ส่วนตัว
    (เจ้าของเท่านั้น), ADMIN/CEO เห็นทุกพื้นที่ (ดูแลระบบ)"""
    from app import org_store
    role = (ident or {}).get("role") or "USER"
    if org_store.role_at_least(role, "ADMIN"):
        return True
    if conv_owner in (None, ""):
        return True
    return conv_owner == _owner(ident)


def _assert_access(conv, ident) -> dict:
    if not _can_see((conv or {}).get("owner"), ident):
        raise ChatAccessError("ไม่มีสิทธิ์เข้าถึงการสนทนานี้")
    return conv


def _only_visible(rows, ident, owner_key="owner") -> list:
    return [r for r in rows if _can_see(r.get(owner_key), ident)]


def _providers():
    from app import providers
    return providers


def _canonical(name: str) -> str:
    from app.providers.registry import canonicalize
    return canonicalize(name)


def _usage_dict(usage) -> dict | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "estimated": bool(usage.estimated),
    }


def _tokens(usage):
    if usage is None:
        return None, None, 1
    return usage.input_tokens, usage.output_tokens, 1 if usage.estimated else 0


def _http_status(exc) -> int:
    from app.providers.errors import ProviderError, ProviderRateLimitError
    if isinstance(exc, ProviderRateLimitError):
        return 429
    if type(exc) is ProviderError:
        return 400
    return 502


def _fallback_system(lang: str) -> str:
    try:
        from local_coder import get_system_prompt
        return get_system_prompt(lang or "th")
    except Exception:
        return ""


def _owner(ident) -> str | None:
    name = (ident or {}).get("username")
    if name in (None, "", "__local__", "__master__"):
        return None
    return name


def _last_user(messages) -> str:
    for message in reversed(messages or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _meter(project_root, connection_id, provider, model, usage) -> None:
    try:
        from app import conn_usage
        incoming, outgoing, _est = _tokens(usage)
        conn_usage.record_usage(
            project_root,
            connection_id or (provider or ""),
            model or provider or "",
            int(incoming or 0),
            int(outgoing or 0),
            endpoint="chat",
        )
    except Exception as exc:  # metering must not fail the reply
        print(f"[chat][warn] บันทึก conn_usage ไม่สำเร็จ: {exc}")


def _quota(handler, ident, model, transcript, text, status) -> None:
    if status != "ok":
        return
    finalize = getattr(handler, "_chat_finalize", None)
    if finalize is None:
        return
    try:
        finalize(ident, model, transcript, text)
    except Exception as exc:
        print(f"[chat][warn] ปิดงานแชทไม่สำเร็จ: {exc}")


def complete(project_root, *, provider, model, transcript, gen_gate, num_ctx,
             on_open=None, on_delta=None, on_partial=None) -> dict:
    """Run one completion. ``provider`` None uses ``model_backend``.

    The admission gate is held only for local runs, and only after ``on_open``
    would be too late: ``on_open`` runs once the gate is acquired so a busy
    machine can still answer 503 before streaming headers.
    """
    from app import admission
    started = time.monotonic()
    parts: list[str] = []
    usage = None
    error = None
    status = "ok"
    http_status = None
    disconnect = False
    last_flush = started
    gate = None
    try:
        if _is_local(provider, project_root):
            if gen_gate is None:
                raise admission.Busy("ไม่มีช่องรันโมเดล")
            gate = gen_gate.slot()
            gate.__enter__()
        if on_open is not None:
            on_open()
        if provider:
            providers = _providers()
            canonical = _canonical(provider)
            if on_delta is not None:
                stream = providers.stream(
                    transcript, model, provider=canonical, project_root=project_root,
                )
                try:
                    for delta in stream:
                        if not delta:
                            continue
                        parts.append(delta)
                        on_delta(delta)
                        now = time.monotonic()
                        if on_partial is not None and now - last_flush >= 2:
                            on_partial("".join(parts))
                            last_flush = now
                finally:
                    try:
                        stream.close()
                    except Exception:
                        pass
                    usage = getattr(stream, "usage", None)
            else:
                response = providers.chat(
                    transcript, model, provider=canonical, project_root=project_root,
                )
                parts.append(response.text or "")
                usage = response.usage
        else:
            from app import model_backend
            if on_delta is not None:
                for delta in model_backend.generate_stream(project_root, model, transcript, num_ctx):
                    if not delta:
                        continue
                    parts.append(delta)
                    on_delta(delta)
                    now = time.monotonic()
                    if on_partial is not None and now - last_flush >= 2:
                        on_partial("".join(parts))
                        last_flush = now
            else:
                parts.append(model_backend.generate(project_root, model, transcript, num_ctx) or "")
            if usage is None:
                from app.providers.base import Usage
                from app.providers.pricing import estimate_tokens
                text_so_far = "".join(parts)
                incoming = 0
                for message in transcript:
                    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
                    incoming += estimate_tokens(content or "")
                outgoing = estimate_tokens(text_so_far)
                usage = Usage(incoming, outgoing, incoming + outgoing, True, "estimate")
    except (BrokenPipeError, ConnectionResetError):
        disconnect = True
        status = "stopped"
    except admission.Busy:
        raise
    except Exception as exc:
        from app import model_backend
        from app.providers.errors import ProviderError
        status = "error"
        error = str(exc) or exc.__class__.__name__
        if isinstance(exc, (ProviderError, model_backend.BackendError)):
            http_status = _http_status(exc) if isinstance(exc, ProviderError) else 502
        else:
            http_status = 502
        print(f"[chat][warn] โมเดลตอบไม่จบ: {error}")
    finally:
        if gate is not None:
            gate.__exit__(None, None, None)
    return {
        "text": "".join(parts),
        "usage": usage,
        "status": status,
        "error": error,
        "http_status": http_status,
        "disconnect": disconnect,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


def _finish_row(project_root, message_id, result, provider, model) -> dict:
    extra = {"error": result["error"]} if result["error"] else None
    tokens_in, tokens_out, tokens_est = _tokens(result["usage"])
    with chat_store.write_txn(project_root) as conn:
        return chat_store.finalize_message(
            conn, message_id,
            content=result["text"],
            status=result["status"] if result["status"] in ("ok", "error", "stopped") else "error",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_est=tokens_est,
            latency_ms=result["latency_ms"],
            extra=extra,
            provider=provider,
            model=model,
        )


def _open_turn(project_root, conversation_id, *, content, parent_id, origin, source_id,
               provider, model, connection_id, role="user"):
    with chat_store.write_txn(project_root) as conn:
        message = chat_store.insert_message(
            conn, int(conversation_id),
            role=role, content=content or "", parent_id=parent_id, origin=origin,
            source_id=source_id, provider=provider, model=model,
            connection_id=connection_id,
            status="ok" if role == "user" else "streaming",
        )
        return message


def _placeholder(project_root, conversation_id, parent_id, *, origin, source_id, provider, model, connection_id):
    with chat_store.write_txn(project_root) as conn:
        return chat_store.insert_message(
            conn, int(conversation_id),
            role="assistant", content="", parent_id=parent_id, origin=origin,
            source_id=source_id, provider=provider, model=model,
            connection_id=connection_id, status="streaming",
        )


def _path(project_root, conversation_id) -> list:
    with chat_store.read_txn(project_root) as conn:
        return chat_store.active_path(conn, int(conversation_id))


def _transcript(project_root, conversation_id, up_to, lang) -> list:
    with chat_store.read_txn(project_root) as conn:
        return chat_store.transcript(
            conn, int(conversation_id), up_to=up_to, fallback_system=_fallback_system(lang),
        )


def _run_assistant(handler, project_root, ident, *, conversation_id, parent_id, provider, model,
                   connection_id, gen_gate, num_ctx, lang, origin, source_id, stream, sink=None):
    """Insert a streaming assistant row, complete it, and return the public payload."""
    from app import admission
    canonical = _canonical(provider) if provider else None
    model = (model or "").strip()
    if not model:
        raise ChatStoreError("ต้องระบุ model")
    placeholder = _placeholder(
        project_root, conversation_id, parent_id,
        origin=origin, source_id=source_id, provider=canonical, model=model,
        connection_id=connection_id,
    )
    transcript = _transcript(project_root, conversation_id, parent_id, lang)
    if not any(m["role"] in ("user", "assistant") for m in transcript):
        raise ChatStoreError("ยังไม่มีข้อความที่จะส่งให้โมเดล")

    opened = {"sent": False}

    def on_partial(text):
        with chat_store.write_txn(project_root) as conn:
            chat_store.touch_stream(conn, placeholder["id"], text)

    def on_open():
        if stream and sink is not None and not opened["sent"]:
            sink["open"]()
            opened["sent"] = True
            sink["send"]({
                "meta": {
                    "conversation_id": int(conversation_id),
                    "message_id": placeholder["id"],
                    "provider": canonical,
                    "model": model,
                }
            })

    try:
        result = complete(
            project_root, provider=canonical, model=model, transcript=transcript,
            gen_gate=gen_gate, num_ctx=num_ctx,
            on_open=on_open if stream else None,
            on_delta=(sink["send_delta"] if stream and sink else None),
            on_partial=on_partial,
        )
    except admission.Busy as exc:
        with chat_store.write_txn(project_root) as conn:
            chat_store.finalize_message(
                conn, placeholder["id"], content="", status="error",
                extra={"error": str(exc)}, provider=canonical, model=model,
            )
        return {
            "reply": "",
            "provider": canonical,
            "model": model,
            "conversation_id": int(conversation_id),
            "message_id": placeholder["id"],
            "status": "error",
            "error": str(exc),
            "http_status": 503,
            "disconnect": False,
            "usage": None,
            "path": _path(project_root, conversation_id),
        }
    row = _finish_row(project_root, placeholder["id"], result, canonical, model)
    _meter(project_root, connection_id, canonical, model, result["usage"])
    _quota(handler, ident, model, transcript, result["text"], result["status"])
    return {
        "reply": result["text"],
        "provider": canonical,
        "model": model,
        "conversation_id": int(conversation_id),
        "message_id": row["id"],
        "status": result["status"],
        "error": result["error"],
        "http_status": result["http_status"],
        "disconnect": result["disconnect"],
        "usage": _usage_dict(result["usage"]),
        "path": _path(project_root, conversation_id),
    }


def _send_turn(handler, project_root, ident, model, messages, num_ctx, hub, gen_gate, *, stream, sink=None):
    provider = hub.get("provider")
    connection_id = hub.get("connection_id")
    lang = hub.get("lang") or "th"
    content = (hub.get("content") or "").strip() or _last_user(messages)
    cid = hub.get("conversation_id")
    if stream and sink is None:
        sink = _sse_sink(handler)
    if cid:
        with chat_store.read_txn(project_root) as conn:
            conv = _assert_access(chat_store.get_conversation(conn, cid), ident)
        if not content:
            raise ChatStoreError("ต้องมีข้อความ")
        parent = hub.get("parent_id")
        if parent in ("", None):
            parent = conv["active_leaf_id"]
        user = _open_turn(
            project_root, conv["id"], content=content, parent_id=parent, origin=None,
            source_id=None, provider=None, model=None, connection_id=None, role="user",
        )
        payload = _run_assistant(
            handler, project_root, ident,
            conversation_id=conv["id"], parent_id=user["id"], provider=provider, model=model,
            connection_id=connection_id, gen_gate=gen_gate, num_ctx=num_ctx, lang=lang,
            origin=None, source_id=None, stream=stream, sink=sink,
        )
        payload["user_message_id"] = user["id"]
        _emit(handler, payload, stream, sink)
        return
    if not provider:
        raise ChatStoreError("ต้องระบุ provider")
    transcript = list(messages or [])
    if not transcript:
        raise ChatStoreError("ต้องมี messages")
    canonical = _canonical(provider)

    def on_open():
        if sink is not None:
            sink["open"]()

    result = complete(
        project_root, provider=canonical, model=(model or "").strip(), transcript=transcript,
        gen_gate=gen_gate, num_ctx=num_ctx,
        on_open=on_open if stream else None,
        on_delta=(sink["send_delta"] if sink else None),
    )
    _meter(project_root, connection_id, canonical, model, result["usage"])
    _quota(handler, ident, model, transcript, result["text"], result["status"])
    payload = {
        "reply": result["text"],
        "provider": canonical,
        "model": (model or "").strip(),
        "status": result["status"],
        "error": result["error"],
        "http_status": result["http_status"],
        "disconnect": result["disconnect"],
        "usage": _usage_dict(result["usage"]),
    }
    _emit(handler, payload, stream, sink)


def _emit(handler, payload, stream, sink) -> None:
    try:
        if payload.get("disconnect"):
            return
        if stream and sink is not None and sink.get("is_open") and sink["is_open"]():
            if payload["status"] == "ok":
                sink["send"]({
                    "done": True,
                    "message_id": payload.get("message_id"),
                    "conversation_id": payload.get("conversation_id"),
                    "usage": payload.get("usage"),
                })
            else:
                sink["send"]({
                    "error": payload.get("error") or "ต่อโมเดลไม่ได้",
                    "status": payload["status"],
                    "partial": True,
                    "message_id": payload.get("message_id"),
                    "conversation_id": payload.get("conversation_id"),
                })
            return
        status = 200 if payload["status"] == "ok" else (payload.get("http_status") or 502)
        body = {key: value for key, value in payload.items() if key not in ("http_status", "disconnect")}
        handler._send_json(status, body)
    except (BrokenPipeError, ConnectionResetError):
        return


def _sse_sink(handler) -> dict:
    state = {"opened": False}

    def open_headers():
        if state["opened"]:
            return
        state["opened"] = True
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()

    def send(obj):
        handler.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
        handler.wfile.flush()

    def send_delta(text):
        send({"delta": text})

    return {
        "open": open_headers,
        "send": send,
        "send_delta": send_delta,
        "is_open": lambda: state["opened"],
    }


def serve_chat(handler, project_root, ident, model, messages, num_ctx, hub, gen_gate, *, stream: bool):
    """Entry from ``/api/chat`` and ``/api/chat/stream`` when a provider or conversation is set."""
    from app import admission
    sink = _sse_sink(handler) if stream else None

    def fail(status: int, message: str, kind: str = "error"):
        # หลังส่ง 200 + header SSE ไปแล้ว จะส่ง JSON ซ้อนอีก response ไม่ได้ (client ได้ขยะ)
        # → ปิดสตรีมด้วย event error เสมอ; ยังไม่เปิดสตรีม → ตอบ status JSON ปกติ
        if sink is not None and sink["is_open"]():
            try:
                sink["send"]({"error": message, "status": kind, "partial": True})
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        handler._send_json(status, {"error": message})

    try:
        _send_turn(handler, project_root, ident, model, messages, num_ctx, hub, gen_gate,
                   stream=stream, sink=sink)
    except admission.Busy as exc:
        fail(503, str(exc), "busy")
    except ChatAccessError as exc:
        fail(403, str(exc))
    except ChatStoreError as exc:
        fail(400, str(exc))
    except (BrokenPipeError, ConnectionResetError):
        return
    except Exception as exc:  # noqa: BLE001 — provider/DB พังกลางทาง: ต้องมีคำตอบเสมอ
        from app.providers.errors import ProviderError
        print(f"[chat][warn] {exc}")
        status = _http_status(exc) if isinstance(exc, ProviderError) else 502
        fail(status, str(exc) or exc.__class__.__name__)


def export_markdown(doc: dict) -> str:
    """แปลง export document (lca-chat-export) เป็น Markdown อ่านง่าย — "Session Tape" สำหรับคน"""
    conv = doc.get("conversation") or {}
    lines = [f"# {conv.get('title') or 'บทสนทนา'}", ""]
    meta = []
    if conv.get("owner"):
        meta.append(f"owner: {conv['owner']}")
    if conv.get("created_at"):
        meta.append(f"created_at: {conv['created_at']}")
    if conv.get("updated_at"):
        meta.append(f"updated_at: {conv['updated_at']}")
    meta.append(f"uid: {conv.get('uid')}")
    lines.append("> " + " · ".join(meta))
    lines.append("")
    if conv.get("system_prompt"):
        lines += ["## System", "", str(conv["system_prompt"]).rstrip(), ""]
    for message in conv.get("messages") or []:
        role = str(message.get("role") or "")
        label = {"user": "ผู้ใช้", "assistant": "ผู้ช่วย", "system": "System"}.get(role, role)
        tag = ""
        if message.get("model"):
            tag = f" ({message.get('provider') or ''}{'/' if message.get('provider') else ''}{message['model']})"
        if message.get("status") and message["status"] != "ok":
            tag += f" [{message['status']}]"
        lines.append(f"## {label}{tag}")
        lines.append("")
        lines.append(str(message.get("content") or "").rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _send_markdown(handler, text: str, filename: str) -> None:
    body = text.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/markdown; charset=utf-8")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def handle_get(handler, parsed, project_root) -> None:
    ident = handler._require("USER")
    if ident is None:
        return
    path = parsed.path
    qs = parse_qs(parsed.query)
    try:
        if path == "/api/chat/providers":
            handler._send_json(200, {"providers": _provider_catalog(project_root)})
        elif path == "/api/chat/personas":
            with chat_store.read_txn(project_root) as conn:
                handler._send_json(200, {"personas": chat_store.list_personas(conn)})
        elif path == "/api/chat/folders":
            with chat_store.read_txn(project_root) as conn:
                handler._send_json(200, {"folders": chat_store.folder_tree(conn)})
        elif path == "/api/chat/search":
            query = (qs.get("q") or [""])[0]
            with chat_store.read_txn(project_root) as conn:
                found = chat_store.search(conn, query)
            found["conversations"] = _only_visible(found.get("conversations") or [], ident)
            found["messages"] = _only_visible(found.get("messages") or [], ident)
            handler._send_json(200, found)
        elif path == "/api/chat/export":
            key = (qs.get("id") or [None])[0]
            fmt = (qs.get("format") or ["json"])[0].lower()
            with chat_store.read_txn(project_root) as conn:
                _assert_access(chat_store.get_conversation(conn, key), ident)
                doc = chat_store.export_public(conn, key)
            if fmt in ("md", "markdown"):
                _send_markdown(handler, export_markdown(doc), f"lca-chat-{doc['conversation']['uid']}.md")
            else:
                handler._send_json(200, doc)
        elif path == "/api/chat/conversations":
            if qs.get("id"):
                with chat_store.read_txn(project_root) as conn:
                    conv = _assert_access(chat_store.get_conversation(conn, qs["id"][0]), ident)
                    handler._send_json(200, {
                        "conversation": conv,
                        "messages": chat_store.active_path(conn, conv["id"]),
                        "system_prompt": chat_store.effective_system(conn, conv["id"]),
                    })
            else:
                folder = "all" if "folder_id" not in qs else qs["folder_id"][0]
                limit = (qs.get("limit") or ["50"])[0]
                with chat_store.read_txn(project_root) as conn:
                    rows = chat_store.list_conversations(conn, folder_id=folder, limit=limit)
                handler._send_json(200, {"conversations": _only_visible(rows, ident)})
        else:
            handler._send_json(404, {"error": "not found"})
    except ChatAccessError as exc:
        handler._send_json(403, {"error": str(exc)})
    except ChatStoreError as exc:
        handler._send_json(400, {"error": str(exc)})


def handle_post(handler, parsed, project_root, gen_gate) -> None:
    ident = handler._require("USER")
    if ident is None:
        return
    data = handler._read_json_body()
    path = parsed.path
    try:
        if path == "/api/chat/conversations":
            _post_conversation(handler, project_root, ident, data)
        elif path == "/api/chat/conversations/update":
            _post_update(handler, project_root, ident, data)
        elif path == "/api/chat/conversations/delete":
            _post_delete(handler, project_root, ident, data)
        elif path == "/api/chat/folders":
            _post_folder(handler, project_root, data)
        elif path == "/api/chat/personas":
            _post_persona(handler, project_root, data)
        elif path == "/api/chat/switch":
            _post_switch(handler, project_root, ident, data)
        elif path == "/api/chat/branch":
            _post_branch(handler, project_root, ident, data, gen_gate)
        elif path == "/api/chat/regen":
            _post_regen(handler, project_root, ident, data, gen_gate)
        elif path == "/api/chat/edit":
            _post_edit(handler, project_root, ident, data, gen_gate)
        elif path == "/api/chat/compare":
            _post_compare(handler, project_root, ident, data, gen_gate)
        elif path == "/api/chat/import":
            _post_import(handler, project_root, ident, data)
        elif path == "/api/chat/save":
            _post_save(handler, project_root, ident, data)
        else:
            handler._send_json(404, {"error": "not found"})
    except ChatAccessError as exc:
        handler._send_json(403, {"error": str(exc)})
    except ChatStoreError as exc:
        handler._send_json(400, {"error": str(exc)})
    except Exception as exc:
        from app.providers.errors import ProviderError
        if not isinstance(exc, ProviderError):
            raise
        handler._send_json(_http_status(exc), {"error": str(exc)})


def _provider_catalog(project_root) -> list:
    recommended = None
    try:
        from app import resource_budget
        recommended = resource_budget.pick_model(project_root=project_root)["model"]
    except Exception:
        recommended = None
    catalog = []
    for name in _providers().supported_providers():
        models = list(SUGGESTED_MODELS.get(name, []))
        if name == "ollama" and recommended and recommended not in models:
            models.insert(0, recommended)
        catalog.append({
            "id": name,
            "label": LABELS.get(name, name),
            "local": _is_local(name, project_root),
            "models": models,
        })
    return catalog


def _post_conversation(handler, project_root, ident, data) -> None:
    with chat_store.write_txn(project_root) as conn:
        conv = chat_store.create_conversation(
            conn,
            title=(data.get("title") or "").strip(),
            folder_id=data.get("folder_id"),
            persona_id=data.get("persona_id"),
            system_prompt=data.get("system_prompt"),
            owner=_owner(ident),
        )
    handler._send_json(200, {"conversation": conv})


def _post_update(handler, project_root, ident, data) -> None:
    with chat_store.write_txn(project_root) as conn:
        _assert_access(chat_store.get_conversation(conn, data.get("id")), ident)
        conv = chat_store.update_conversation(conn, data.get("id"), **{
            key: data.get(key) for key in ("title", "system_prompt", "folder_id", "persona_id", "pinned", "archived")
            if key in data
        })
    handler._send_json(200, {"conversation": conv})


def _post_delete(handler, project_root, ident, data) -> None:
    with chat_store.write_txn(project_root) as conn:
        _assert_access(chat_store.get_conversation(conn, data.get("id")), ident)
        chat_store.delete_conversation(conn, data.get("id"))
    handler._send_json(200, {"deleted": True})


def _post_folder(handler, project_root, data) -> None:
    with chat_store.write_txn(project_root) as conn:
        folder = chat_store.create_folder(
            conn, name=data.get("name") or "", kind=data.get("kind") or "folder",
            parent_id=data.get("parent_id"), instructions=data.get("instructions"),
            persona_id=data.get("persona_id"),
        )
    handler._send_json(200, {"folder": folder})


def _post_persona(handler, project_root, data) -> None:
    with chat_store.write_txn(project_root) as conn:
        persona = chat_store.create_persona(
            conn, name=data.get("name") or "", system_prompt=data.get("system_prompt") or "",
            provider=data.get("provider"), model=data.get("model"),
        )
    handler._send_json(200, {"persona": persona})


def _post_switch(handler, project_root, ident, data) -> None:
    with chat_store.write_txn(project_root) as conn:
        conv = _assert_access(chat_store.get_conversation(conn, data.get("conversation_id")), ident)
        leaf = chat_store.switch_branch(conn, conv["id"], int(data.get("message_id")))
        path = chat_store.active_path(conn, conv["id"])
    handler._send_json(200, {"active_leaf_id": leaf, "conversation_id": conv["id"], "messages": path})


def _need_conv(project_root, data, ident=None):
    with chat_store.read_txn(project_root) as conn:
        conv = chat_store.get_conversation(conn, data.get("conversation_id"))
    return _assert_access(conv, ident) if ident is not None else conv


def _post_branch(handler, project_root, ident, data, gen_gate) -> None:
    conv = _need_conv(project_root, data, ident)
    content = (data.get("content") or "").strip()
    if not content:
        raise ChatStoreError("ต้องมีข้อความสำหรับสาขาใหม่")
    message_id = int(data.get("message_id"))
    with chat_store.read_txn(project_root) as conn:
        parent = chat_store.get_message(conn, message_id)
    if parent["conversation_id"] != conv["id"]:
        raise ChatStoreError("ข้อความไม่อยู่ในการสนทนานี้")
    user = _open_turn(
        project_root, conv["id"], content=content, parent_id=parent["id"], origin="branch",
        source_id=parent["id"], provider=None, model=None, connection_id=None, role="user",
    )
    payload = _run_assistant(
        handler, project_root, ident,
        conversation_id=conv["id"], parent_id=user["id"],
        provider=data.get("provider"), model=data.get("model"),
        connection_id=data.get("connection_id"), gen_gate=gen_gate,
        num_ctx=data.get("num_ctx") or 8192, lang=data.get("lang") or "th",
        origin="branch", source_id=None, stream=False, sink=None,
    )
    payload["user_message_id"] = user["id"]
    _emit(handler, payload, False, None)


def _post_regen(handler, project_root, ident, data, gen_gate) -> None:
    conv = _need_conv(project_root, data, ident)
    with chat_store.read_txn(project_root) as conn:
        old = chat_store.get_message(conn, int(data.get("message_id")))
    if old["conversation_id"] != conv["id"]:
        raise ChatStoreError("ข้อความไม่อยู่ในการสนทนานี้")
    if old["role"] != "assistant":
        raise ChatStoreError("ตอบใหม่ได้เฉพาะข้อความของผู้ช่วย")
    provider = data.get("provider") or old.get("provider")
    model = data.get("model") or old.get("model")
    payload = _run_assistant(
        handler, project_root, ident,
        conversation_id=conv["id"], parent_id=old["parent_id"],
        provider=provider, model=model, connection_id=data.get("connection_id") or old.get("connection_id"),
        gen_gate=gen_gate, num_ctx=data.get("num_ctx") or 8192, lang=data.get("lang") or "th",
        origin="regen", source_id=old["id"], stream=False, sink=None,
    )
    _emit(handler, payload, False, None)


def _post_edit(handler, project_root, ident, data, gen_gate) -> None:
    conv = _need_conv(project_root, data, ident)
    content = (data.get("content") or "").strip()
    if not content:
        raise ChatStoreError("ต้องมีข้อความที่แก้")
    with chat_store.read_txn(project_root) as conn:
        old = chat_store.get_message(conn, int(data.get("message_id")))
    if old["conversation_id"] != conv["id"] or old["role"] != "user":
        raise ChatStoreError("แก้ได้เฉพาะข้อความของผู้ใช้ในการสนทนานี้")
    user = _open_turn(
        project_root, conv["id"], content=content, parent_id=old["parent_id"], origin="edit",
        source_id=old["id"], provider=None, model=None, connection_id=None, role="user",
    )
    payload = _run_assistant(
        handler, project_root, ident,
        conversation_id=conv["id"], parent_id=user["id"],
        provider=data.get("provider"), model=data.get("model"),
        connection_id=data.get("connection_id"), gen_gate=gen_gate,
        num_ctx=data.get("num_ctx") or 8192, lang=data.get("lang") or "th",
        origin=None, source_id=None, stream=False, sink=None,
    )
    payload["user_message_id"] = user["id"]
    _emit(handler, payload, False, None)


def _post_compare(handler, project_root, ident, data, gen_gate) -> None:
    targets = data.get("targets")
    if not isinstance(targets, list) or len(targets) < 2:
        raise ChatStoreError("เทียบต้องส่งอย่างน้อย 2 โมเดล")
    if len(targets) > MAX_COMPARE:
        raise ChatStoreError(f"เทียบได้ไม่เกิน {MAX_COMPARE} โมเดล")
    cleaned = []
    for target in targets:
        if not isinstance(target, dict):
            raise ChatStoreError("เป้าหมายเทียบไม่ถูกต้อง")
        provider = _canonical(target.get("provider") or "")
        model = (target.get("model") or "").strip()
        if not model:
            raise ChatStoreError("ทุกเป้าหมายต้องมี model")
        cleaned.append({"provider": provider, "model": model, "connection_id": target.get("connection_id")})
    conv = _need_conv(project_root, data, ident) if data.get("conversation_id") else None
    if conv is None:
        with chat_store.write_txn(project_root) as conn:
            conv = chat_store.create_conversation(conn, title="", owner=_owner(ident))
    content = (data.get("content") or "").strip()
    if content:
        user = _open_turn(
            project_root, conv["id"], content=content,
            parent_id=data.get("parent_id") if data.get("parent_id") not in (None, "") else conv["active_leaf_id"],
            origin=None, source_id=None, provider=None, model=None, connection_id=None, role="user",
        )
    elif data.get("message_id"):
        with chat_store.read_txn(project_root) as conn:
            user = chat_store.get_message(conn, int(data["message_id"]))
        if user["conversation_id"] != conv["id"] or user["role"] != "user":
            raise ChatStoreError("เทียบได้จากข้อความของผู้ใช้")
    else:
        raise ChatStoreError("ต้องมีข้อความที่จะเทียบ")
    local_flags = [_is_local(t["provider"], project_root) for t in cleaned]
    locals_ = [t for t, is_local in zip(cleaned, local_flags) if is_local]
    clouds = [t for t, is_local in zip(cleaned, local_flags) if not is_local]
    replies = []

    def run(target):
        return _run_assistant(
            handler, project_root, ident,
            conversation_id=conv["id"], parent_id=user["id"],
            provider=target["provider"], model=target["model"],
            connection_id=target.get("connection_id"), gen_gate=gen_gate,
            num_ctx=data.get("num_ctx") or 8192, lang=data.get("lang") or "th",
            origin="compare", source_id=None, stream=False, sink=None,
        )

    if clouds:
        workers = max(1, len(clouds))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for payload in pool.map(run, clouds):
                replies.append(payload)
    for target in locals_:
        replies.append(run(target))
    ids = [item["message_id"] for item in replies if item.get("message_id")]
    if ids:
        first = min(ids)
        with chat_store.write_txn(project_root) as conn:
            marks = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE messages SET compare_id=? WHERE id IN ({marks})",
                (first, *ids),
            )
            chat_store.switch_branch(conn, conv["id"], first)
    replies.sort(key=lambda item: item.get("message_id") or 0)
    handler._send_json(200, {
        "conversation_id": conv["id"],
        "user_message_id": user["id"],
        "replies": [
            {
                "message_id": item.get("message_id"),
                "provider": item.get("provider"),
                "model": item.get("model"),
                "reply": item.get("reply"),
                "status": item.get("status"),
                "error": item.get("error"),
            }
            for item in replies
        ],
        "messages": _path(project_root, conv["id"]),
    })


def _post_import(handler, project_root, ident, data) -> None:
    doc = data.get("document") if isinstance(data.get("document"), dict) else data
    with chat_store.write_txn(project_root) as conn:
        conv = chat_store.import_document(conn, doc, as_copy=bool(data.get("as_copy")))
        # ไฟล์นำเข้าอาจระบุ owner เป็นคนอื่น — บทสนทนาที่นำเข้าเป็นของคนที่นำเข้าเสมอ
        mine = _owner(ident)
        if conv and conv.get("owner") != mine:
            conn.execute("UPDATE conversations SET owner=? WHERE id=?", (mine, conv["id"]))
            conv = chat_store.get_conversation(conn, conv["id"])
    handler._send_json(200, {"conversation": conv})


def _post_save(handler, project_root, ident, data) -> None:
    """Save a temporary (browser-only) transcript as a normal conversation."""
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ChatStoreError("ต้องมี messages")
    with chat_store.write_txn(project_root) as conn:
        conv = chat_store.create_conversation(
            conn, title=(data.get("title") or "").strip(), owner=_owner(ident),
            system_prompt=data.get("system_prompt"),
        )
        parent = None
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in ("user", "assistant"):
                continue
            row = chat_store.insert_message(
                conn, conv["id"], role=role, content=str(message.get("content") or ""),
                parent_id=parent, provider=message.get("provider"), model=message.get("model"),
                status=message.get("status") or "ok", origin="import",
            )
            parent = row["id"]
        saved = chat_store.get_conversation(conn, conv["id"])
    handler._send_json(200, {"conversation": saved})
