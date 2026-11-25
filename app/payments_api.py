"""
payments_api.py — HTTP routes ของแพ็กเกจ/คำสั่งซื้อ (เรียกจาก server.py แบบเดียวกับ chat_hub)

    GET  /api/plans                                  public (ไม่คืนเลข PromptPay)
    POST /api/orders              {"plan"}           USER+  สร้าง pending + payload QR
    GET  /api/orders                                 USER+  เฉพาะของตัวเอง
    POST /api/orders/<id>/cancel                     USER+  ของตัวเองที่ pending
    POST /api/orders/<id>/refund-request {"reason"}  USER+  ของตัวเองที่ paid/active
    GET  /api/admin/orders?status=                   ADMIN+
    POST /api/admin/orders/<id>/confirm-paid|refund|reject-refund   ADMIN+
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

from app import payments

_USER_ACTION = re.compile(r"^/api/orders/(ord_[0-9a-f]{16})/(cancel|refund-request)$")
_ADMIN_ACTION = re.compile(r"^/api/admin/orders/([^/]+)/(confirm-paid|refund|reject-refund)$")
_ADMIN_FUNCS = {"confirm-paid": payments.confirm_paid, "refund": payments.refund,
                "reject-refund": payments.reject_refund}
GET_PATHS = {"/api/plans", "/api/orders", "/api/admin/orders"}


def tick(project_root) -> None:
    """เรียกได้ทุก request — sweep หมดอายุแบบ throttle, ไม่ raise"""
    payments.maybe_sweep(project_root)


def wants_get(path: str) -> bool:
    return path in GET_PATHS


def wants_post(path: str) -> bool:
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
                                 "pay_window_min": payments.PAY_WINDOW_S // 60,
                                 "plan_days": payments.PLAN_DAYS})
        return
    if parsed.path == "/api/orders":
        ident = handler._require("USER")
        if ident is None:
            return
        payments.sweep(project_root)  # สถานะที่ลูกค้าเห็นต้องสด (pending หมดเวลา)
        handler._send_json(200, {"orders": payments.list_orders(project_root,
                                                                username=ident.get("username"))})
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
    handler._send_json(200, {"orders": orders})


def handle_post(handler, parsed, project_root) -> None:
    payments.maybe_sweep(project_root)
    path = parsed.path
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
        _call(handler, _ADMIN_FUNCS[action], project_root, order_id, user, ident.get("role"))
        return
    order_id, action = _USER_ACTION.match(path).groups()
    if action == "cancel":
        _call(handler, payments.cancel_order, project_root, order_id, user, ident.get("role"),
              owner=user)
    else:
        _call(handler, payments.request_refund, project_root, order_id, user, data.get("reason"))
