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
    list_api_keys(project_root) -> list[dict]                       # ไม่คืน key/hash
"""

import functools
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
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


def _save(project_root: Path, data: dict) -> None:
    # เขียนแบบ atomic (temp + os.replace) เพื่อให้ผู้อ่านพร้อมกันเห็นไฟล์เก่าหรือใหม่เต็มๆ
    # เสมอ ไม่เห็นไฟล์ครึ่งๆ กลางๆ (กัน JSON พังตอนอ่านชนกับตอนเขียน)
    path = _org_path(project_root)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".org.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError:
            # เก็บกวาด temp ถ้าเขียน/replace ไม่สำเร็จ
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        # fail loud (Rule 14) แต่ไม่ทำโปรแกรมพัง — ผู้เรียกจะเห็นว่า state ไม่ถูกบันทึก
        print(f"[org][error] เขียน {ORG_FILE_NAME} ไม่ได้: {e}")


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

    ใช้ที่ server เพื่อปฏิเสธคำขอที่เกินโควตา 'ก่อน' ลงมือทำงานจริง แล้วค่อยเรียก
    consume_quota หลังทำสำเร็จ — คำขอที่ล้มเหลว (body พัง/Ollama ล่ม) จะได้ไม่โดนหัก
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
    _save(project_root, data)
    return (True, limit - rec["used_today"])


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
