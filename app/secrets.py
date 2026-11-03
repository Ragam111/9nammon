"""secrets.py — API keys at rest (Windows DPAPI, with a documented fallback).

What this module does
    seal a secret so ``config.json`` / ``connections.json`` / ``config_versions.json``
    keep a reference, not the plaintext. Read it back with ``reveal``. Callers that
    already use ``config_manager.get_key`` or ``connections.get(..., raw=True)``
    still receive the plaintext. Nothing here is written to a log line.

Windows
    ``CryptProtectData`` / ``CryptUnprotectData`` via ctypes (stdlib only).
    Scope is CurrentUser: ``dwFlags`` is ``CRYPTPROTECT_UI_FORBIDDEN`` and does
    **not** include ``CRYPTPROTECT_LOCAL_MACHINE`` (0x04). Only the same Windows
    user can decrypt. No extra package.

Non-Windows
    ``keyring`` is used only when it is declared in ``requirements.txt``.
    It is not: that file lists ``psutil`` only. Importing a keyring that happens
    to be installed in the environment would hide secrets in a backend this
    repo does not pin, so it is ignored.

    Fallback (this is what Linux and macOS use today): the secret is stored in
    ``<project_root>/secrets.bin`` and the file mode is forced to ``0o600``.
    A one-line warning is printed once per process. The warning names the
    mechanism, never the secret. Protection on this path is the file mode,
    not DPAPI encryption. Copying the file to another account that can read
    it reveals the secrets.

Migration
    ``remember_plaintext`` writes the secret first, then the caller replaces
    the JSON value with ``{"$lca_secret_ref": "<name>"}``. If sealing fails,
    the plaintext is left where it was. A corrupt ``secrets.bin`` is never
    overwritten. ``reveal`` failure does not delete the stored entry.

Never log secrets. Exception text and warnings use type names and entry
names only.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import threading
from ctypes import wintypes
from pathlib import Path

SECRETS_FILE_NAME = "secrets.bin"
REF_KEY = "$lca_secret_ref"
SCHEMA = 1
KEYRING_SERVICE = "LocalCodeAssistant"

# CryptProtectData dwFlags. CurrentUser is the default scope; do not set
# CRYPTPROTECT_LOCAL_MACHINE or the blob would be machine-wide.
CRYPTPROTECT_UI_FORBIDDEN = 0x01
CRYPTPROTECT_LOCAL_MACHINE = 0x04

FILE_FALLBACK_WARNING = (
    "[secrets][warn] DPAPI (CryptProtectData, CurrentUser) ใช้ได้บน Windows เท่านั้น "
    "และแพ็กเกจ keyring ไม่ได้อยู่ใน requirements.txt (มีแต่ psutil) — "
    "เก็บความลับใน secrets.bin โหมด 0600 แทน "
    "การป้องกันคือสิทธิ์ของไฟล์ ไม่ใช่การเข้ารหัสแบบ DPAPI"
)

# Names that are credentials. Feature flags, model ids, and URLs without a
# secret stay plaintext so config.json remains hand-editable for those keys.
_EXACT_SECRET_NAMES = frozenset({
    "API_KEY",
    "STATIC_TOKENS",
    "DISCORD_WEBHOOK_URL",
    "SMTP_PASS",
})
_SECRET_SUFFIXES = (
    "_API_KEY",
    "_TOKEN",
    "_TOKENS",
    "_PASS",
    "_PASSWORD",
    "_SECRET",
    "_WEBHOOK_URL",
)

_lock = threading.Lock()
_file_fallback_warned = False
_keyring_dep_cache: bool | None = None


class SecretError(Exception):
    """Store/load failed. The message must not contain a secret value."""


class DATA_BLOB(ctypes.Structure):
    _fields_ = (
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    )


def using_dpapi() -> bool:
    """True when this process should call CryptProtectData (Windows)."""
    return sys.platform == "win32"


def is_secret_name(name: str) -> bool:
    """True when a config.json key holds a credential, not a setting."""
    n = str(name or "").strip().upper()
    if not n:
        return False
    if n in _EXACT_SECRET_NAMES:
        return True
    return any(n.endswith(suffix) for suffix in _SECRET_SUFFIXES)


def make_ref(name: str) -> dict:
    return {REF_KEY: name}


def ref_name(value) -> str | None:
    """Return the entry name if ``value`` is a sealed reference, else None."""
    if isinstance(value, dict):
        name = value.get(REF_KEY)
        if isinstance(name, str) and name:
            return name
    return None


def keyring_is_dependency() -> bool:
    """True only when requirements.txt declares keyring.

    A keyring package that merely happens to be installed is not used.
    """
    global _keyring_dep_cache
    if _keyring_dep_cache is not None:
        return _keyring_dep_cache
    req = Path(__file__).resolve().parent.parent / "requirements.txt"
    found = False
    try:
        text = req.read_text(encoding="utf-8")
    except OSError:
        _keyring_dep_cache = False
        return False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if not line:
            continue
        pkg = line.split("==", 1)[0].split(">=", 1)[0].split("<=", 1)[0]
        pkg = pkg.split("~=", 1)[0].split("[", 1)[0].strip()
        if pkg == "keyring":
            found = True
            break
    _keyring_dep_cache = found
    return found


def _import_keyring():
    """Import keyring after ``keyring_is_dependency`` is true. Tests may patch this."""
    import keyring  # noqa: WPS433 — optional, and only after the requirements check
    return keyring


def _load_keyring():
    if not keyring_is_dependency():
        return None
    try:
        return _import_keyring()
    except Exception as exc:  # ImportError or a broken install
        print(f"[secrets][warn] โหลด keyring ไม่ได้: {type(exc).__name__}")
        return None


def _warn_file_fallback() -> None:
    global _file_fallback_warned
    if _file_fallback_warned:
        return
    _file_fallback_warned = True
    print(FILE_FALLBACK_WARNING)


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\n" in name or "\x00" in name:
        raise SecretError("ชื่อที่เก็บความลับไม่ถูกต้อง")
    if len(name) > 300:
        raise SecretError("ชื่อที่เก็บความลับยาวเกินไป")
    return name


def _bytes_to_blob(data: bytes):
    buf = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    return blob, buf


def dpapi_protect(data: bytes, crypt_protect, local_free) -> bytes:
    """Call CryptProtectData with CurrentUser scope.

    ``crypt_protect`` is CryptProtectData (or a test double). ``local_free`` is
    LocalFree. Flags are ``CRYPTPROTECT_UI_FORBIDDEN`` only — LocalMachine is
    not set. ``data`` must be non-empty bytes.
    """
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise SecretError("DPAPI รับข้อมูลว่างไม่ได้")
    blob_in, pinned = _bytes_to_blob(bytes(data))
    blob_out = DATA_BLOB()
    ok = crypt_protect(
        ctypes.pointer(blob_in),
        None,   # description (would otherwise be a window title)
        None,   # optional entropy
        None,
        None,   # prompt struct — no UI
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.pointer(blob_out),
    )
    # ``pinned`` must stay alive until the call returns.
    del pinned
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        if blob_out.pbData:
            local_free(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def dpapi_unprotect(data: bytes, crypt_unprotect, local_free) -> bytes:
    """Call CryptUnprotectData. Same flags as ``dpapi_protect`` (CurrentUser)."""
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise SecretError("DPAPI รับข้อมูลว่างไม่ได้")
    blob_in, pinned = _bytes_to_blob(bytes(data))
    blob_out = DATA_BLOB()
    ok = crypt_unprotect(
        ctypes.pointer(blob_in),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.pointer(blob_out),
    )
    del pinned
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        if blob_out.pbData:
            local_free(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def _win_protect(data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return dpapi_protect(data, crypt32.CryptProtectData, kernel32.LocalFree)


def _win_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return dpapi_unprotect(data, crypt32.CryptUnprotectData, kernel32.LocalFree)


def protect(data: bytes) -> bytes:
    """Encrypt with DPAPI CurrentUser. Linux tests patch ``using_dpapi`` and ``_win_protect``."""
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise SecretError("protect() รับ bytes ที่ไม่ว่าง")
    if not using_dpapi():
        raise SecretError("CryptProtectData ใช้ได้บน Windows เท่านั้น")
    try:
        return _win_protect(bytes(data))
    except OSError as exc:
        raise SecretError(f"CryptProtectData ไม่สำเร็จ ({type(exc).__name__})") from None


def unprotect(data: bytes) -> bytes:
    """Decrypt a blob from ``protect``. Does not delete anything on failure."""
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise SecretError("unprotect() รับ bytes ที่ไม่ว่าง")
    if not using_dpapi():
        raise SecretError("CryptUnprotectData ใช้ได้บน Windows เท่านั้น")
    try:
        return _win_unprotect(bytes(data))
    except OSError as exc:
        raise SecretError(f"CryptUnprotectData ไม่สำเร็จ ({type(exc).__name__})") from None


def _secrets_path(project_root) -> Path:
    return Path(project_root) / SECRETS_FILE_NAME


def _read_store(path: Path) -> dict:
    """Load secrets.bin. Missing file → empty store. Corrupt file → SecretError
    and the file is left untouched."""
    if not path.exists():
        return {"schema": SCHEMA, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecretError(
            f"อ่าน {SECRETS_FILE_NAME} ไม่ได้ ({type(exc).__name__}) — ไม่เขียนทับ"
        ) from None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        raise SecretError(f"รูปแบบ {SECRETS_FILE_NAME} ไม่ถูกต้อง — ไม่เขียนทับ")
    data.setdefault("schema", SCHEMA)
    return data


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if fd >= 0:
            os.close(fd)
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    if os.name == "posix":
        os.chmod(path, 0o600)


def _write_store(path: Path, data: dict) -> None:
    payload = json.dumps(
        {"schema": SCHEMA, "entries": data.get("entries", {})},
        ensure_ascii=False,
        indent=2,
    )
    try:
        _atomic_write(path, payload)
    except OSError as exc:
        raise SecretError(
            f"เขียน {SECRETS_FILE_NAME} ไม่ได้ ({type(exc).__name__})"
        ) from None


def _wrap(name: str, plaintext: str) -> dict:
    raw = plaintext.encode("utf-8")
    if using_dpapi():
        blob = protect(raw)
        return {"alg": "dpapi", "blob": base64.b64encode(blob).decode("ascii")}
    keyring_mod = _load_keyring()
    if keyring_mod is not None:
        try:
            keyring_mod.set_password(KEYRING_SERVICE, name, plaintext)
        except Exception as exc:
            print(
                f"[secrets][warn] keyring เก็บ {name} ไม่ได้: {type(exc).__name__} "
                "— ใช้ไฟล์โหมด 0600 แทน"
            )
        else:
            return {"alg": "keyring", "service": KEYRING_SERVICE}
    _warn_file_fallback()
    return {"alg": "file0600", "v": plaintext}


def _unwrap(name: str, entry: dict) -> str | None:
    if not isinstance(entry, dict):
        print(f"[secrets][warn] รายการ {name} ไม่ใช่รูปแบบที่รู้จัก — ไม่ลบค่าที่เก็บไว้")
        return None
    alg = entry.get("alg")
    if alg == "dpapi":
        try:
            blob = base64.b64decode(entry.get("blob") or "", validate=True)
            return unprotect(blob).decode("utf-8")
        except (SecretError, ValueError, UnicodeDecodeError) as exc:
            print(
                f"[secrets][warn] ถอด DPAPI ของ {name} ไม่ได้: {type(exc).__name__} "
                "— ไม่ลบค่าที่เก็บไว้"
            )
            return None
    if alg == "keyring":
        keyring_mod = _load_keyring()
        if keyring_mod is None:
            print(f"[secrets][warn] อ่าน {name} จาก keyring ไม่ได้ — ไม่ลบค่าที่เก็บไว้")
            return None
        try:
            service = entry.get("service") or KEYRING_SERVICE
            value = keyring_mod.get_password(service, name)
        except Exception as exc:
            print(
                f"[secrets][warn] อ่าน {name} จาก keyring ไม่ได้: {type(exc).__name__} "
                "— ไม่ลบค่าที่เก็บไว้"
            )
            return None
        return value if isinstance(value, str) else None
    if alg == "file0600":
        value = entry.get("v")
        return value if isinstance(value, str) else None
    print(f"[secrets][warn] ไม่รู้จักวิธีเก็บของ {name} — ไม่ลบค่าที่เก็บไว้")
    return None


def store(project_root, name: str, plaintext: str) -> None:
    """Save ``plaintext`` under ``name``, overwriting that entry only.

    Other entries are kept. A corrupt store is not replaced. Callers that must
    not destroy a different existing value use ``store_keeping_existing``.
    """
    name = _check_name(name)
    if not isinstance(plaintext, str) or plaintext == "":
        raise SecretError("ไม่เก็บความลับที่ว่าง")
    entry = _wrap(name, plaintext)
    path = _secrets_path(project_root)
    with _lock:
        data = _read_store(path)
        data["entries"][name] = entry
        _write_store(path, data)


def store_keeping_existing(project_root, preferred: str, plaintext: str) -> str:
    """Store ``plaintext`` under ``preferred`` or the next free name.

    An entry that already holds a different value, or that cannot be read, is
    left in place. Returns the name that now holds ``plaintext``.
    """
    preferred = _check_name(preferred)
    if not isinstance(plaintext, str) or plaintext == "":
        raise SecretError("ไม่เก็บความลับที่ว่าง")
    name = preferred
    for n in range(2, 52):
        try:
            exists = has_entry(project_root, name)
        except SecretError:
            raise
        if not exists:
            store(project_root, name, plaintext)
            return name
        try:
            current = reveal(project_root, name)
        except SecretError:
            current = None
        if current == plaintext:
            return name
        name = _check_name(f"{preferred}-{n}")
    raise SecretError("หาที่ว่างใน secrets.bin ไม่ได้")


def reveal(project_root, name: str) -> str | None:
    """Return the plaintext, or None if it is missing or cannot be opened.

    Failure does not delete the entry.
    """
    name = _check_name(name)
    path = _secrets_path(project_root)
    with _lock:
        if not path.exists():
            return None
        data = _read_store(path)
        entry = data["entries"].get(name)
    if entry is None:
        return None
    return _unwrap(name, entry)


def has_entry(project_root, name: str) -> bool:
    """True when an entry exists, even if it cannot currently be decrypted."""
    name = _check_name(name)
    path = _secrets_path(project_root)
    with _lock:
        if not path.exists():
            return False
        data = _read_store(path)
        return name in data["entries"]


def delete(project_root, name: str) -> None:
    """Remove one entry. A corrupt store is left as-is (nothing is wiped)."""
    name = _check_name(name)
    path = _secrets_path(project_root)
    with _lock:
        if not path.exists():
            return
        data = _read_store(path)
        if name not in data["entries"]:
            return
        del data["entries"][name]
        _write_store(path, data)


def config_entry_name(key_name: str) -> str:
    return f"config:{key_name}"


def snapshot_entry_name(version_id: str, key_name: str) -> str:
    return f"snapshot:{version_id}:{key_name}"


def connection_entry_name(conn_id: str) -> str:
    return f"conn:{conn_id}"
