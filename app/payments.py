"""
payments.py — แพ็กเกจรายเดือน + คำสั่งซื้อผ่าน PromptPay QR (ไม่มี payment gateway, ไม่มีค่าธรรมเนียมบุคคลที่สาม)

ลำดับงาน:
    ลูกค้า (USER) เลือกแพ็กเกจ → ได้ order สถานะ pending + payload PromptPay (มียอด) → สแกนโอน
    ADMIN เห็นเงินเข้าบัญชีจริง (นอกระบบ) → กดยืนยัน → paid → active (ขยายโควตา 30 วัน)
    ลูกค้าขอคืนเงินได้ (paid/active) → ADMIN คืนเงินเอง (นอกระบบ) แล้วกด refund / หรือปฏิเสธ

สถานะ (TRANSITIONS):
    pending -> paid -> active -> expired (ครบ 30 วัน / ถูกแทนที่ด้วยแพ็กเกจใหม่)
    pending -> cancelled (ลูกค้ายกเลิก หรือหมดเวลาชำระ 30 นาที — actor "system")
    paid|active -> refund_requested -> refunded | refund_rejected
ทุกการเปลี่ยนสถานะ: เช็คด้วย TRANSITIONS, idempotent (สถานะเดิม = no-op), บันทึก who/when
ลง pay_order_events และบันทึกเงินเข้า/ออกลง finance_ledger (record-only)

ข้อมูลอยู่ใน data/lca.db (migration 0013_payments) ผ่าน org_store.run_write (transaction เดียว
กับการปรับโควตา) — เปิดแพ็กเกจ = ตั้ง daily_limit ของ key tier free ของผู้ใช้ (org_plan_limits)

สมมติฐาน:
    - โควตาจริงของระบบนับเป็น request ต่อวัน → แพ็กเกจรายเดือนแปลงเป็น ceil(monthly_requests / 30)
      ต่อวัน; monthly_tokens แสดงเพื่อเปรียบเทียบเท่านั้น (ยังไม่ได้บังคับใช้)
    - ADMIN ยืนยัน/คืนเงิน order ของตัวเองไม่ได้ (แยกหน้าที่); CEO (เจ้าของ) ทำได้
    - ห้ามมี pending ค้างเกิน 1 order ต่อผู้ใช้ (กดซื้อแพ็กเกจเดิมซ้ำ = ได้ order เดิม)
"""

from __future__ import annotations

import json
import math
import secrets
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app import config_manager, db, finance_ledger, org_store, promptpay

PAY_WINDOW_S = 30 * 60          # pending ต้องชำระภายใน 30 นาที
PLAN_DAYS = 30                  # แพ็กเกจมีอายุ 30 วันนับจากยืนยันการชำระ
SYSTEM_ACTOR = "system"
PLAN_ORDER = ("free", "plus", "pro", "max")
MAX_REASON = 500

# !! PLACEHOLDER !! ราคาและโควตาด้านล่างเป็นค่าตัวอย่างเท่านั้น — เจ้าของระบบต้องตั้งราคาจริงเอง
# ใน config.json key "PLANS" เช่น {"plus": {"price_thb": 149, "monthly_requests": 9000}}
# (field ที่ไม่ระบุ/ค่าไม่ถูกต้อง = ใช้ค่า placeholder นี้). free = โควตาฟรีรายวันปัจจุบัน
DEFAULT_PLANS = {
    "free": {"name": "Free", "price_thb": 0,
             "monthly_requests": org_store.TIER_DAILY_LIMIT["free"] * 30,
             "monthly_tokens": 300_000},                                         # PLACEHOLDER
    "plus": {"name": "Plus", "price_thb": 99, "monthly_requests": 6_000,         # PLACEHOLDER
             "monthly_tokens": 3_000_000},
    "pro": {"name": "Pro", "price_thb": 299, "monthly_requests": 24_000,         # PLACEHOLDER
            "monthly_tokens": 12_000_000},
    "max": {"name": "Max", "price_thb": 799, "monthly_requests": 90_000,         # PLACEHOLDER
            "monthly_tokens": 45_000_000},
}

