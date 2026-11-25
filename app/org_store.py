"""
org_store.py — ระบบองค์กร: ผู้ใช้ (User) + บทบาท (Role) + API key แบบมี tier/quota
เก็บใน SQLite (WAL) ต่อโปรเจกต์: ``data/lca.db`` ตาราง org_users / org_api_keys /
org_user_usage / org_meta (migration ``0012_org_auth``) ผ่าน app/db.py

ทำไมย้ายจาก org.json:
    org.json ต้อง read-modify-write ทั้งไฟล์ทุกครั้ง (ช้าเมื่อ key เยอะ, verify_api_key ไล่ทุก key)
    และ lock อยู่แค่ใน process เดียว — หลายโปรเซสหักโควตาพร้อมกันแล้วนับเพี้ยนได้.
    SQLite: index ที่ key_hash, หักโควตาด้วย UPDATE เดียวแบบ atomic (ข้ามโปรเซสได้)

ย้ายข้อมูล (ครั้งเดียว):
    ครั้งแรกที่เปิด store ของโปรเจกต์ ถ้ามี org.json และยังไม่เคย import → copy ไป
    ``backups/org.json.<เวลา>.bak`` ก่อน แล้ว import users / api_keys / used_today / usage
    บันทึกใน org_meta('org_json_imported'). ไม่ลบ/ไม่แก้ org.json เดิม (หลัง import ไม่ถูกอ่านอีก)

บทบาท (สูง -> ต่ำ):   CEO > ADMIN > USER
    USER  : แชท/ใช้งาน AI ได้ (กินโควตาตาม tier ของ API key)
    ADMIN : ทุกอย่างของ USER + สร้าง/ปิด user ระดับ USER + ออก/ยกเลิก API key
    CEO   : ทุกอย่างของ ADMIN + ตั้ง ADMIN + ดูภาพรวมทั้งองค์กร

ความปลอดภัย (Rule ข้อ 23 — secret ห้าม commit/ห้าม print เต็มๆ):
    - รหัสผ่านเก็บเป็น pbkdf2_hmac(sha256) + salt สุ่ม ไม่เคยเก็บ plaintext
    - API key สุ่มด้วย secrets, เก็บเฉพาะ sha256 hash + prefix ไว้โชว์ระบุตัว
    - คืนค่า key เต็มๆ "ครั้งเดียวตอนสร้าง" เท่านั้น หลังจากนั้นกู้คืนไม่ได้ (by design)
    - data/ และ backups/ อยู่ใน .gitignore

Interface หลักที่ server.py เรียกใช้ (เหมือนเดิม):
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

from __future__ import annotations

import enum
import hashlib
import hmac
import json
import secrets
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from app import db

ORG_FILE_NAME = "org.json"
IMPORT_META = "org_json_imported"

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

_WRITE_ATTEMPTS = 5          # retry เมื่อ db ถูก lock ชั่วคราว (หลังหมด busy_timeout)
_WRITE_BACKOFF_S = 0.02

_PREPARED: set[str] = set()
_PREPARE_LOCK = threading.Lock()


# ---------- storage (SQLite ผ่าน app/db.py) ----------

def _org_path(project_root: Path) -> Path:
    return Path(project_root) / ORG_FILE_NAME


def _open(path: Path) -> sqlite3.Connection:
    """จุดเดียวที่เปิด connection (tests patch ตรงนี้เพื่อจำลอง db ล้ม)"""
    return db.connect_light(path)


def _is_busy(err: sqlite3.Error) -> bool:
    msg = str(err).lower()
    return "locked" in msg or "busy" in msg


@contextmanager
def _txn(project_root: Path, path: Path):
    """BEGIN IMMEDIATE ... COMMIT; ใช้ write_lock เดียวกับ db.write_txn (ทีละ writer ใน process)"""
    with db.write_lock(project_root):
        conn = _open(path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()


def _prepare(project_root: Path) -> Path:
    """migrate + import org.json ครั้งเดียวต่อ db ต่อ process → คืน path ของ db"""
    path = db.db_path(project_root)
    key = str(path)
    with _PREPARE_LOCK:
        if key in _PREPARED and path.exists():
            return path
        db.ensure_ready(project_root)
        _import_org_json(Path(project_root), path)
        _PREPARED.add(key)
    return path


def _write(project_root: Path, fn):
    """รัน fn(conn) ใน write transaction — retry เมื่อ db busy/locked ชั่วคราว"""
    path = _prepare(project_root)
    for i in range(_WRITE_ATTEMPTS):
        try:
            with _txn(project_root, path) as conn:
                return fn(conn)
        except sqlite3.OperationalError as e:
            if i == _WRITE_ATTEMPTS - 1 or not _is_busy(e):
                raise
            time.sleep(_WRITE_BACKOFF_S * (i + 1))
    raise RuntimeError("unreachable")  # pragma: no cover


def _read(project_root: Path, sql: str, params: tuple = (), one: bool = False):
    path = _prepare(project_root)
    conn = _open(path)
    try:
        cur = conn.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        conn.close()


# ---------- one-time import from org.json ----------

def _backup_org_json(project_root: Path, src: Path) -> Path:
    dest_dir = project_root / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"org.json.{stamp}.bak"
    n = 1
    while dest.exists():
        dest = dest_dir / f"org.json.{stamp}-{n}.bak"
        n += 1
    shutil.copy2(src, dest)
    return dest


def _int(value, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _import_rows(conn: sqlite3.Connection, data: dict) -> dict:
    users = data.get("users") if isinstance(data.get("users"), dict) else {}
    keys = data.get("api_keys") if isinstance(data.get("api_keys"), dict) else {}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    done = {"users": 0, "keys": 0, "usage": 0, "skipped": 0}
    for name, u in users.items():
        if not isinstance(u, dict) or u.get("role") not in VALID_ROLES:
            done["skipped"] += 1
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO org_users(username, role, password, active, created_at,"
            " display_name, google_email) VALUES (?,?,?,?,?,?,?)",
            (name, u["role"], u.get("password") or "", 1 if u.get("active", False) else 0,
             u.get("created_at"), u.get("display_name"), u.get("google_email")))
        done["users"] += cur.rowcount
    for key_id, k in keys.items():
        if not isinstance(k, dict) or not k.get("key_hash") or not k.get("owner"):
            done["skipped"] += 1
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO org_api_keys(key_id, key_hash, prefix, owner, tier,"
            " daily_limit, used_today, usage_date, active, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key_id, k["key_hash"], k.get("prefix"), k["owner"], k.get("tier") or "free",
             _int(k.get("daily_limit", 0)), _int(k.get("used_today", 0)), k.get("usage_date"),
             1 if k.get("active", False) else 0, k.get("created_at")))
        done["keys"] += cur.rowcount
    for name, entry in usage.items():
        if isinstance(entry, dict) and entry.get("date"):
            cur = conn.execute(
                "INSERT OR IGNORE INTO org_user_usage(username, usage_date, count) VALUES (?,?,?)",
                (name, str(entry["date"]), _int(entry.get("count", 0))))
            done["usage"] += cur.rowcount
    return done


def _import_org_json(project_root: Path, path: Path) -> dict | None:
    """import org.json ครั้งเดียว (backup ก่อนเสมอ, ไม่ลบไฟล์เดิม) — คืนสรุปหรือ None"""
    src = _org_path(project_root)
    if not src.is_file():
        return None
    conn = _open(path)
    try:
        if conn.execute("SELECT 1 FROM org_meta WHERE name=?", (IMPORT_META,)).fetchone():
            return None
    finally:
        conn.close()
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"[org][warn] อ่าน {ORG_FILE_NAME} เพื่อ import ไม่ได้: {e} — ข้าม (ยังไม่ทำเครื่องหมาย)")
        return None
    if not isinstance(data, dict):
        print(f"[org][warn] {ORG_FILE_NAME} รูปแบบผิด — ข้าม import")
        return None
    backup = _backup_org_json(project_root, src)
    with _txn(project_root, path) as conn:
        if conn.execute("SELECT 1 FROM org_meta WHERE name=?", (IMPORT_META,)).fetchone():
            return None  # อีกโปรเซส import ไปแล้ว
        done = _import_rows(conn, data)
        info = {**done, "backup": str(backup.relative_to(project_root)),
                "at": datetime.now().isoformat(timespec="seconds")}
        conn.execute("INSERT INTO org_meta(name, value) VALUES (?,?)",
                     (IMPORT_META, json.dumps(info, ensure_ascii=False)))
    print(f"[org] import {ORG_FILE_NAME} -> lca.db: users={done['users']} keys={done['keys']} "
          f"skipped={done['skipped']} backup={info['backup']}")
    return info


def init_storage(project_root: Path) -> dict | None:
    """เรียกตอน server เริ่ม: migrate + import org.json (ครั้งแรก) — คืนข้อมูลการ import ถ้ามี"""
    _prepare(Path(project_root))
    row = _read(Path(project_root), "SELECT value FROM org_meta WHERE name=?", (IMPORT_META,), one=True)
    return json.loads(row["value"]) if row else None


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
    """ยังไม่มี user เลย = ต้อง bootstrap. db ล้ม → False (fail-closed: ไม่เปิดให้สร้าง CEO)"""
    try:
        row = _read(project_root, "SELECT COUNT(*) AS n FROM org_users", one=True)
    except sqlite3.Error as e:
        print(f"[org][error] อ่าน org_users ไม่ได้: {e}")
        return False
    return row["n"] == 0


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
    hashed = _hash_password(password)  # ช้า (PBKDF2) — ทำก่อนจับ write lock

    def op(conn):
        if conn.execute("SELECT 1 FROM org_users WHERE username=?", (username,)).fetchone():
            raise ValueError(f"มี user ชื่อ {username} อยู่แล้ว")
        is_bootstrap = conn.execute("SELECT COUNT(*) FROM org_users").fetchone()[0] == 0
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
        conn.execute("INSERT INTO org_users(username, role, password, active, created_at)"
                     " VALUES (?,?,?,1,?)", (username, role, hashed, _now_iso()))

    _write(project_root, op)
    return {"username": username, "role": role, "active": True}


def verify_password(project_root: Path, username: str, password: str) -> dict | None:
    """ตรวจ username/password — คืน record (ไม่มี hash) ถ้าถูกและ active, ไม่งั้น None"""
    try:
        user = _read(project_root, "SELECT role, password, active FROM org_users WHERE username=?",
                     (username,), one=True)
    except sqlite3.Error as e:
        print(f"[org][error] อ่าน user ไม่ได้: {e}")
        return None
    if not user or not user["active"]:
        return None
    if not _verify_password_hash(password, user["password"] or ""):
        return None
    return {"username": username, "role": user["role"], "active": True}


def set_user_active(project_root: Path, username: str, active: bool, actor_role: str) -> bool:
    """เปิด/ปิด user — ต้องเป็น ADMIN ขึ้นไป คืน True ถ้าเจอและแก้สำเร็จ"""
    if not role_at_least(actor_role, "ADMIN"):
        raise ValueError("ต้องเป็น ADMIN ขึ้นไปจึงเปิด/ปิด user ได้")

    def op(conn):
        row = conn.execute("SELECT role FROM org_users WHERE username=?", (username,)).fetchone()
        if not row:
            return False
        # ADMIN ปิด CEO ไม่ได้
        if ROLE_LEVEL[row["role"]] >= ROLE_LEVEL["CEO"] and actor_role != "CEO":
            raise ValueError("ADMIN ปิดบัญชี CEO ไม่ได้")
        conn.execute("UPDATE org_users SET active=? WHERE username=?",
                     (1 if active else 0, username))
        return True

    return _write(project_root, op)


def list_users(project_root: Path) -> list:
    """คืนรายชื่อ user (ไม่มี password hash) — เรียงตามชื่อ"""
    rows = _read(project_root, "SELECT username, role, active, created_at FROM org_users"
                               " ORDER BY username")
    return [{"username": r["username"], "role": r["role"], "active": bool(r["active"]),
             "created_at": r["created_at"]} for r in rows]


# ---------- api keys ----------

def _today_str() -> str:
    return date.today().isoformat()


def _insert_key(conn, key_id: str, raw_key: str, owner: str, tier: str) -> None:
    limit = TIER_DAILY_LIMIT[tier]
    if tier == "free":
        # a paid plan (app/payments.py) that is still running also covers keys issued later
        row = conn.execute("SELECT daily_limit FROM org_plan_limits WHERE username=?"
                           " AND expires_at > ?", (owner, time.time())).fetchone()
        if row is not None:
            limit = row["daily_limit"]
    conn.execute(
        "INSERT INTO org_api_keys(key_id, key_hash, prefix, owner, tier, daily_limit,"
        " used_today, usage_date, active, created_at) VALUES (?,?,?,?,?,?,0,?,1,?)",
        (key_id, _hash_key(raw_key), raw_key[:_KEY_PREFIX_SHOW], owner, tier,
         limit, _today_str(), _now_iso()))


# ---------- paid plans (app/payments.py) ----------
# A plan only changes daily_limit of the owner's tier="free" keys; tier "paid" keys stay
# unlimited. The *_in helpers run inside the caller's write transaction (run_write).

def run_write(project_root: Path, fn):
    """Public wrapper of the write transaction (BEGIN IMMEDIATE + retry) for sibling stores."""
    return _write(project_root, fn)


def run_read(project_root: Path, sql: str, params: tuple = (), one: bool = False):
    return _read(project_root, sql, params, one)


def set_plan_limit_in(conn, username: str, plan: str, daily_limit: int, order_id: str,
                      expires_at: float) -> None:
    if daily_limit < 0:
        raise ValueError("daily_limit ต้อง >= 0")
    conn.execute(
        "INSERT INTO org_plan_limits(username, plan, daily_limit, order_id, expires_at)"
        " VALUES (?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET plan=excluded.plan,"
        " daily_limit=excluded.daily_limit, order_id=excluded.order_id,"
        " expires_at=excluded.expires_at",
        (username, plan, int(daily_limit), order_id, float(expires_at)))
    conn.execute("UPDATE org_api_keys SET daily_limit=? WHERE owner=? AND tier='free'",
                 (int(daily_limit), username))


def clear_plan_limit_in(conn, username: str, order_id: str | None = None) -> bool:
    """Back to the free limit. With order_id: only if that order is the running plan."""
    sql, params = "DELETE FROM org_plan_limits WHERE username=?", [username]
    if order_id is not None:
        sql += " AND order_id=?"
        params.append(order_id)
    if conn.execute(sql, tuple(params)).rowcount == 0:
        return False
    conn.execute("UPDATE org_api_keys SET daily_limit=? WHERE owner=? AND tier='free'",
                 (TIER_DAILY_LIMIT["free"], username))
    return True


def expire_plan_limits_in(conn, now: float) -> list:
    """Clear every plan whose expires_at <= now; returns [(username, order_id)]"""
    rows = conn.execute("SELECT username, order_id FROM org_plan_limits WHERE expires_at <= ?",
                        (float(now),)).fetchall()
    for r in rows:
        clear_plan_limit_in(conn, r["username"], r["order_id"])
    return [(r["username"], r["order_id"]) for r in rows]


def plan_limit(project_root: Path, username: str) -> dict | None:
    row = _read(project_root, "SELECT username, plan, daily_limit, order_id, expires_at"
                              " FROM org_plan_limits WHERE username=?", (username,), one=True)
    return dict(row) if row else None


def create_api_key(project_root: Path, owner: str, tier: str, actor_role: str) -> dict:
    """ออก API key ใหม่ให้ owner — ต้องเป็น ADMIN ขึ้นไป

    คืน dict ที่มี field 'key' = ค่าเต็ม (โชว์ครั้งเดียวเท่านั้น!) + metadata
    หลังจากนี้ระบบเก็บแค่ hash กู้ค่าเต็มคืนไม่ได้
    """
    if not role_at_least(actor_role, "ADMIN"):
        raise ValueError("ต้องเป็น ADMIN ขึ้นไปจึงออก API key ได้")
    if tier not in VALID_TIERS:
        raise ValueError(f"tier ไม่ถูกต้อง: {tier} (ต้องเป็น {sorted(VALID_TIERS)})")

    tier_letter = tier[0]  # f / p
    raw_key = f"{_KEY_PREFIX}_{tier_letter}_{secrets.token_urlsafe(32)}"
    key_id = secrets.token_hex(8)

    def op(conn):
        if not conn.execute("SELECT 1 FROM org_users WHERE username=?", (owner,)).fetchone():
            raise ValueError(f"ไม่พบ user เจ้าของ key: {owner}")
        _insert_key(conn, key_id, raw_key, owner, tier)

    _write(project_root, op)
    return {
        "key_id": key_id,
        "key": raw_key,                 # <<< โชว์ครั้งเดียว
        "owner": owner,
        "tier": tier,
        "daily_limit": TIER_DAILY_LIMIT[tier],
        "prefix": raw_key[:_KEY_PREFIX_SHOW],
    }


_VERIFY_SQL = (
    "SELECT k.key_id, k.key_hash, k.owner, k.tier, k.daily_limit,"
    " u.role AS role, u.active AS user_active"
    " FROM org_api_keys k LEFT JOIN org_users u ON u.username = k.owner"
    " WHERE k.key_hash = ? AND k.active = 1 LIMIT 1"
)


def verify_api_key(project_root: Path, raw_key: str) -> dict | None:
    """ตรวจ API key ดิบ — คืน record (key_id/owner/tier/role ฯลฯ ไม่มี hash) ถ้าใช้ได้

    ใช้ได้ = key มีอยู่ + active + เจ้าของยังมีตัวตนและ active. ค้นด้วย index key_hash
    db ล้ม → None (fail-closed)
    """
    if not raw_key:
        return None
    target = _hash_key(raw_key)
    try:
        rec = _read(project_root, _VERIFY_SQL, (target,), one=True)
    except sqlite3.Error as e:
        print(f"[org][error] ตรวจ API key ไม่ได้: {e}")
        return None
    if rec is None or not hmac.compare_digest(rec["key_hash"], target):
        return None
    if not rec["role"] or not rec["user_active"]:
        return None  # เจ้าของถูกปิด/ไม่มีตัวตน → key ใช้ไม่ได้
    return {
        "key_id": rec["key_id"],
        "username": rec["owner"],   # ให้ identity มี field เดียวกับ master/local (/api/me)
        "owner": rec["owner"],
        "role": rec["role"],
        "tier": rec["tier"],
        "daily_limit": rec["daily_limit"],
    }


def has_quota(project_root: Path, key_id: str) -> bool:
    """เช็คว่า key นี้ยังมีโควตาเหลือวันนี้ไหม โดย 'ไม่หัก' (peek อย่างเดียว)

    ใช้ที่ server เพื่อปฏิเสธเร็วก่อนอ่าน body. การหักจริงคือ consume_quota (จองแบบ atomic
    ก่อนเรียกโมเดล) และถ้าโมเดล/แชทล้มเหลว server จะเรียก refund_quota คืนให้
    """
    try:
        rec = _read(project_root, "SELECT active, daily_limit, used_today, usage_date"
                                  " FROM org_api_keys WHERE key_id=?", (key_id,), one=True)
    except sqlite3.Error as e:
        print(f"[org][error] อ่านโควตาไม่ได้: {e}")
        return False
    if not rec or not rec["active"]:
        return False
    if rec["daily_limit"] == 0:
        return True  # paid = ไม่จำกัด
    if rec["usage_date"] != _today_str():
        return True  # ข้ามวันแล้ว โควตารีเซ็ต
    return rec["used_today"] < rec["daily_limit"]


# หัก 1 แบบ atomic ในคำสั่งเดียว: ข้ามวัน = เริ่มนับ 1 ใหม่, ไม่งั้น +1 เฉพาะเมื่อยังไม่ถึง limit
_CONSUME_SQL = (
    "UPDATE org_api_keys SET"
    " used_today = CASE WHEN usage_date = :today THEN used_today + 1 ELSE 1 END,"
    " usage_date = :today"
    " WHERE key_id = :key_id AND active = 1 AND daily_limit > 0"
    " AND (usage_date IS NOT :today OR used_today < daily_limit)"
    " RETURNING used_today, daily_limit"
)


def consume_quota(project_root: Path, key_id: str) -> tuple:
    """หัก 1 โควตาของ key — คืน (ok, remaining)

    - tier paid (daily_limit=0) → ไม่จำกัด ok=True, remaining=-1 (แทน unlimited)
    - รีเซ็ตตัวนับอัตโนมัติเมื่อข้ามวัน
    - เกินโควตา → ok=False ไม่หักเพิ่ม
    - บันทึกลง db ไม่สำเร็จ → ok=False (fail-closed; ไม่ปล่อยผ่านทั้งที่ไม่ได้นับ)
    - server เรียกเพื่อ "จอง" ก่อนเรียกโมเดล และเรียก refund_quota เมื่อไม่ได้คำตอบ
    """
    params = {"today": _today_str(), "key_id": key_id}

    def op(conn):
        row = conn.execute(_CONSUME_SQL, params).fetchone()
        if row is not None:
            return (True, row["daily_limit"] - row["used_today"])
        rec = conn.execute("SELECT active, daily_limit FROM org_api_keys WHERE key_id=?",
                           (key_id,)).fetchone()
        if rec and rec["active"] and rec["daily_limit"] == 0:
            return (True, -1)  # unlimited (paid)
        return (False, 0)      # ไม่มี key / ปิดแล้ว / เต็มโควตา

    try:
        return _write(project_root, op)
    except sqlite3.Error as e:
        print(f"[org][error] หักโควตาไม่สำเร็จ: {e}")
        return (False, 0)


class RefundResult(enum.Enum):
    """ผลของ refund_quota — bool() เป็น True เฉพาะ REFUNDED (เข้ากันได้กับโค้ดเดิมที่เช็ค bool)"""
    REFUNDED = "refunded"        # คืนแล้วและบันทึกสำเร็จ
    NOTHING = "nothing"          # ไม่มีอะไรต้องคืน (ไม่มี key / paid / ข้ามวัน / used=0)
    SAVE_FAILED = "save_failed"  # บันทึกการคืนลง db ไม่สำเร็จ

    def __bool__(self) -> bool:
        return self is RefundResult.REFUNDED


def refund_quota(project_root: Path, key_id: str) -> RefundResult:
    """คืน 1 โควตาที่ consume_quota จองไว้ (ใช้เมื่อโมเดล/แชทล้มเหลว)

    - ไม่ติดลบ (used_today ต่ำสุด 0); tier paid/ข้ามวันแล้ว = NOTHING
    - บันทึกไม่สำเร็จ = SAVE_FAILED (ผู้เรียกควร log warn)
    """
    def op(conn):
        cur = conn.execute(
            "UPDATE org_api_keys SET used_today = used_today - 1"
            " WHERE key_id=? AND daily_limit > 0 AND usage_date=? AND used_today > 0",
            (key_id, _today_str()))
        return RefundResult.REFUNDED if cur.rowcount == 1 else RefundResult.NOTHING

    try:
        return _write(project_root, op)
    except sqlite3.Error as e:
        print(f"[org][error] คืนโควตาไม่สำเร็จ: {e}")
        return RefundResult.SAVE_FAILED


def revoke_api_key(project_root: Path, key_id: str, actor_role: str) -> bool:
    """ยกเลิก API key (ปิดใช้งาน ไม่ลบประวัติ) — ต้องเป็น ADMIN ขึ้นไป"""
    if not role_at_least(actor_role, "ADMIN"):
        raise ValueError("ต้องเป็น ADMIN ขึ้นไปจึงยกเลิก API key ได้")

    def op(conn):
        cur = conn.execute("UPDATE org_api_keys SET active=0 WHERE key_id=?", (key_id,))
        return cur.rowcount == 1

    return _write(project_root, op)


def list_api_keys(project_root: Path) -> list:
    """คืนรายการ key (prefix เท่านั้น ไม่มี key เต็ม/hash ตาม Rule 23) — เรียงตามวันที่สร้าง"""
    rows = _read(project_root,
                 "SELECT key_id, prefix, owner, tier, daily_limit, used_today, usage_date,"
                 " active, created_at FROM org_api_keys ORDER BY COALESCE(created_at, ''), rowid")
    return [{
        "key_id": r["key_id"],
        "prefix": r["prefix"],
        "owner": r["owner"],
        "tier": r["tier"],
        "daily_limit": r["daily_limit"],
        "used_today": r["used_today"],
        "usage_date": r["usage_date"],
        "active": bool(r["active"]),
        "created_at": r["created_at"],
    } for r in rows]


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
    out = dict(rec)
    out["username"] = rec.get("username") or rec.get("owner")
    out["active"] = True  # verify_api_key คืนเฉพาะเมื่อเจ้าของ active
    return out


def check_and_consume_quota(username: str, tier: str = "free", project_root: Path | str | None = None) -> bool:
    """Compatibility wrapper used by Phase 1 tests.

    Per-user daily bucket, atomic in one UPSERT. Fail-closed: a free-tier user over
    the daily limit, or a db error, is rejected.
    """
    root = Path(project_root) if project_root is not None else Path.cwd()
    if tier not in VALID_TIERS:
        return True
    if tier == "paid":
        return True
    params = {"u": username, "today": _today_str(), "limit": TIER_DAILY_LIMIT[tier]}

    def op(conn):
        cur = conn.execute(
            "INSERT INTO org_user_usage(username, usage_date, count) VALUES (:u, :today, 1)"
            " ON CONFLICT(username) DO UPDATE SET"
            " count = CASE WHEN usage_date = excluded.usage_date THEN count + 1 ELSE 1 END,"
            " usage_date = excluded.usage_date"
            " WHERE usage_date <> excluded.usage_date OR count < :limit", params)
        return cur.rowcount == 1

    try:
        return _write(root, op)
    except sqlite3.Error as e:
        print(f"[org][error] หักโควตาผู้ใช้ไม่สำเร็จ: {e}")
        return False


# ---------- google oauth ----------

def create_or_update_google_user(project_root: Path, email: str, display_name: str) -> dict:
    """Create or update a Google-authenticated user (role USER for new accounts)."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("อีเมล Google ไม่ถูกต้อง")
    username = email
    display = (display_name or email.split("@")[0]).strip() or email.split("@")[0]
    random_pw = _hash_password(secrets.token_urlsafe(24))

    def op(conn):
        row = conn.execute("SELECT role FROM org_users WHERE username=?", (username,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO org_users(username, role, password, active, display_name,"
                " google_email, created_at) VALUES (?, 'USER', ?, 1, ?, ?, ?)",
                (username, random_pw, display, email, _now_iso()))
            return "USER"
        conn.execute("UPDATE org_users SET display_name=?, google_email=?, active=1"
                     " WHERE username=?", (display, email, username))
        return row["role"] or "USER"

    role = _write(project_root, op)
    return {"username": username, "role": role, "tier": "free"}


def issue_google_internal_token(project_root: Path, username: str, tier: str = "free") -> str:
    """Issue a fresh internal LCA key for a Google-authenticated user.

    Unlike create_api_key(), this path does not require an ADMIN/CEO actor because
    the user is authenticating through OAuth and needs an internal token immediately.
    """
    project_root = Path(project_root)
    if tier not in VALID_TIERS:
        raise ValueError(f"tier ไม่ถูกต้อง: {tier} (ต้องเป็น {sorted(VALID_TIERS)})")
    raw_key = f"lca_f_g_{secrets.token_urlsafe(16)}"
    key_id = secrets.token_hex(8)

    def op(conn):
        if not conn.execute("SELECT 1 FROM org_users WHERE username=?", (username,)).fetchone():
            raise ValueError(f"ไม่พบ user: {username}")
        _insert_key(conn, key_id, raw_key, username, tier)

    _write(project_root, op)
    return raw_key
