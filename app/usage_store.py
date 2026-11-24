"""
usage_store.py — บันทึกการใช้งาน API ต่อ key ลง SQLite เพื่อ metering/สรุปค่าใช้จ่าย (stdlib)

ทำไมต้องมี (Item H): org_store เก็บแค่ตัวนับรายวัน (used_today/usage_date) ที่ "รีเซ็ตทุกวัน"
— ดูย้อนหลังไม่ได้ว่าใครใช้ไปเท่าไรเดือนนี้ หรือ tier paid สร้างค่าใช้จ่ายรวมเท่าไร
โมดูลนี้บันทึกทุก event การใช้งานที่สำเร็จ (append-only) ลง usage.db จึง query ย้อนหลัง
+ สรุปต่อ key / ต่อ tier ได้ ซึ่งเป็นฐานของการคิดเงิน

ขอบเขต (ตาม backlog H): **บันทึก + สรุปเท่านั้น ไม่เชื่อม payment gateway จริง**
ราคา/หน่วย (TIER_UNIT_PRICE) เป็นค่า "ตั้งต้นสำหรับประมาณการ" ใน docs/USAGE_BILLING.md
ไม่ใช่การเรียกเก็บเงินจริง

สไตล์เดิม: stdlib เท่านั้น, per-project store (usage.db), connection ต่อ call
(ปลอดภัยกับ ThreadingHTTPServer), SQL parametrised, ไม่ crash โปรแกรมหลัก

Interface:
    record_usage(project_root, key_id, owner, tier, endpoint="chat", units=1) -> dict
    list_usage(project_root, key_id=None, limit=100) -> list[dict]   # ใหม่สุดก่อน
    summary(project_root) -> dict   # รวม units+cost ต่อ tier/ต่อ key
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

USAGE_DB_NAME = "usage.db"

# ราคาต่อ 1 หน่วยการใช้งาน (เช่น 1 request) แยกตาม tier — หน่วยเป็น "บาท" (ประมาณการ)
# หมายเหตุ: เป็นค่าตั้งต้นสำหรับประมาณการเท่านั้น ไม่ใช่การเรียกเก็บเงินจริง
TIER_UNIT_PRICE = {
    "free": 0.0,
    "paid": 0.10,
}
_DEFAULT_PRICE = 0.0  # tier ที่ไม่รู้จัก = ไม่คิดเงิน (ปลอดภัยไว้ก่อน)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def _session(project_root: Path):
    """Open, commit/rollback, then always close. A bare `with sqlite3.connect()`
    only commits; it never closes, so the file stays locked (Windows) until GC."""
    conn = _connect(project_root)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _connect(project_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(project_root / USAGE_DB_NAME), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            used_at TEXT NOT NULL,
            key_id TEXT,
            owner TEXT,
            tier TEXT,
            endpoint TEXT,
            units INTEGER NOT NULL DEFAULT 1
        )"""
    )
    return conn


def _unit_price(tier: Optional[str]) -> float:
    return TIER_UNIT_PRICE.get(tier or "", _DEFAULT_PRICE)