TRANSITIONS = {
    "pending": {"paid", "cancelled"},
    "paid": {"active", "refund_requested"},
    "active": {"refund_requested", "expired"},
    "refund_requested": {"refunded", "refund_rejected"},
    "cancelled": set(), "refunded": set(), "refund_rejected": set(), "expired": set(),
}
# สถานะที่แปลว่า "เคยยืนยันการชำระแล้ว" — confirm ซ้ำ = no-op
_CONFIRMED = {"paid", "active", "refund_requested", "refunded", "refund_rejected", "expired"}

_ORDER_COLS = ("order_id, username, plan, amount_satang, status, payload, ledger_id,"
               " refund_ledger_id, refund_reason, created_at, pay_deadline, paid_at,"
               " active_until, updated_at")


class PaymentError(Exception):
    """ข้อผิดพลาดที่แปลงเป็น HTTP ได้ตรง ๆ: status + code + message (ภาษาไทย)"""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def body(self) -> dict:
        return {"error": self.message, "code": self.code}


# ---------- plans ----------

def _num(value, integer: bool):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    if not d.is_finite() or d < 0:
        return None
    return int(d) if integer else float(d.quantize(Decimal("0.01")))


def _config_plans(project_root: Path) -> dict:
    raw = config_manager.get_key(Path(project_root), "PLANS")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    return raw if isinstance(raw, dict) else {}


def _merge_plan(pid: str, override) -> dict:
    plan = dict(DEFAULT_PLANS[pid])
    if isinstance(override, dict):
        for field, integer in (("price_thb", False), ("monthly_requests", True),
                               ("monthly_tokens", True)):
            v = _num(override.get(field), integer)
            if v is not None:
                plan[field] = v
        name = override.get("name")
        if isinstance(name, str) and name.strip():
            plan["name"] = name.strip()[:40]
    plan["id"] = pid
    if pid == "free":
        plan["price_thb"] = 0
        plan["daily_limit"] = org_store.TIER_DAILY_LIMIT["free"]
        plan["buyable"] = False
    else:
        plan["daily_limit"] = math.ceil(plan["monthly_requests"] / PLAN_DAYS)
        plan["buyable"] = plan["price_thb"] > 0 and plan["monthly_requests"] > 0
    return plan


def load_plans(project_root: Path) -> list:
    """แพ็กเกจทั้งหมด (free, plus, pro, max) + ราคา/1,000 requests + โน้ต "ประหยัดกว่า" """
    cfg = _config_plans(project_root)
    plans = [_merge_plan(pid, cfg.get(pid)) for pid in PLAN_ORDER]
    prev = None
    for p in plans:
        p["price_per_1k"] = None
        p["savings_pct"] = None
        p["savings_note"] = None
        if not p["buyable"]:
            continue
        p["price_per_1k"] = round(p["price_thb"] / (p["monthly_requests"] / 1000), 2)
        if prev is not None and prev["price_per_1k"]:
            pct = math.floor((1 - p["price_per_1k"] / prev["price_per_1k"]) * 100 + 1e-9)
            if pct >= 1:
                p["savings_pct"] = pct
                p["savings_note"] = f"ประหยัดกว่า {prev['name']} {pct}% (ราคาต่อ 1,000 requests)"
        prev = p
    return plans


def get_plan(project_root: Path, plan_id) -> dict | None:
    return next((p for p in load_plans(project_root) if p["id"] == plan_id), None)


def _promptpay_id(project_root: Path):
    value = config_manager.get_key(Path(project_root), "PROMPTPAY_ID")
    return value.strip() if isinstance(value, str) and value.strip() else None


def promptpay_ready(project_root: Path) -> bool:
    """ตั้ง PROMPTPAY_ID ถูกรูปแบบแล้วหรือยัง (ไม่คืนเลขจริง)"""
    pid = _promptpay_id(project_root)
    if pid is None:
        return False
    try:
        promptpay.normalize_target(pid)
    except ValueError:
        return False
    return True


# ---------- rows ----------

def _to_order(row) -> dict:
    d = dict(row)
    d["amount_thb"] = d.pop("amount_satang") / 100
    if d["status"] != "pending":
        d["payload"] = None  # QR ใช้ได้เฉพาะตอนรอชำระ
    return d


def _fetch(conn, order_id: str):
    return conn.execute(f"SELECT {_ORDER_COLS} FROM pay_orders WHERE order_id=?",
                        (order_id,)).fetchone()


