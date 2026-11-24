"""
org_store.py — ระบบองค์กร: ผู้ใช้ (User) + บทบาท (Role) + API key แบบมี tier/quota
เก็บเป็น JSON ต่อโปรเจกต์ (ไฟล์ org.json ที่ project_root)

ทำไมต้องมี:
    server.py เดิมใช้ token เดี่ยวตัวเดียว (ใครมี token ก็ทำได้ทุกอย่าง) ไม่พอสำหรับ
    องค์กรที่มีหลายคน/หลายสิทธิ์ โมดูลนี้เพิ่ม "ใครเป็นใคร" + "ทำอะไรได้บ้าง" + โควตา
    การใช้ API (free/paid) โดยยังคงสไตล์ stdlib ล้วนเหมือนโมดูลอื่นในโปรเจกต์

บทบาท (สูง -> ต่ำ):   CEO > ADMIN > USER
    USER  : แชท/ใช้งาน AI ได้ (กินโควตาตาม tier ของ API key)
    ADMIN : ทุกอย่างของ USER + สร้าง/ปิด user ระดับ USER + ออก/ยกเลิก API key
    CEO   : ทุกอย่างของ ADMIN + ตั้ง ADMIN + ดูภาพรวมทั้งองค์กร

ความปลอดภัย (Rule ข้อ 23 — secret ห้าม commit/ห้าม print เต็มๆ):
    - รหัสผ่านเก็บเป็น pbkdf2_hmac(sha256) + salt สุ่ม ไม่เคยเก็บ plaintext
    - API key สุ่มด้วย secrets, เก็บเฉพาะ sha256 hash + prefix ไว้โชว์ระบุตัว
    - คืนค่า key เต็มๆ "ครั้งเดียวตอนสร้าง" เท่านั้น หลังจากนั้นกู้คืนไม่ได้ (by design)
    - org.json ต้องอยู่ใน .gitignore เสมอ (เหมือน config.json/todos.json)

Interface หลักที่ server.py เรียกใช้:
    bootstrap_needed(project_root) -> bool
    create_user(project_root, username, password, role, created_by_role) -> dict
    verify_password(project_root, username, password) -> dict | None
    set_user_active(project_root, username, active, actor_role) -> bool
    list_users(project_root) -> list[dict]            # ไม่คืน hash

    create_api_key(project_root, owner, tier, actor_role) -> dict   # มี "key" เต็มครั้งเดียว
    verify_api_key(project_root, raw_key) -> dict | None            # คืน record (ไม่มี hash)
    revoke_api_key(project_root, key_id, actor_role) -> bool
    consume_quota(project_root, key_id) -> tuple[bool, int]         # (ผ่านไหม, เหลือเท่าไร)
    refund_quota(project_root, key_id) -> RefundResult               # คืน 1 ที่จองไว้เมื่อแชทล้ม
    list_api_keys(project_root) -> list[dict]                       # ไม่คืน key/hash
"""

import enum
import functools
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from datetime import date, datetime
from pathlib import Path

ORG_FILE_NAME = "org.json"

# server รันบน ThreadingHTTPServer → การ read-modify-write org.json ต้องกันชนกัน
# ไม่งั้น request พร้อมกันทำให้ quota เพี้ยนหรือเขียนทับกันหาย (lost update)
_lock = threading.RLock()