def record_usage(
    project_root: Path,
    key_id: Optional[str],
    owner: Optional[str],
    tier: Optional[str],
    endpoint: str = "chat",
    units: int = 1,
) -> dict:
    """บันทึก 1 event การใช้งาน (append-only) — raise ValueError ถ้า units ไม่ใช่จำนวนบวก"""
    try:
        units = int(units)
    except (TypeError, ValueError) as e:
        raise ValueError(f"units ต้องเป็นจำนวนเต็ม: {units!r}") from e
    if units <= 0:
        raise ValueError("units ต้องมากกว่า 0")
    now = _now()
    with _session(project_root) as conn:
        cur = conn.execute(
            "INSERT INTO usage (used_at, key_id, owner, tier, endpoint, units) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now, key_id, owner, (tier or None), (endpoint or "").strip() or None, units),
        )
        row = conn.execute("SELECT * FROM usage WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_usage(project_root: Path, key_id: Optional[str] = None, limit: int = 100) -> list:
    """คืน event ล่าสุดก่อน กรองตาม key_id ได้"""
    with _session(project_root) as conn:
        if key_id:
            rows = conn.execute(
                "SELECT * FROM usage WHERE key_id = ? ORDER BY id DESC LIMIT ?",
                (key_id, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM usage ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
    return [dict(r) for r in rows]


def summary(project_root: Path) -> dict:
    """สรุปรวมการใช้งาน: units+cost รวม, แยกตาม tier, และแยกต่อ key
    cost = units * TIER_UNIT_PRICE[tier] (ประมาณการ ไม่ใช่เรียกเก็บจริง)"""
    with _session(project_root) as conn:
        by_tier_rows = conn.execute(
            "SELECT tier, COALESCE(SUM(units), 0) AS units, COUNT(*) AS events "
            "FROM usage GROUP BY tier"
        ).fetchall()
        by_key_rows = conn.execute(
            "SELECT key_id, owner, tier, COALESCE(SUM(units), 0) AS units, COUNT(*) AS events "
            "FROM usage GROUP BY key_id, owner, tier ORDER BY units DESC"
        ).fetchall()

    by_tier, total_units, total_cost = {}, 0, 0.0
    for r in by_tier_rows:
        tier = r["tier"] or "unknown"
        units = int(r["units"])
        cost = round(units * _unit_price(r["tier"]), 2)
        by_tier[tier] = {"units": units, "events": int(r["events"]),
                         "unit_price": _unit_price(r["tier"]), "cost": cost}
        total_units += units
        total_cost += cost

    by_key = []
    for r in by_key_rows:
        units = int(r["units"])
        by_key.append({
            "key_id": r["key_id"],
            "owner": r["owner"],
            "tier": r["tier"],
            "units": units,
            "events": int(r["events"]),
            "cost": round(units * _unit_price(r["tier"]), 2),
        })

    return {
        "total_units": total_units,
        "total_cost": round(total_cost, 2),
        "currency": "THB (ประมาณการ — ไม่ใช่การเรียกเก็บจริง)",
        "by_tier": by_tier,
        "by_key": by_key,
    }


QUOTA_FILE_NAME = "usage_quotas.json"
FREE_DAILY_LIMIT = 100
LOCK_TIMEOUT_S = 5.0   # รอ lock นานสุดเท่านี้ก่อนปฏิเสธ (fail-closed)
LOCK_STALE_S = 30.0    # lock ที่เก่ากว่านี้ถือว่าค้างจากโปรเซสที่ล้ม


class QuotaStoreError(RuntimeError):
    """ไฟล์โควตาเสียหาย/อ่านไม่ได้/ล็อกไม่ได้ — ปฏิเสธคำขอ ห้ามรีเซ็ตโควตาเงียบๆ"""


def _quota_path(project_root: Path | str | None) -> Path:
    root = Path(project_root) if project_root is not None else Path.cwd()
    return root / QUOTA_FILE_NAME


def _validate_quota_data(data: object) -> dict:
    """ตรวจโครงสร้าง {username: {"date": str, "count": int}} — ไม่ผ่าน raise ValueError"""
    if not isinstance(data, dict):
        raise ValueError("ระดับบนสุดต้องเป็น object")
    for user, entry in data.items():
        ok = (isinstance(entry, dict) and isinstance(entry.get("date"), str)
              and isinstance(entry.get("count"), int))
        if not ok:
            raise ValueError(f"รายการของ {user!r} ไม่ถูกต้อง")
    return data


def _quarantine_corrupt(path: Path) -> str:
    """คัดลอกไฟล์เสียเป็น .corrupt-<เวลา> เก็บไว้ (ไฟล์เดิมคงอยู่เพื่อให้ยัง fail-closed)"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.name}.corrupt-{stamp}")
    shutil.copy2(path, backup)
    return backup.name


def _load_quota(path: Path) -> dict:
    """อ่านโควตา: ไม่มีไฟล์ = ว่าง (เริ่มใหม่ได้); ไฟล์เสีย = เก็บสำเนาแล้ว raise"""
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise QuotaStoreError(f"อ่านไฟล์โควตาไม่ได้: {e}") from e
    try:
        return _validate_quota_data(json.loads(raw))
    except ValueError as e:
        try:
            where = _quarantine_corrupt(path)
        except OSError:
            where = "(สำรองไม่สำเร็จ)"
        raise QuotaStoreError(
            f"ไฟล์โควตาเสียหาย ({e}) เก็บสำเนาไว้ที่ {where} — "
            "ปฏิเสธคำขอจนกว่าผู้ดูแลจะตรวจสอบ"
        ) from e


def _replace_with_retry(src: Path, dst: Path, attempts: int = 20) -> None:
    """os.replace บน Windows อาจโดน PermissionError ชั่วคราวถ้ามีผู้อ่านถือไฟล์อยู่ -> ลองใหม่"""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.005)


def _write_quota_atomic(path: Path, data: dict) -> None:
    """เขียนผ่านไฟล์ tmp ชื่อไม่ซ้ำ แล้ว os.replace ทับ — ไม่มีไฟล์ครึ่งๆ กลางคัน"""
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)  # ไม่ fsync: ไฟล์ที่ครึ่งๆ กลางคันหลังไฟดับจะถูกจับเป็นไฟล์เสีย (fail-closed)
        _replace_with_retry(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()  # ไม่มีผลถ้า replace สำเร็จไปแล้ว (tmp หายไปแล้ว)


def _read_lock_token(lock: Path) -> Optional[str]:
    try:
        return lock.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _restore_lock(grave: Path, lock: Path) -> None:
    """คืนไฟล์ lock ที่ย้ายผิดตัวกลับชื่อเดิม โดยไม่เขียนทับ lock ใหม่ที่อาจเกิดขึ้นแล้ว

    os.link ล้มถ้าปลายทางมีอยู่ (ทั้ง POSIX/NTFS) ส่วน os.rename บน POSIX จะเขียนทับ จึงใช้
    link ก่อน; ถ้า filesystem ไม่รองรับ hard link ใช้ rename (Windows ล้มเองถ้าปลายทางมี)
    ข้อจำกัด: ถ้ามีโปรเซสที่สามสร้าง lock ใหม่ระหว่างช่วงสั้น ๆ ที่เรา rename ออกไป จะคืนไม่ได้
    เจ้าของเดิมจะเห็น token ไม่ตรงตอนปล่อยและไม่ลบของโปรเซสที่สาม (เกิดได้เฉพาะ race แคบมาก)
    """
    try:
        os.link(grave, lock)
    except FileExistsError:
        pass  # มี lock ใหม่แล้ว คืนไม่ได้ (ดูข้อจำกัดด้านบน)
    except OSError:
        if os.name == "nt":  # rename บน Windows ไม่เขียนทับ → ปลอดภัย
            with contextlib.suppress(OSError):
                os.rename(grave, lock)
                return
        elif not lock.exists():  # POSIX fallback: ยังมีช่องแคบระหว่าง exists กับ rename
            with contextlib.suppress(OSError):
                os.rename(grave, lock)
                return
    with contextlib.suppress(OSError):
        grave.unlink()


def _remove_lock_if_token(lock: Path, expected: str) -> bool:
    """rename-then-verify: ย้าย lock ไปชื่อชั่วคราวไม่ซ้ำ (atomic) แล้วค่อยตรวจ token

    ถ้า token ตรง → ลบ, ไม่ตรง → คืนชื่อเดิม. ลดช่อง TOCTOU ของ "อ่าน token แล้ว unlink"
    เพราะสิ่งที่ตรวจคือไฟล์ที่เรายึดมาแล้วจริง ไม่ใช่ไฟล์ที่อาจถูกแทนที่ระหว่างอ่านกับลบ
    Windows: rename ไฟล์ที่อีกโปรเซสเปิดอยู่จะได้ PermissionError → ถือว่าไม่ได้ลบ (ลองใหม่รอบหน้า)
    """
    grave = lock.with_name(f"{lock.name}.{uuid.uuid4().hex}.del")
    try:
        os.rename(lock, grave)
    except OSError:
        return False
    if _read_lock_token(grave) == expected:
        with contextlib.suppress(OSError):
            grave.unlink()
        return True
    _restore_lock(grave, lock)
    return False


def _break_stale_lock(lock: Path) -> None:
    """ลบ lock ที่ค้างจากโปรเซสที่ล้ม — เฉพาะเมื่อ token ยังเป็นตัวเดียวกับที่เห็นว่าเก่า"""
    seen = _read_lock_token(lock)
    if seen is None:
        return
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return
    if age <= LOCK_STALE_S:
        return
    _remove_lock_if_token(lock, seen)  # มีเจ้าของใหม่แทนที่แล้ว → คืนชื่อเดิม ไม่ลบ


def _release_own_lock(lock: Path, token: str) -> None:
    """ลบไฟล์ lock เฉพาะเมื่อยังเป็นของเรา (token ตรง) — ถ้าถูกตัดเป็น stale แล้วมีคนอื่นถือ ห้ามลบ"""
    if not _remove_lock_if_token(lock, token):
        print("[quota][warn] lock ถูกโปรเซสอื่นถือแทนแล้ว (เราช้าเกิน LOCK_STALE_S) — ไม่ลบ")


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path: Path) -> threading.Lock:
    """lock ระดับเธรดต่อไฟล์ — กันเธรดในโปรเซสเดียวกัน polling ไฟล์ lock แย่งกัน"""
    key = str(path)
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


def _acquire_file_lock(lock: Path, deadline: float) -> str:
    """สร้างไฟล์ .lock ด้วย O_EXCL แล้วเขียน token ของตัวเองลงไป — คืน token, เกิน deadline raise"""
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            # Windows: ไฟล์ lock ที่กำลังถูกลบอยู่จะตอบ PermissionError -> ลองใหม่เหมือนถูกล็อก
            _break_stale_lock(lock)
            if time.monotonic() >= deadline:
                raise QuotaStoreError("รอ lock ของโควตานานเกินไป ปฏิเสธคำขอชั่วคราว") from None
            time.sleep(0.005)
            continue
        except OSError as e:
            raise QuotaStoreError(f"สร้าง lock ของโควตาไม่ได้: {e}") from e
        try:
            os.write(fd, token.encode("ascii"))
        finally:
            os.close(fd)
        return token


@contextmanager
def _quota_lock(path: Path, timeout: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """lock ระดับไฟล์ข้ามโปรเซส (O_EXCL บนไฟล์ .lock) ซ้อนกับ lock ระดับเธรด พร้อม timeout"""
    thread_lock = _thread_lock_for(path)
    if not thread_lock.acquire(timeout=timeout):
        raise QuotaStoreError("รอ lock ของโควตานานเกินไป ปฏิเสธคำขอชั่วคราว")
    try:
        lock = path.with_name(f"{path.name}.lock")
        token = _acquire_file_lock(lock, time.monotonic() + timeout)
        try:
            yield
        finally:
            _release_own_lock(lock, token)
    finally:
        thread_lock.release()


def check_and_consume_quota(username: str, tier: str = "free", project_root: Path | str | None = None) -> bool:
    """โควตารายวันแบบ fail-closed (free = FREE_DAILY_LIMIT ต่อวันต่อ username)

    - คืน True ถ้าหักได้ (หรือ tier paid), False ถ้าเกินโควตาแล้ว
    - raise QuotaStoreError ถ้าไฟล์เสีย/อ่านไม่ได้/ล็อกไม่ได้ — ไม่รีเซ็ตโควตาเด็ดขาด
    - อ่าน-ตรวจ-เขียน ทำภายใต้ lock เดียวกัน จึงไม่เกิด lost update
    """
    if tier == "paid":
        return True
    limit = FREE_DAILY_LIMIT if tier == "free" else 0
    path = _quota_path(project_root)
    try:
        return _consume_locked(path, username, limit)
    except QuotaStoreError:
        raise
    except OSError as e:  # PermissionError จาก os.replace/lock ฯลฯ → ตาม docstring
        raise QuotaStoreError(f"บันทึกโควตาไม่ได้: {e}") from e


def _consume_locked(path: Path, username: str, limit: int) -> bool:
    """อ่าน-ตรวจ-เขียนโควตาภายใต้ lock เดียว (ผู้เรียกแปลง OSError เป็น QuotaStoreError)"""
    with _quota_lock(path):
        data = _load_quota(path)
        if limit == 0:
            return True
        today = datetime.now().strftime("%Y-%m-%d")
        entry = data.get(username)
        count = entry["count"] if entry and entry["date"] == today else 0
        if count >= limit:
            return False
        data[username] = {"date": today, "count": count + 1}
        _write_quota_atomic(path, data)
        return True