def _log(conn, order_id, frm, to, actor, role, now, note=None) -> None:
    conn.execute("INSERT INTO pay_order_events(order_id, from_status, to_status, actor,"
                 " actor_role, note, at) VALUES (?,?,?,?,?,?,?)",
                 (order_id, frm, to, actor or "?", role, note, now))


def _set(root, conn, row, to: str, actor, role, now, note=None, **extra) -> dict:
    """เปลี่ยนสถานะแบบ compare-and-set + side effect ของปลายทาง + log; คืน action ให้ ledger"""
    frm = row["status"]
    if to not in TRANSITIONS[frm]:
        raise PaymentError(409, "bad_transition", f"เปลี่ยนสถานะจาก {frm} เป็น {to} ไม่ได้")
    if to == "paid":
        extra.setdefault("paid_at", now)
    if to == "active":
        extra["active_until"] = now + PLAN_DAYS * 86400
    cols = {"status": to, "updated_at": now, **extra}
    sql = ", ".join(f"{k}=?" for k in cols)
    cur = conn.execute(f"UPDATE pay_orders SET {sql} WHERE order_id=? AND status=?",
                       (*cols.values(), row["order_id"], frm))
    if cur.rowcount != 1:  # pragma: no cover - protected by BEGIN IMMEDIATE
        raise PaymentError(409, "conflict", "สถานะคำสั่งซื้อเปลี่ยนไปแล้ว ลองใหม่")
    _log(conn, row["order_id"], frm, to, actor, role, now, note)
    if to == "active":
        _activate_plan(root, conn, row, actor, role, now, cols["active_until"])
    elif to in ("refunded", "expired"):
        org_store.clear_plan_limit_in(conn, row["username"], row["order_id"])
    return {"order_id": row["order_id"], "to": to, "ledger_id": row["ledger_id"],
            "amount": row["amount_satang"] / 100, "username": row["username"],
            "plan": row["plan"], "actor": actor}


def _activate_plan(root, conn, row, actor, role, now, until) -> None:
    # แพ็กเกจใหม่แทนที่ของเดิมที่ยัง active อยู่ (โควตาไม่ซ้อนกัน)
    olds = conn.execute(f"SELECT {_ORDER_COLS} FROM pay_orders WHERE username=? AND"
                        " status='active' AND order_id<>?",
                        (row["username"], row["order_id"])).fetchall()
    for old in olds:
        _set(root, conn, old, "expired", actor, role, now, note=f"แทนที่ด้วย {row['order_id']}")
    plan = get_plan(root, row["plan"])
    if plan is None:
        raise PaymentError(409, "bad_plan", f"ไม่พบแพ็กเกจ {row['plan']} ในการตั้งค่าปัจจุบัน")
    org_store.set_plan_limit_in(conn, row["username"], row["plan"], plan["daily_limit"],
                                row["order_id"], until)


def _expire_due(root, conn, row, now):
    """pending ที่เลยกำหนดชำระ → cancelled โดย system; คืน (row ใหม่, action|None)"""
    if row["status"] == "pending" and row["pay_deadline"] <= now:
        act = _set(root, conn, row, "cancelled", SYSTEM_ACTOR, None, now, note="หมดเวลาชำระ 30 นาที")
        return _fetch(conn, row["order_id"]), act
    return row, None


# ---------- ledger (finance.db, record-only) ----------

def _ledger_after(project_root: Path, actions: list) -> None:
    """บันทึกเงินลง finance_ledger หลัง commit — ล้มเหลว = warn (order ยังถูกต้อง)"""
    for a in actions:
        if a is None:
            continue
        try:
            note = f"order {a['order_id']} {a['plan']} ของ {a['username']} — โดย {a['actor']}"
            if a["to"] == "pending":
                e = finance_ledger.record_entry(project_root, a["amount"], "in", note=note,
                                                category="plan_sale", status="pending")
                org_store.run_write(project_root, lambda c: c.execute(
                    "UPDATE pay_orders SET ledger_id=? WHERE order_id=?", (e["id"], a["order_id"])))
            elif a["to"] in ("paid", "cancelled") and a["ledger_id"]:
                finance_ledger.set_status(project_root, a["ledger_id"],
                                          "received" if a["to"] == "paid" else "cancelled")
            elif a["to"] == "refunded":
                e = finance_ledger.record_entry(project_root, a["amount"], "out", note=note,
                                                category="plan_refund", status="paid")
                org_store.run_write(project_root, lambda c: c.execute(
                    "UPDATE pay_orders SET refund_ledger_id=? WHERE order_id=?",
                    (e["id"], a["order_id"])))
        except Exception as exc:  # noqa: BLE001 — ledger ต้องไม่ทำให้ order พัง
            print(f"[payments][warn] บันทึก ledger ไม่สำเร็จ ({a['order_id']} -> {a['to']}): {exc}")


