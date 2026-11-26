"""
payments_api.py — HTTP routes ของแพ็กเกจ/คำสั่งซื้อ (เรียกจาก server.py แบบเดียวกับ chat_hub)

    GET  /api/plans                                  public (ไม่คืนเลข PromptPay)
    POST /api/orders              {"plan"}           USER+  สร้าง pending + payload QR
    GET  /api/orders                                 USER+  เฉพาะของตัวเอง
    POST /api/orders/<id>/cancel                     USER+  ของตัวเองที่ pending
    POST /api/orders/<id>/refund-request {"reason"}  USER+  ของตัวเองที่ paid/active
    GET  /api/admin/orders?status=                   ADMIN+
    POST /api/admin/orders/<id>/confirm-paid|refund|reject-refund   ADMIN+
    POST /api/pay/stripe/checkout {"plan"}           USER+  Stripe hosted Checkout → {"url"}
    POST /api/pay/stripe/webhook                     no auth; Stripe-Signature on raw body
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

from app import config_manager, payments, stripe_pay

_USER_ACTION = re.compile(r"^/api/orders/(ord_[0-9a-f]{16})/(cancel|refund-request)$")
_ADMIN_ACTION = re.compile(r"^/api/admin/orders/([^/]+)/(confirm-paid|refund|reject-refund)$")
_ADMIN_FUNCS = {"confirm-paid": payments.confirm_paid, "refund": payments.refund,
                "reject-refund": payments.reject_refund}
STRIPE_CHECKOUT = "/api/pay/stripe/checkout"
STRIPE_WEBHOOK = "/api/pay/stripe/webhook"
MAX_WEBHOOK_BYTES = 256 * 1024
GET_PATHS = {"/api/plans", "/api/orders", "/api/admin/orders"}


def tick(project_root) -> None:
    """เรียกได้ทุก request — sweep หมดอายุแบบ throttle, ไม่ raise"""
    payments.maybe_sweep(project_root)


def wants_get(path: str) -> bool:
    return path in GET_PATHS


def wants_post(path: str) -> bool:
    if path.startswith("/api/pay/stripe/"):
        return True
    return path == "/api/orders" or bool(_USER_ACTION.match(path) or _ADMIN_ACTION.match(path))


def _body(handler) -> dict | None:
    try:
        return handler._read_json_body()
    except (ValueError, json.JSONDecodeError) as e:
        handler._send_json(400, {"error": f"body ไม่ถูกต้อง: {e}"})
        return None


def _call(handler, fn, *args, **kwargs) -> None:
    try:
        res = fn(*args, **kwargs)
    except payments.PaymentError as e:
        handler._send_json(e.status, e.body())
        return
    handler._send_json(200, res)


def handle_get(handler, parsed, project_root) -> None:
    payments.maybe_sweep(project_root)
    if parsed.path == "/api/plans":
        handler._send_json(200, {"plans": payments.load_plans(project_root),
                                 "promptpay_ready": payments.promptpay_ready(project_root),
                                 "stripe_ready": stripe_pay.ready(project_root),
                                 "pay_window_min": payments.PAY_WINDOW_S // 60,
                                 "plan_days": payments.PLAN_DAYS})
        return
    if parsed.path == "/api/orders":
        ident = handler._require("USER")
        if ident is None:
            return
        payments.sweep(project_root)  # สถานะที่ลูกค้าเห็นต้องสด (pending หมดเวลา)
        orders = payments.list_orders(project_root, username=ident.get("username"))
        handler._send_json(200, {"orders": stripe_pay.annotate(project_root, orders,
                                                                 with_resume=True)})
        return
    ident = handler._require("ADMIN")
    if ident is None:
        return
    status = (parse_qs(parsed.query).get("status") or [""])[0].strip() or None
    payments.sweep(project_root)
    try:
        orders = payments.list_orders(project_root, status=status, with_events=True)
    except payments.PaymentError as e:
        handler._send_json(e.status, e.body())
        return
    handler._send_json(200, {"orders": stripe_pay.annotate(project_root, orders)})


_LOOPBACK = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?$")
NO_BASE_URL_MSG = "ยังไม่ได้ตั้ง PUBLIC_BASE_URL (https) — ชำระผ่าน Stripe โหมด live ไม่ได้"


def _server_port(handler) -> int:
    try:
        return int(handler.server.server_address[1])
    except Exception:  # noqa: BLE001 - fall back to default port
        return 8420


def _base_url(handler, project_root) -> str | None:
    """success/cancel origin: PUBLIC_BASE_URL only (never the request Host).
    live: https required; test: https or loopback http; unset → live None, test loopback."""
    live = stripe_pay._mode(project_root) == "live"
    base = config_manager.get_key(project_root, "PUBLIC_BASE_URL")
    base = base.strip().rstrip("/") if isinstance(base, str) else ""
    if base.startswith("https://") and len(base) > 8:
        return base
    if base and not live and _LOOPBACK.match(base):
        return base
    if live:
        return None
    return f"http://127.0.0.1:{_server_port(handler)}"


def _handle_stripe(handler, path, project_root) -> None:
    if path == STRIPE_WEBHOOK:
        try:
            length = int(handler.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_WEBHOOK_BYTES:
            handler._send_json(400, {"error": "body ไม่ถูกต้อง", "code": "bad_body"})
            return
        raw = handler.rfile.read(length)
        status, body = stripe_pay.handle_webhook(project_root, raw,
                                                 handler.headers.get("Stripe-Signature"))
        handler._send_json(status, body)
        return
    if path != STRIPE_CHECKOUT:
        handler._send_json(404, {"error": "ไม่พบ endpoint"})
        return
    if not stripe_pay.ready(project_root):
        handler._send_json(503, {"error": stripe_pay.NOT_READY_MSG, "code": "stripe_not_configured"})
        return
    ident = handler._require("USER")
    if ident is None:
        return
    data = _body(handler)
    if data is None:
        return
    base = _base_url(handler, project_root)
    if base is None:
        handler._send_json(503, {"error": NO_BASE_URL_MSG, "code": "public_base_url_required"})
        return
    # ราคาไม่รับจาก client: ใช้เฉพาะ plan id
    _call(handler, stripe_pay.create_checkout, project_root, ident.get("username"),
          data.get("plan"), base)


def handle_post(handler, parsed, project_root) -> None:
    payments.maybe_sweep(project_root)
    path = parsed.path
    if path.startswith("/api/pay/stripe/"):
        _handle_stripe(handler, path, project_root)
        return
    m_admin = _ADMIN_ACTION.match(path)
    ident = handler._require("ADMIN" if m_admin else "USER")
    if ident is None:
        return
    data = _body(handler)
    if data is None:
        return
    user = ident.get("username")
    if path == "/api/orders":
        _call(handler, payments.create_order, project_root, user, data.get("plan"))
        return
    if m_admin:
        order_id, action = m_admin.groups()
        if action == "refund" and stripe_pay.is_stripe(project_root, order_id):
            _call(handler, stripe_pay.refund, project_root, order_id, user, ident.get("role"))
            return
        _call(handler, _ADMIN_FUNCS[action], project_root, order_id, user, ident.get("role"))
        return
    order_id, action = _USER_ACTION.match(path).groups()
    if action == "cancel":
        fn = stripe_pay.cancel_order if stripe_pay.is_stripe(project_root, order_id)             else payments.cancel_order
        _call(handler, fn, project_root, order_id, user, ident.get("role"),
              owner=user)
    else:
        _call(handler, payments.request_refund, project_root, order_id, user, data.get("reason"))
