"""auth_backend.py — "เต้ารับมาตรฐาน" สำหรับการพิสูจน์ตัวตนของ LCA

ไอเดีย (9arm): วันนี้ server.py รู้วิธี auth อยู่ในตัว — master token = CEO,
X-API-Key ไปเช็คกับ org_store, ไม่มี token + มาจาก 127.0.0.1 = local CEO
ตรรกะนี้ดีและพิสูจน์แล้ว แต่มันฝังอยู่ใน handler ตัวเดียว พอวันหนึ่งต้องรองรับ
SSO / OIDC / JWT เราไม่อยากไปผ่า handler เราทำ **interface มาตรฐาน** ของ
"token (+ ที่มา) → ตัวตน (role)" ไว้ แล้ววิธี auth ใหม่เสียบเองได้

ตัวตนที่คืน = dict:
    {"role": "CEO"|"ADMIN"|"USER", "source": "<ที่มา>", "owner": "<ถ้ามี>"}
    คืน None = พิสูจน์ไม่ผ่าน (ผู้เรียกตอบ 401/403 เอง)

- LocalAuthBackend: ห่อตรรกะเดิม (master token + org_store api key + local CEO)
- StaticTokenBackend: token→role แบบ map ตายตัว — พิสูจน์ว่าขอบเขตสะอาด (impl ที่ 2)
  + เหมาะกับ deploy เล็ก ๆ / เทส

เลือก backend ด้วย config (ไม่ hardcode):
  AUTH_BACKEND = local | static        (default local)
  STATIC_TOKENS = '{"tok":"ROLE", ...}' (เมื่อ static; JSON string)

stdlib ล้วน — ไม่เพิ่ม dependency
"""

from __future__ import annotations

import hmac
import json
from pathlib import Path

from app import config_manager
from app import org_store

LOCAL_IPS = ("127.0.0.1", "::1", "localhost")
VALID_ROLES = ("CEO", "ADMIN", "USER")


class AuthBackend:
    """เต้ารับมาตรฐาน: รับ token (+ ที่มา) คืนตัวตน หรือ None"""
    name = "base"

    def authenticate(self, token: str | None, client_ip: str | None = None) -> dict | None:
        raise NotImplementedError


class LocalAuthBackend(AuthBackend):
    """ตรรกะเดิมของ server รวมไว้ที่เดียว — ทดสอบแยกได้ และเปลี่ยนภายหลังได้โดยไม่แตะ handler

    ลำดับ (เหมือน server.py):
    1. master token ตรง → CEO
    2. token ตรงกับ api key ใน org_store → USER (แนบ owner/tier)
    3. ไม่มี token + มาจาก localhost → CEO (โหมด local บนเครื่องตัวเอง)
    4. อื่น ๆ → None
    """
    name = "local"

    def __init__(self, project_root, master_token: str | None):
        self.project_root = Path(project_root)
        self.master_token = master_token or None

    def authenticate(self, token, client_ip=None) -> dict | None:
        token = (token or "").strip() or None
        # เทียบ token แบบ constant-time (hmac.compare_digest) กัน timing attack
        if token and self.master_token and hmac.compare_digest(token, self.master_token):
            return {"role": "CEO", "source": "master_token"}
        if token:
            rec = org_store.verify_api_key(self.project_root, token)
            if rec:
                return {"role": "USER", "source": "api_key",
                        "owner": rec.get("owner"), "tier": rec.get("tier"),
                        "key_id": rec.get("key_id")}
            return None  # ให้ token มาแต่ไม่ถูก = ไม่ fallback เป็น local
        # ไม่มี token เลย — อนุญาตเฉพาะเครื่องตัวเอง (local mode)
        if client_ip and client_ip in LOCAL_IPS:
            return {"role": "CEO", "source": "local"}
        return None


class StaticTokenBackend(AuthBackend):
    """token→role แบบ map ตายตัว — พิสูจน์ขอบเขต + deploy เล็ก/เทส (impl ที่ 2)"""
    name = "static"

    def __init__(self, tokens: dict | None = None):
        # เก็บเฉพาะ role ที่ถูกต้อง — กัน config เพี้ยนทำให้ได้สิทธิ์มั่ว
        self.tokens = {
            str(k): str(v).upper()
            for k, v in (tokens or {}).items()
            if str(v).upper() in VALID_ROLES
        }

    def authenticate(self, token, client_ip=None) -> dict | None:
        token = (token or "").strip() or None
        if not token:
            return None
        # เทียบ token กับทุก entry ด้วย compare_digest เสมอ (ไม่หยุด early) กัน timing attack
        matched = None
        for known, role in self.tokens.items():
            if hmac.compare_digest(token, known):
                matched = role
                # ไม่ break — วิ่งต่อให้ครบ ทำให้เวลาคงที่ไม่ว่าตรงที่ไหน
        if matched is None:
            return None
        return {"role": matched, "source": "static"}


def get_auth_backend(project_root, master_token: str | None = None) -> AuthBackend:
    """เลือก backend จาก config (default local) — อ่านจากที่คนตั้งเท่านั้น"""
    project_root = Path(project_root)
    sel = (config_manager.get_key(project_root, "AUTH_BACKEND") or "local").strip().lower()
    if sel == "static":
        raw = config_manager.get_key(project_root, "STATIC_TOKENS") or "{}"
        try:
            tokens = json.loads(raw)
            if not isinstance(tokens, dict):
                tokens = {}
        except (ValueError, TypeError):
            tokens = {}
        return StaticTokenBackend(tokens)
    return LocalAuthBackend(project_root, master_token)


def authenticate(project_root, token, client_ip=None, master_token: str | None = None) -> dict | None:
    """สะดวก: เลือก backend ตาม config แล้ว authenticate — ผู้เรียกเรียกตัวนี้ตัวเดียวจบ"""
    return get_auth_backend(project_root, master_token).authenticate(token, client_ip)