def _run(project_root: Path, fn):
    """รัน fn(conn, actions) ใน write txn เดียว แล้วค่อยลง ledger"""
    actions: list = []
    result = org_store.run_write(project_root, lambda conn: fn(conn, actions))
    _ledger_after(Path(project_root), actions)
    return result


def _now(now) -> float:
    return float(now) if now is not None else time.time()


# ---------- orders ----------

def create_order(project_root: Path, username: str, plan_id, now=None) -> dict:
    """สร้าง order pending + payload PromptPay — {"order", "changed"}"""
    now = _now(now)
    if not username:
        raise PaymentError(401, "unauthorized", "ต้องเข้าสู่ระบบก่อนซื้อแพ็กเกจ")
    plan = get_plan(project_root, plan_id) if isinstance(plan_id, str) else None
    if plan is None or not plan["buyable"]:
        raise PaymentError(400, "bad_plan", "ไม่มีแพ็กเกจนี้ให้ซื้อ")
    pp_id = _promptpay_id(project_root)
    if pp_id is None:
        raise PaymentError(409, "promptpay_not_configured",
                           "เจ้าของระบบยังไม่ได้ตั้งค่า PROMPTPAY_ID ใน config.json — ยังซื้อแพ็กเกจไม่ได้")
    try:
        payload = promptpay.build_payload(pp_id, plan["price_thb"])
    except ValueError:
        raise PaymentError(409, "promptpay_invalid",
                           "PROMPTPAY_ID ใน config.json รูปแบบไม่ถูกต้อง — เจ้าของระบบต้องแก้ก่อน") from None
    satang = int(Decimal(promptpay.format_amount(plan["price_thb"])) * 100)

    def op(conn, actions):
        pend = conn.execute(f"SELECT {_ORDER_COLS} FROM pay_orders WHERE username=? AND"
                            " status='pending'", (username,)).fetchall()
        for row in pend:
            row, act = _expire_due(project_root, conn, row, now)
            actions.append(act)
            if row["status"] != "pending":
                continue
            if row["plan"] == plan["id"]:
                return {"order": _to_order(row), "changed": False}
            raise PaymentError(409, "pending_exists",
                               "มีคำสั่งซื้อที่รอชำระอยู่แล้ว — ยกเลิกรายการเดิมก่อนเลือกแพ็กเกจอื่น")
        order_id = "ord_" + secrets.token_hex(8)
        conn.execute("INSERT INTO pay_orders(order_id, username, plan, amount_satang, status,"
                     " payload, created_at, pay_deadline, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (order_id, username, plan["id"], satang, "pending", payload, now,
                      now + PAY_WINDOW_S, now))
        _log(conn, order_id, None, "pending", username, "USER", now, f"แพ็กเกจ {plan['id']}")
        actions.append({"order_id": order_id, "to": "pending", "ledger_id": None,
                        "amount": satang / 100, "username": username, "plan": plan["id"],
                        "actor": username})
        return {"order": _to_order(_fetch(conn, order_id)), "changed": True}

    res = _run(project_root, op)
    if res["changed"]:
        res["order"] = get_order(project_root, res["order"]["order_id"])
    return res


