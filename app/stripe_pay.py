"""
stripe_pay.py — ชำระด้วยบัตร/PromptPay ผ่าน Stripe hosted Checkout (PCI SAQ-A: ข้อมูลบัตรไม่ผ่าน server เรา)

    create_checkout(root, username, plan, base_url) -> {"url", "order_id"}
        ราคาคิดฝั่ง server จากตารางแพ็กเกจเท่านั้น; pay_orders (pending) + stripe_orders (provider=stripe)
    handle_webhook(root, raw_body, sig_header) -> (status, body)
        ตรวจ Stripe-Signature บน raw body (HMAC-SHA256 "t.body", 5 นาที, constant-time)
        event id ซ้ำ = no-op (ตาราง stripe_events, migration 0016)
    refund(root, order_id, actor, role) -> เรียก Stripe refunds API แล้ว refunded

ค่าตั้ง (config.json / env): STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_MODE (test|live)
ไม่ตั้ง/ไม่ถูกต้อง = ปิด Stripe (ปุ่มซ่อน, API ตอบ 503) — PromptPay QR เดิมใช้ได้ตามปกติ
ห้าม log/คืนค่า key ใด ๆ; stdlib เท่านั้น (urllib)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

from app import config_manager, org_store, payments, promptpay
from app.payments import PaymentError
from app.rate_limit import RateLimiter

API_BASE = "https://api.stripe.com/v1"
TOLERANCE_S = 300
SESSION_TTL_S = 60 * 60            # Stripe session expires_at (min 30 min)
LOCAL_WINDOW_S = SESSION_TTL_S + 300
ACTOR = "stripe"
ACTOR_ROLE = "SYSTEM"
NOT_READY_MSG = "ยังไม่เปิดชำระผ่าน Stripe — เจ้าของระบบยังไม่ได้ตั้งค่า (ใช้ PromptPay QR แทนได้)"
CHECKOUT_LIMITER = RateLimiter(5, 60.0)   # ต่อผู้ใช้: 5 ครั้ง / นาที
PAID_TYPES = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
FAIL_TYPES = {"checkout.session.async_payment_failed": "failed",
              "checkout.session.expired": "cancelled"}


# ---------- config ----------

def _cfg(root: Path, name: str):
    v = config_manager.get_key(Path(root), name)
    return v.strip() if isinstance(v, str) and v.strip() else None


def _mode(root: Path) -> str:
    return "live" if (_cfg(root, "STRIPE_MODE") or "test").lower() == "live" else "test"


def secret_key(root: Path):
    """คืน secret key ที่ใช้ได้ หรือ None (sk_live_ ถูกปฏิเสธเว้นแต่ STRIPE_MODE=live)"""
    key = _cfg(root, "STRIPE_SECRET_KEY")
    if not key:
        return None
    if key.startswith("sk_live_") or key.startswith("rk_live_"):
        return key if _mode(root) == "live" else None
    if key.startswith("sk_test_") or key.startswith("rk_test_"):
        return key
    return None


def ready(root: Path) -> bool:
    return secret_key(root) is not None and _cfg(root, "STRIPE_WEBHOOK_SECRET") is not None


def _require_ready(root: Path) -> str:
    key = secret_key(root)
    if key is None or _cfg(root, "STRIPE_WEBHOOK_SECRET") is None:
        raise PaymentError(503, "stripe_not_configured", NOT_READY_MSG)
    return key


# ---------- HTTP (mocked in tests) ----------

def _http(method: str, url: str, form: dict, key: str, idem: str | None) -> dict:
    data = urllib.parse.urlencode(form).encode("ascii")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if idem:
        req.add_header("Idempotency-Key", idem)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # ไม่ส่งต่อข้อความดิบของ Stripe (อาจมีข้อมูลบัญชี) — เก็บแค่ status
        raise PaymentError(502, "stripe_error", f"Stripe ตอบกลับผิดพลาด ({e.code})") from None
    except (urllib.error.URLError, OSError, ValueError):
        raise PaymentError(502, "stripe_unreachable", "ติดต่อ Stripe ไม่ได้ ลองใหม่ภายหลัง") from None


def _call(key: str, path: str, form: dict, idem: str) -> dict:
    return _http("POST", API_BASE + path, form, key, idem)


# ---------- checkout ----------

def _stripe_row(conn, order_id):
    return conn.execute("SELECT order_id, session_id, session_url, payment_intent, state, refund_id"
                        " FROM stripe_orders WHERE order_id=?", (order_id,)).fetchone()


def is_stripe(root: Path, order_id: str) -> bool:
    return org_store.run_read(root, "SELECT 1 FROM stripe_orders WHERE order_id=?",
                              (order_id,), one=True) is not None


def _reserve(root: Path, username: str, plan: dict, satang: int, now: float) -> dict:
    """สร้าง/คืน order pending ของ stripe — {"order_id", "url"|None}"""

    def op(conn, actions):
        for row in conn.execute("SELECT order_id, plan, pay_deadline, status FROM pay_orders"
                                " WHERE username=? AND status='pending'", (username,)).fetchall():
            if row["pay_deadline"] <= now:
                continue  # หมดเวลาแล้ว — sweep จะยกเลิก
            srow = _stripe_row(conn, row["order_id"])
            if srow is not None and row["plan"] == plan["id"] and srow["session_url"]:
                return {"order_id": row["order_id"], "url": srow["session_url"]}
            raise PaymentError(409, "pending_exists",
                               "มีคำสั่งซื้อที่รอชำระอยู่แล้ว — ยกเลิกรายการเดิมก่อน")
        order_id = "ord_" + secrets.token_hex(8)
        conn.execute("INSERT INTO pay_orders(order_id, username, plan, amount_satang, status,"
                     " payload, created_at, pay_deadline, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (order_id, username, plan["id"], satang, "pending", None, now,
                      now + LOCAL_WINDOW_S, now))
        conn.execute("INSERT INTO stripe_orders(order_id, state, created_at, updated_at)"
                     " VALUES (?,?,?,?)", (order_id, "pending", now, now))
        payments._log(conn, order_id, None, "pending", username, "USER", now,
                      f"แพ็กเกจ {plan['id']} (Stripe)")
        return {"order_id": order_id, "url": None}

    return org_store.run_write(root, lambda c: op(c, []))


def create_checkout(root: Path, username: str, plan_id, base_url: str, now=None) -> dict:
    root = Path(root)
    if not username:
        raise PaymentError(401, "unauthorized", "ต้องเข้าสู่ระบบก่อนซื้อแพ็กเกจ")
    key = _require_ready(root)
    plan = payments.get_plan(root, plan_id) if isinstance(plan_id, str) else None
    if plan is None or not plan["buyable"]:
        raise PaymentError(400, "bad_plan", "ไม่มีแพ็กเกจนี้ให้ซื้อ")
    if not CHECKOUT_LIMITER.allow(username):
        raise PaymentError(429, "rate_limited", "เรียกชำระเงินถี่เกินไป รอสักครู่แล้วลองใหม่")
    now = float(now) if now is not None else time.time()
    satang = int(Decimal(promptpay.format_amount(plan["price_thb"])) * 100)
    res = _reserve(root, username, plan, satang, now)
    if res["url"]:
        return {"url": res["url"], "order_id": res["order_id"]}
    oid = res["order_id"]
    base = base_url.rstrip("/")
    form = {
        "mode": "payment",
        "payment_method_types[0]": "card",
        "payment_method_types[1]": "promptpay",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "thb",
        "line_items[0][price_data][unit_amount]": str(satang),
        "line_items[0][price_data][product_data][name]": f"LCA {plan['name']} (30 วัน)",
        "client_reference_id": oid,
        "metadata[order_id]": oid,
        "metadata[username]": username,
        "metadata[plan]": plan["id"],
        "success_url": f"{base}/plans?stripe=success&order={oid}",
        "cancel_url": f"{base}/plans?stripe=cancel&order={oid}",
        "expires_at": str(int(now + SESSION_TTL_S)),
    }
    try:
        sess = _call(key, "/checkout/sessions", form, idem=oid)
    except PaymentError:
        payments._change(root, oid, "cancelled", ACTOR, ACTOR_ROLE, now,
                         note="สร้าง Stripe session ไม่สำเร็จ")
        _set_state(root, oid, "cancelled", now)
        raise
    url, sid = sess.get("url"), sess.get("id")
    if not (isinstance(url, str) and url.startswith("https://") and isinstance(sid, str)):
        raise PaymentError(502, "stripe_error", "Stripe ตอบกลับไม่ถูกต้อง")
    org_store.run_write(root, lambda c: c.execute(
        "UPDATE stripe_orders SET session_id=?, session_url=?, updated_at=? WHERE order_id=?",
        (sid, url, now, oid)))
    return {"url": url, "order_id": oid}


def _set_state(root, oid, state, now, note=None, **extra) -> None:
    cols = {"state": state, "updated_at": now, **extra}
    if note is not None:
        cols["note"] = note
    sql = ", ".join(f"{k}=?" for k in cols)
    org_store.run_write(root, lambda c: c.execute(
        f"UPDATE stripe_orders SET {sql} WHERE order_id=?", (*cols.values(), oid)))


# ---------- webhook ----------

def verify_signature(raw: bytes, header, secret: str, now=None, tolerance=TOLERANCE_S) -> bool:
    if not isinstance(header, str) or not secret:
        return False
    ts, sigs = None, []
    for part in header.split(","):
        k, _, v = part.strip().partition("=")
        if k == "t":
            ts = v
        elif k == "v1":
            sigs.append(v)
    try:
        t = int(ts)
    except (TypeError, ValueError):
        return False
    now = time.time() if now is None else now
    if abs(now - t) > tolerance or not sigs:
        return False
    expected = hmac.new(secret.encode("utf-8"), f"{t}.".encode("ascii") + raw,
                        hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def _claim_event(root, eid, etype, oid, now) -> bool:
    def op(conn):
        cur = conn.execute("INSERT OR IGNORE INTO stripe_events(event_id, type, order_id, result,"
                           " received_at) VALUES (?,?,?,?,?)", (eid, etype, oid, "received", now))
        return cur.rowcount == 1
    return org_store.run_write(root, op)


def _event_result(root, eid, result) -> None:
    org_store.run_write(root, lambda c: c.execute(
        "UPDATE stripe_events SET result=? WHERE event_id=?", (result, eid)))


def handle_webhook(root: Path, raw: bytes, sig_header, now=None) -> tuple:
    root = Path(root)
    secret = _cfg(root, "STRIPE_WEBHOOK_SECRET")
    if not ready(root):
        return 503, {"error": NOT_READY_MSG, "code": "stripe_not_configured"}
    if not verify_signature(raw, sig_header, secret, now):
        return 400, {"error": "ลายเซ็น Stripe ไม่ถูกต้อง", "code": "bad_signature"}
    try:
        event = json.loads(raw.decode("utf-8"))
        eid, etype = event["id"], event["type"]
        obj = event["data"]["object"]
    except (ValueError, KeyError, TypeError):
        return 400, {"error": "event ไม่ถูกต้อง", "code": "bad_event"}
    if not isinstance(eid, str) or not isinstance(obj, dict):
        return 400, {"error": "event ไม่ถูกต้อง", "code": "bad_event"}
    if etype not in PAID_TYPES and etype not in FAIL_TYPES:
        return 200, {"received": True, "ignored": True}
    oid = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("order_id")
    now = float(now) if now is not None else time.time()
    if not _claim_event(root, eid, etype, oid if isinstance(oid, str) else None, now):
        return 200, {"received": True, "duplicate": True}
    result = _apply(root, etype, obj, oid, now)
    _event_result(root, eid, result)
    return 200, {"received": True, "result": result}


def _apply(root, etype, obj, oid, now) -> str:
    if not isinstance(oid, str):
        return "unknown_order"
    order = payments.get_order(root, oid)
    srow = org_store.run_read(root, "SELECT session_id, state FROM stripe_orders WHERE order_id=?",
                              (oid,), one=True)
    if order is None or srow is None:
        return "unknown_order"
    if srow["session_id"] and obj.get("id") and obj.get("id") != srow["session_id"]:
        _set_state(root, oid, "review", now, note="session id ไม่ตรง")
        return "review"
    if etype in FAIL_TYPES:
        if order["status"] == "pending":
            payments._change(root, oid, "cancelled", ACTOR, ACTOR_ROLE, now,
                             note=f"Stripe: {etype}")
            _set_state(root, oid, FAIL_TYPES[etype], now)
            return FAIL_TYPES[etype]
        return "ignored"
    if etype == "checkout.session.completed" and obj.get("payment_status") != "paid":
        return "awaiting_async"      # PromptPay: รอ async_payment_succeeded
    amount, currency = obj.get("amount_total"), obj.get("currency")
    if (isinstance(amount, bool) or amount != int(round(order["amount_thb"] * 100))
            or currency != "thb"):
        _set_state(root, oid, "review", now, note="ยอด/สกุลเงินไม่ตรงกับคำสั่งซื้อ")
        return "review"
    pi = obj.get("payment_intent") if isinstance(obj.get("payment_intent"), str) else None
    if order["status"] != "pending" and order["status"] not in payments._CONFIRMED:
        _set_state(root, oid, "review", now, note=f"ชำระแล้วแต่ order เป็น {order['status']}",
                   payment_intent=pi)
        return "review"
    try:
        res = payments._change(root, oid, "paid", ACTOR, ACTOR_ROLE, now,
                               noop_from=payments._CONFIRMED - {"paid"},
                               note="Stripe ยืนยันการชำระ")
        if res["order"]["status"] == "paid":
            payments._change(root, oid, "active", ACTOR, ACTOR_ROLE, now,
                             note=f"เปิดแพ็กเกจ {payments.PLAN_DAYS} วัน")
    except PaymentError:
        _set_state(root, oid, "review", now, note="ชำระแล้วแต่เปิดแพ็กเกจไม่ได้",
                   payment_intent=pi)
        return "review"
    _set_state(root, oid, "paid", now, payment_intent=pi)
    return "paid"


# ---------- refunds ----------

def refund(root: Path, order_id: str, actor: str, actor_role, now=None) -> dict:
    """ADMIN คืนเงิน order Stripe: เรียก refunds API (idempotent) → refunded + กลับเป็น free"""
    root = Path(root)
    payments._require_admin(order_id, root, actor, actor_role)
    key = _require_ready(root)
    now = float(now) if now is not None else time.time()
    order = payments.get_order(root, order_id)
    srow = org_store.run_read(root, "SELECT payment_intent, state FROM stripe_orders"
                                    " WHERE order_id=?", (order_id,), one=True)
    if order is None or srow is None:
        raise PaymentError(404, "not_found", "ไม่พบคำสั่งซื้อ")
    if order["status"] == "refunded":
        return {"order": order, "changed": False}
    if order["status"] not in ("paid", "active", "refund_requested") or not srow["payment_intent"]:
        raise PaymentError(409, "bad_transition",
                           f"คืนเงินไม่ได้ เพราะคำสั่งซื้ออยู่ในสถานะ {order['status']}")
    rf = _call(key, "/refunds", {"payment_intent": srow["payment_intent"],
                                 "metadata[order_id]": order_id}, idem="refund_" + order_id)
    if rf.get("status") not in ("succeeded", "pending"):
        raise PaymentError(502, "stripe_refund_failed", "Stripe คืนเงินไม่สำเร็จ")
    if order["status"] != "refund_requested":
        payments._change(root, order_id, "refund_requested", actor, actor_role, now,
                         note="ผู้ดูแลคืนเงินผ่าน Stripe")
    res = payments._change(root, order_id, "refunded", actor, actor_role, now,
                           note="คืนเงินผ่าน Stripe แล้ว")
    _set_state(root, order_id, "refunded", now, refund_id=str(rf.get("id") or ""))
    return res


def annotate(root: Path, orders: list) -> list:
    """เติม provider ให้รายการ order (stripe|promptpay) — ไม่มีข้อมูลลับ"""
    try:
        rows = org_store.run_read(root, "SELECT order_id, state FROM stripe_orders")
    except Exception:  # noqa: BLE001 — ตารางยังไม่มี = ไม่มี stripe order
        rows = []
    st = {r["order_id"]: r["state"] for r in rows}
    for o in orders:
        o["provider"] = "stripe" if o["order_id"] in st else "promptpay"
        if o["order_id"] in st:
            o["stripe_state"] = st[o["order_id"]]
    return orders