def _synchronized(fn):
    """ครอบฟังก์ชันที่ทำ read-modify-write org.json ให้ทำทีละตัว (atomic ต่อ process)"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return wrapper

# ลำดับชั้นบทบาท — ตัวเลขมากกว่า = สิทธิ์สูงกว่า
ROLE_LEVEL = {"USER": 1, "ADMIN": 2, "CEO": 3}
VALID_ROLES = set(ROLE_LEVEL)

# tier ของ API key -> โควตาต่อวัน (จำนวน request). 0 = ไม่จำกัด (paid)
TIER_DAILY_LIMIT = {
    "free": 100,   # ฟรี: จำกัดกันคนยิงถล่ม
    "paid": 0,     # จ่ายเงิน/ซื้อ API: ไม่จำกัดโควตารายวัน
}
VALID_TIERS = set(TIER_DAILY_LIMIT)

_PBKDF2_ITERATIONS = 200_000
_KEY_PREFIX = "lca"          # รูปแบบ key: lca_<tier>_<random>
_KEY_PREFIX_SHOW = 12        # จำนวนอักษรหัว key ที่เก็บไว้โชว์ระบุตัว (ปลอดภัย)


# ---------- storage (JSON ต่อโปรเจกต์ ตาม pattern todo_store/config_manager) ----------

def _org_path(project_root: Path) -> Path:
    return project_root / ORG_FILE_NAME


def _load(project_root: Path) -> dict:
    """อ่าน org.json — ไม่มีไฟล์คืนโครงว่าง, ไฟล์เสียเตือนแล้วคืนโครงว่าง (ไม่ crash)"""
    path = _org_path(project_root)
    if not path.exists():
        return {"users": {}, "api_keys": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[org][warn] อ่าน {ORG_FILE_NAME} ไม่ได้: {e} — ถือว่าว่างเปล่า")
        return {"users": {}, "api_keys": {}}
    if not isinstance(data, dict):
        print(f"[org][warn] {ORG_FILE_NAME} รูปแบบผิด — ถือว่าว่างเปล่า")
        return {"users": {}, "api_keys": {}}
    data.setdefault("users", {})
    data.setdefault("api_keys", {})
    return data


_REPLACE_ATTEMPTS = 5      # Windows: os.replace may hit a transient PermissionError
_REPLACE_BACKOFF_S = 0.02  # when another reader holds org.json open


def _replace_with_retry(src: str, dst: Path) -> None:
    """os.replace with a few retries on PermissionError (Windows sharing violation)."""
    for i in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S * (i + 1))


def _save(project_root: Path, data: dict) -> bool:
    """เขียนแบบ atomic (temp + os.replace) — คืน True ถ้าบันทึกสำเร็จ, False ถ้าล้ม

    ผู้อ่านพร้อมกันเห็นไฟล์เก่าหรือใหม่เต็มๆ เสมอ ไม่เห็นไฟล์ครึ่งๆ กลางๆ.
    ผู้เรียกที่ความถูกต้องสำคัญ (เช่น consume_quota) ต้องเช็คผลนี้ ห้ามถือว่าสำเร็จเอง
    """
    path = _org_path(project_root)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".org.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _replace_with_retry(tmp, path)
        except OSError:
            # เก็บกวาด temp ถ้าเขียน/replace ไม่สำเร็จ
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        # fail loud (Rule 14) แต่ไม่ทำโปรแกรมพัง — คืน False ให้ผู้เรียกรู้ว่า state ไม่ถูกบันทึก
        print(f"[org][error] เขียน {ORG_FILE_NAME} ไม่ได้: {e}")
        return False
    return True


# ---------- password hashing ----------

def _hash_password(password: str, salt: str | None = None) -> str:
    """คืนสตริง 'pbkdf2_sha256$iterations$salt$hash' — เก็บลงไฟล์ได้ตรงๆ"""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             salt.encode("utf-8"), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def _verify_password_hash(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, _ = stored.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = _hash_password(password, salt)
    # compare_digest กัน timing attack
    return hmac.compare_digest(candidate, stored)


# ---------- api key hashing ----------

def _hash_key(raw_key: str) -> str:
    # key เป็น random entropy สูง → sha256 ครั้งเดียวพอ (ไม่ต้อง pbkdf2 แบบรหัสผ่าน)
    return "sha256:" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# ---------- role helpers ----------

def role_at_least(role: str, required: str) -> bool:
    """True ถ้า role มีสิทธิ์ >= required (ใช้เช็ค permission ที่ server)"""
    return ROLE_LEVEL.get(role, 0) >= ROLE_LEVEL.get(required, 99)


# ---------- users ----------

def bootstrap_needed(project_root: Path) -> bool:
    """ยังไม่มี user เลย = ต้อง bootstrap (อนุญาตให้สร้าง CEO คนแรกได้โดยไม่ต้องมีสิทธิ์)"""
    return len(_load(project_root)["users"]) == 0


@_synchronized
def create_user(project_root: Path, username: str, password: str, role: str,
                created_by_role: str | None = None) -> dict:
    """สร้าง user ใหม่ คืน record (ไม่มี hash)

    กติกาสิทธิ์:
      - ถ้ายังไม่มี user เลย (bootstrap) → สร้าง CEO คนแรกได้เท่านั้น ไม่ต้องมีสิทธิ์
      - หลังจากนั้นต้องมี actor: ADMIN สร้างได้ถึงระดับ USER, CEO สร้างได้ทุกระดับ
    raise ValueError ถ้า input ผิด/ชื่อซ้ำ/สิทธิ์ไม่พอ (ผู้เรียกแปลงเป็น HTTP error)
    """
    username = (username or "").strip()
    if not username:
        raise ValueError("ต้องระบุ username")
    if not password or len(password) < 8:
        raise ValueError("รหัสผ่านต้องยาวอย่างน้อย 8 ตัวอักษร")
    if role not in VALID_ROLES:
        raise ValueError(f"role ไม่ถูกต้อง: {role} (ต้องเป็น {sorted(VALID_ROLES)})")

    data = _load(project_root)
    if username in data["users"]:
        raise ValueError(f"มี user ชื่อ {username} อยู่แล้ว")

    is_bootstrap = len(data["users"]) == 0
    if is_bootstrap:
        if role != "CEO":
            raise ValueError("user คนแรกต้องเป็น CEO (bootstrap)")
    else:
        if created_by_role is None:
            raise ValueError("ต้องมีสิทธิ์ผู้สร้าง (actor) เพื่อสร้าง user")
        if not role_at_least(created_by_role, "ADMIN"):
            raise ValueError("ต้องเป็น ADMIN ขึ้นไปจึงสร้าง user ได้")
        # ห้ามสร้าง role ที่สูงกว่าหรือเท่ากับตัวเอง (ADMIN สร้าง CEO/ADMIN ไม่ได้)
        if ROLE_LEVEL[role] >= ROLE_LEVEL[created_by_role] and created_by_role != "CEO":
            raise ValueError(f"{created_by_role} สร้าง role {role} ไม่ได้ (สิทธิ์ไม่พอ)")

    data["users"][username] = {
        "role": role,
        "password": _hash_password(password),
        "active": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(project_root, data)
    return {"username": username, "role": role, "active": True}


def verify_password(project_root: Path, username: str, password: str) -> dict | None:
    """ตรวจ username/password — คืน record (ไม่มี hash) ถ้าถูกและ active, ไม่งั้น None"""
    data = _load(project_root)
    user = data["users"].get(username)
    if not user or not user.get("active", False):
        return None
    if not _verify_password_hash(password, user.get("password", "")):
        return None
    return {"username": username, "role": user["role"], "active": True}


@_synchronized
def set_user_active(project_root: Path, username: str, active: bool, actor_role: str) -> bool:
    """เปิด/ปิด user — ต้องเป็น ADMIN ขึ้นไป คืน True ถ้าเจอและแก้สำเร็จ"""
    if not role_at_least(actor_role, "ADMIN"):
        raise ValueError("ต้องเป็น ADMIN ขึ้นไปจึงเปิด/ปิด user ได้")
    data = _load(project_root)
    user = data["users"].get(username)
    if not user:
        return False
    # ADMIN ปิด CEO ไม่ได้
    if ROLE_LEVEL[user["role"]] >= ROLE_LEVEL["CEO"] and actor_role != "CEO":
        raise ValueError("ADMIN ปิดบัญชี CEO ไม่ได้")
    user["active"] = bool(active)
    _save(project_root, data)
    return True


def list_users(project_root: Path) -> list:
    """คืนรายชื่อ user (ไม่มี password hash) — เรียงตามชื่อ"""
    data = _load(project_root)
    out = []
    for name, u in sorted(data["users"].items()):
        out.append({
            "username": name,
            "role": u.get("role"),
            "active": u.get("active", False),
            "created_at": u.get("created_at"),
        })
    return out


# ---------- api keys ----------

def _today_str() -> str:
    return date.today().isoformat()


@_synchronized
def create_api_key(project_root: Path, owner: str, tier: str, actor_role: str) -> dict:
    """ออก API key ใหม่ให้ owner — ต้องเป็น ADMIN ขึ้นไป

    คืน dict ที่มี field 'key' = ค่าเต็ม (โชว์ครั้งเดียวเท่านั้น!) + metadata
    หลังจากนี้ระบบเก็บแค่ hash กู้ค่าเต็มคืนไม่ได้
    """
    if not role_at_least(actor_role, "ADMIN"):
        raise ValueError("ต้องเป็น ADMIN ขึ้นไปจึงออก API key ได้")
    if tier not in VALID_TIERS:
        raise ValueError(f"tier ไม่ถูกต้อง: {tier} (ต้องเป็น {sorted(VALID_TIERS)})")

    data = _load(project_root)
    if owner not in data["users"]:
        raise ValueError(f"ไม่พบ user เจ้าของ key: {owner}")

    tier_letter = tier[0]  # f / p
    raw_key = f"{_KEY_PREFIX}_{tier_letter}_{secrets.token_urlsafe(32)}"
    key_id = secrets.token_hex(8)

    data["api_keys"][key_id] = {
        "key_hash": _hash_key(raw_key),
        "prefix": raw_key[:_KEY_PREFIX_SHOW],   # ปลอดภัยที่จะโชว์ (ระบุตัว key)
        "owner": owner,
        "tier": tier,
        "daily_limit": TIER_DAILY_LIMIT[tier],
        "used_today": 0,
        "usage_date": _today_str(),
        "active": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(project_root, data)
    return {
        "key_id": key_id,
        "key": raw_key,                 # <<< โชว์ครั้งเดียว
        "owner": owner,
        "tier": tier,
        "daily_limit": TIER_DAILY_LIMIT[tier],
        "prefix": raw_key[:_KEY_PREFIX_SHOW],
    }


def verify_api_key(project_root: Path, raw_key: str) -> dict | None:
    """ตรวจ API key ดิบ — คืน record (key_id/owner/tier/role ฯลฯ ไม่มี hash) ถ้าใช้ได้

    ใช้ได้ = key มีอยู่ + active + เจ้าของยังมีตัวตนและ active
    """
    if not raw_key:
        return None
    target = _hash_key(raw_key)
    data = _load(project_root)
    for key_id, rec in data["api_keys"].items():
        if not rec.get("active", False):
            continue
        if hmac.compare_digest(rec.get("key_hash", ""), target):
            owner = rec.get("owner")
            user = data["users"].get(owner)
            if not user or not user.get("active", False):
                return None  # เจ้าของถูกปิด → key ใช้ไม่ได้
            return {
                "key_id": key_id,
                "username": owner,   # ให้ identity มี field เดียวกับ master/local (/api/me)
                "owner": owner,
                "role": user["role"],
                "tier": rec.get("tier"),
                "daily_limit": rec.get("daily_limit", 0),
            }
    return None


def has_quota(project_root: Path, key_id: str) -> bool:
    """เช็คว่า key นี้ยังมีโควตาเหลือวันนี้ไหม โดย 'ไม่หัก' (peek อย่างเดียว)

    ใช้ที่ server เพื่อปฏิเสธเร็วก่อนอ่าน body. การหักจริงคือ consume_quota (จองแบบ atomic
    ก่อนเรียกโมเดล) และถ้าโมเดล/แชทล้มเหลว server จะเรียก refund_quota คืนให้
    """
    data = _load(project_root)
    rec = data["api_keys"].get(key_id)
    if not rec or not rec.get("active", False):
        return False
    limit = rec.get("daily_limit", 0)
    if limit == 0:
        return True  # paid = ไม่จำกัด
    if rec.get("usage_date") != _today_str():
        return True  # ข้ามวันแล้ว โควตารีเซ็ต
    return rec.get("used_today", 0) < limit


@_synchronized
def consume_quota(project_root: Path, key_id: str) -> tuple:
    """หัก 1 โควตาของ key — คืน (ok, remaining)

    - tier paid (daily_limit=0) → ไม่จำกัด ok=True, remaining=-1 (แทน unlimited)
    - รีเซ็ตตัวนับอัตโนมัติเมื่อข้ามวัน
    - เกินโควตา → ok=False ไม่หักเพิ่ม
    - บันทึกลงดิสก์ไม่สำเร็จ → ok=False (fail-closed; ไม่ปล่อยผ่านทั้งที่ไม่ได้นับ)
    - server เรียกเพื่อ "จอง" ก่อนเรียกโมเดล และเรียก refund_quota เมื่อไม่ได้คำตอบ
    """
    data = _load(project_root)
    rec = data["api_keys"].get(key_id)
    if not rec or not rec.get("active", False):
        return (False, 0)

    limit = rec.get("daily_limit", 0)
    if limit == 0:
        return (True, -1)  # unlimited (paid)

    today = _today_str()
    if rec.get("usage_date") != today:
        rec["usage_date"] = today
        rec["used_today"] = 0

    if rec["used_today"] >= limit:
        _save(project_root, data)  # บันทึกการรีเซ็ตวันที่ (ถ้ามี) ไว้ด้วย
        return (False, 0)

    rec["used_today"] += 1
    if not _save(project_root, data):
        return (False, 0)  # ไม่ได้บันทึกการหัก → ห้ามให้ผ่าน (กันข้ามโควตาบน Windows)
    return (True, limit - rec["used_today"])


class RefundResult(enum.Enum):
    """ผลของ refund_quota — bool() เป็น True เฉพาะ REFUNDED (เข้ากันได้กับโค้ดเดิมที่เช็ค bool)"""
    REFUNDED = "refunded"        # คืนแล้วและบันทึกสำเร็จ
    NOTHING = "nothing"          # ไม่มีอะไรต้องคืน (ไม่มี key / paid / ข้ามวัน / used=0)
    SAVE_FAILED = "save_failed"  # คืนในหน่วยความจำแล้วแต่บันทึก org.json ไม่สำเร็จ

    def __bool__(self) -> bool:
        return self is RefundResult.REFUNDED


@_synchronized
def refund_quota(project_root: Path, key_id: str) -> RefundResult:
    """คืน 1 โควตาที่ consume_quota จองไว้ (ใช้เมื่อโมเดล/แชทล้มเหลว)

    - ไม่ติดลบ (used_today ต่ำสุด 0); tier paid/ข้ามวันแล้ว = NOTHING
    - บันทึกไม่สำเร็จ = SAVE_FAILED (ผู้เรียกควร log warn)
    """
    data = _load(project_root)
    rec = data["api_keys"].get(key_id)
    if not rec or rec.get("daily_limit", 0) == 0:
        return RefundResult.NOTHING
    if rec.get("usage_date") != _today_str():
        return RefundResult.NOTHING  # ข้ามวันแล้ว ตัวนับรีเซ็ตไปเอง ไม่คืนข้ามวัน
    used = int(rec.get("used_today", 0))
    if used <= 0:
        return RefundResult.NOTHING
    rec["used_today"] = used - 1
    if not _save(project_root, data):
        return RefundResult.SAVE_FAILED
    return RefundResult.REFUNDED


@_synchronized
def revoke_api_key(project_root: Path, key_id: str, actor_role: str) -> bool:
    """ยกเลิก API key (ปิดใช้งาน ไม่ลบประวัติ) — ต้องเป็น ADMIN ขึ้นไป"""
    if not role_at_least(actor_role, "ADMIN"):
        raise ValueError("ต้องเป็น ADMIN ขึ้นไปจึงยกเลิก API key ได้")
    data = _load(project_root)
    rec = data["api_keys"].get(key_id)
    if not rec:
        return False
    rec["active"] = False
    _save(project_root, data)
    return True


def list_api_keys(project_root: Path) -> list:
    """คืนรายการ key (prefix เท่านั้น ไม่มี key เต็ม/hash ตาม Rule 23) — เรียงตามวันที่สร้าง"""
    data = _load(project_root)
    out = []
    for key_id, rec in data["api_keys"].items():
        out.append({
            "key_id": key_id,
            "prefix": rec.get("prefix"),
            "owner": rec.get("owner"),
            "tier": rec.get("tier"),
            "daily_limit": rec.get("daily_limit", 0),
            "used_today": rec.get("used_today", 0),
            "usage_date": rec.get("usage_date"),
            "active": rec.get("active", False),
            "created_at": rec.get("created_at"),
        })
    out.sort(key=lambda r: r.get("created_at") or "")
    return out


# ---------- test compatibility helpers ----------

def get_user_by_api_key(raw_key: str, project_root: Path | str | None = None) -> dict | None:
    """Compatibility wrapper for Phase 1 auth tests.

    Supports the simplified API used in tests: get_user_by_api_key(raw_key) and
    fail-closed semantics when the key is missing, revoked, or owned by an inactive user.
    """
    root = Path(project_root) if project_root is not None else Path.cwd()
    rec = verify_api_key(root, raw_key)
    if not rec:
        return None
    data = _load(root)
    user = data["users"].get(rec["owner"])
    if not user or not user.get("active", False):
        return None
    out = dict(rec)
    out["username"] = rec.get("username") or rec.get("owner")
    out["tier"] = rec.get("tier")
    out["active"] = bool(user.get("active", False))
    return out


def check_and_consume_quota(username: str, tier: str = "free", project_root: Path | str | None = None) -> bool:
    """Compatibility wrapper used by Phase 1 tests.

    This function performs a simplified quota guard for a user-level quota bucket.
    It is intentionally fail-closed: a free-tier user exceeding the daily limit is rejected.
    """
    root = Path(project_root) if project_root is not None else Path.cwd()
    data = _load(root)
    if tier not in VALID_TIERS:
        return True
    if tier == "paid":
        return True

    today = _today_str()
    bucket = data.setdefault("usage", {})
    entry = bucket.get(username)
    if isinstance(entry, dict) and entry.get("date") == today:
        count = int(entry.get("count", 0))
    else:
        count = 0
    if count >= TIER_DAILY_LIMIT[tier]:
        bucket[username] = {"date": today, "count": count}
        _save(root, data)
        return False
    bucket[username] = {"date": today, "count": count + 1}
    return _save(root, data)  # fail-closed: ไม่ได้บันทึกการหัก = ไม่ให้ผ่าน


# ---------- google oauth ----------

def create_or_update_google_user(project_root: Path, email: str, display_name: str) -> dict:
    """Create or update a Google-authenticated user in the existing org.json schema.

    This keeps the repository's structure consistent with the rest of the app:
    {
      "users": {"username": {...}},
      "api_keys": {"key_id": {...}}
    }
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("อีเมล Google ไม่ถูกต้อง")

    data = _load(project_root)
    username = email
    user = data["users"].get(username)
    display = (display_name or email.split("@")[0]).strip() or email.split("@")[0]

    if user is None:
        data["users"][username] = {
            "role": "USER",
            "password": _hash_password(secrets.token_urlsafe(24)),
            "active": True,
            "display_name": display,
            "google_email": email,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save(project_root, data)
        return {"username": username, "role": "USER", "tier": "free"}

    user["display_name"] = display
    user["google_email"] = email
    user["active"] = True
    _save(project_root, data)
    return {"username": username, "role": user.get("role", "USER"), "tier": "free"}


def issue_google_internal_token(project_root: Path, username: str, tier: str = "free") -> str:
    """Issue a fresh internal LCA key for a Google-authenticated user.

    Unlike create_api_key(), this path does not require an ADMIN/CEO actor because
    the user is authenticating through OAuth and needs an internal token immediately.
    """
    project_root = Path(project_root)
    if tier not in VALID_TIERS:
        raise ValueError(f"tier ไม่ถูกต้อง: {tier} (ต้องเป็น {sorted(VALID_TIERS)})")

    data = _load(project_root)
    if username not in data["users"]:
        raise ValueError(f"ไม่พบ user: {username}")

    raw_key = f"lca_f_g_{secrets.token_urlsafe(16)}"
    key_id = secrets.token_hex(8)
    data["api_keys"][key_id] = {
        "key_hash": _hash_key(raw_key),
        "prefix": raw_key[:_KEY_PREFIX_SHOW],
        "owner": username,
        "tier": tier,
        "daily_limit": TIER_DAILY_LIMIT[tier],
        "used_today": 0,
        "usage_date": _today_str(),
        "active": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(project_root, data)
    return raw_key