def _change(project_root, order_id, to, actor, role, now, *, owner=None, note=None,
            noop_from=(), extra=None) -> dict:
    """โครงกลางของทุก action: หา order (+เช็คเจ้าของ) → หมดเวลา? → no-op? → เปลี่ยนสถานะ"""
    now = _now(now)
    if not isinstance(order_id, str) or not order_id:
        raise PaymentError(404, "not_found", "ไม่พบคำสั่งซื้อ")

    def expire(conn, actions):
        row = _fetch(conn, order_id)
        if row is not None:
            actions.append(_expire_due(project_root, conn, row, now)[1])

    _run(project_root, expire)  # หมดเวลาแล้วต้อง cancelled จริง แม้ action ถัดไปจะถูกปฏิเสธ

    def op(conn, actions):
        row = _fetch(conn, order_id)
        if row is None or (owner is not None and row["username"] != owner):
            raise PaymentError(404, "not_found", "ไม่พบคำสั่งซื้อ")
        if row["status"] == to or row["status"] in noop_from:
            return {"order": _to_order(row), "changed": False}
        if to not in TRANSITIONS[row["status"]]:
            raise PaymentError(409, "bad_transition",
                               f"ทำรายการนี้ไม่ได้ เพราะคำสั่งซื้ออยู่ในสถานะ {row['status']}")
        actions.append(_set(project_root, conn, row, to, actor, role, now, note, **(extra or {})))
        return {"order": _to_order(_fetch(conn, order_id)), "changed": True}

    return _run(project_root, op)


def transition(project_root: Path, order_id: str, to: str, actor: str, actor_role,
               now=None, note=None) -> dict:
    """เปลี่ยนสถานะตรง ๆ (ตรวจ TRANSITIONS) — ใช้ภายใน/ทดสอบ; API ใช้ฟังก์ชันเฉพาะด้านล่าง"""
    if to not in TRANSITIONS:
        raise PaymentError(400, "bad_status", f"ไม่มีสถานะ {to}")
    return _change(project_root, order_id, to, actor, actor_role, now, note=note)


def _require_admin(order_id, project_root, actor, actor_role) -> None:
    if not org_store.role_at_least(actor_role or "", "ADMIN"):
        raise PaymentError(403, "forbidden", "ต้องเป็น ADMIN ขึ้นไป")
    if actor_role != "CEO":
        o = get_order(project_root, order_id)
        if o is not None and o["username"] == actor:
            raise PaymentError(403, "own_order", "ห้ามยืนยัน/คืนเงินคำสั่งซื้อของตัวเอง — ให้ผู้ดูแลคนอื่นทำ")


def confirm_paid(project_root: Path, order_id: str, actor: str, actor_role, now=None) -> dict:
    """ADMIN ยืนยันว่าได้รับเงิน → paid → active ใน transaction เดียว; ยืนยันซ้ำ = no-op"""
    _require_admin(order_id, project_root, actor, actor_role)
    now = _now(now)
    res = _change(project_root, order_id, "paid", actor, actor_role, now,
                  noop_from=_CONFIRMED - {"paid"}, note="ยืนยันรับเงินแล้ว")
    if res["order"]["status"] == "paid":
        act = _change(project_root, order_id, "active", actor, actor_role, now,
                      note=f"เปิดแพ็กเกจ {PLAN_DAYS} วัน")
        act["changed"] = act["changed"] or res["changed"]
        return act
    return res


def cancel_order(project_root: Path, order_id: str, actor: str, actor_role, owner=None,
                 now=None) -> dict:
    """ยกเลิก pending (ลูกค้าเจ้าของ order; owner=None = ADMIN ยกเลิกแทน)"""
    if owner is None and not org_store.role_at_least(actor_role or "", "ADMIN"):
        raise PaymentError(403, "forbidden", "ยกเลิกได้เฉพาะคำสั่งซื้อของตัวเอง")
    return _change(project_root, order_id, "cancelled", actor, actor_role, now, owner=owner,
                   note="ยกเลิกโดยลูกค้า" if owner else "ยกเลิกโดยผู้ดูแล")


def request_refund(project_root: Path, order_id: str, owner: str, reason, now=None) -> dict:
    """ลูกค้าขอคืนเงิน order ของตัวเองที่ paid/active (ต้องมีเหตุผล)"""
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        raise PaymentError(400, "reason_required", "ต้องระบุเหตุผลที่ขอคืนเงิน")
    return _change(project_root, order_id, "refund_requested", owner, "USER", now, owner=owner,
                   note=reason[:MAX_REASON], extra={"refund_reason": reason[:MAX_REASON]})


def refund(project_root: Path, order_id: str, actor: str, actor_role, now=None) -> dict:
    """ADMIN คืนเงินแล้ว (โอนคืนนอกระบบ) → refunded + กลับเป็น free"""
    _require_admin(order_id, project_root, actor, actor_role)
    return _change(project_root, order_id, "refunded", actor, actor_role, now,
                   note="คืนเงินแล้ว")


def reject_refund(project_root: Path, order_id: str, actor: str, actor_role, now=None) -> dict:
    _require_admin(order_id, project_root, actor, actor_role)
    return _change(project_root, order_id, "refund_rejected", actor, actor_role, now,
                   note="ปฏิเสธการคืนเงิน")


def get_order(project_root: Path, order_id: str) -> dict | None:
    row = org_store.run_read(project_root, f"SELECT {_ORDER_COLS} FROM pay_orders"
                                           " WHERE order_id=?", (order_id,), one=True)
    return _to_order(row) if row else None


def list_orders(project_root: Path, username=None, status=None, limit: int = 200,
                with_events: bool = False) -> list:
    where, params = [], []
    if username is not None:
        where.append("username=?")
        params.append(username)
    if status:
        if status not in TRANSITIONS:
            raise PaymentError(400, "bad_status", f"ไม่มีสถานะ {status}")
        where.append("status=?")
        params.append(status)
    sql = f"SELECT {_ORDER_COLS} FROM pay_orders"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    orders = [_to_order(r) for r in org_store.run_read(project_root, sql, tuple(params))]
    if with_events:
        for o in orders:
            o["events"] = list_events(project_root, o["order_id"])
    return orders


def list_events(project_root: Path, order_id: str) -> list:
    rows = org_store.run_read(project_root, "SELECT from_status, to_status, actor, actor_role,"
                                            " note, at FROM pay_order_events WHERE order_id=?"
                                            " ORDER BY id", (order_id,))
    return [dict(r) for r in rows]


# ---------- expiry ----------

def sweep(project_root: Path, now=None) -> dict:
    """หมดเวลาชำระ (pending > 30 นาที) → cancelled; แพ็กเกจครบ 30 วัน → expired + กลับเป็น free"""
    now = _now(now)

    def op(conn, actions):
        n_pending = n_active = 0
        for row in conn.execute(f"SELECT {_ORDER_COLS} FROM pay_orders WHERE status='pending'"
                                " AND pay_deadline <= ?", (now,)).fetchall():
            actions.append(_expire_due(project_root, conn, row, now)[1])
            n_pending += 1
        for row in conn.execute(f"SELECT {_ORDER_COLS} FROM pay_orders WHERE status='active'"
                                " AND active_until <= ?", (now,)).fetchall():
            actions.append(_set(project_root, conn, row, "expired", SYSTEM_ACTOR, None, now,
                                note=f"ครบ {PLAN_DAYS} วัน"))
            n_active += 1
        # แพ็กเกจของ order ที่อยู่ระหว่าง/หลังขอคืนเงิน (ไม่ใช่ active) ก็หมดอายุตามเวลาเดียวกัน
        n_limits = len(org_store.expire_plan_limits_in(conn, now))
        return {"pending_cancelled": n_pending, "plans_expired": n_active + n_limits}

    return _run(project_root, op)


_LAST_SWEEP: dict = {}
_SWEEP_LOCK = threading.Lock()
SWEEP_EVERY_S = 60


def maybe_sweep(project_root: Path) -> None:
    """เรียกจาก server ได้ทุก request: sweep จริงไม่เกิน 1 ครั้ง/นาที/โปรเจกต์; ไม่ raise"""
    key = str(project_root)
    now = time.time()
    if not db.db_path(project_root).exists():
        return  # ยังไม่มีฐานข้อมูล = ไม่มีอะไรหมดอายุ (ไม่สร้างไฟล์โดยไม่จำเป็น)
    with _SWEEP_LOCK:
        if now - _LAST_SWEEP.get(key, 0) < SWEEP_EVERY_S:
            return
        _LAST_SWEEP[key] = now
    try:
        sweep(project_root, now)
    except Exception as exc:  # noqa: BLE001 — การ sweep ล้มต้องไม่ล้ม request หลัก
        print(f"[payments][warn] sweep ไม่สำเร็จ: {exc}")


def _force_status(project_root: Path, order_id: str, status: str) -> None:
    """test helper only: ตั้งสถานะตรง ๆ โดยไม่ผ่าน state machine / ไม่ log"""
    org_store.run_write(project_root, lambda c: c.execute(
        "UPDATE pay_orders SET status=? WHERE order_id=?", (status, order_id)))
