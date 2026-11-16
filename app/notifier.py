"""
notifier.py — แจ้งเตือนเหตุการณ์ออก Discord (webhook) + Email (ทางเดียว) ด้วย stdlib ล้วน

ทำไมต้องมี (docs/AGENT_ORG.md): องค์กร LCA ต้องส่งข่าว "งานใหม่/เสร็จ/บั๊ก/เงินเข้า-รออนุมัติ"
ให้คนรู้โดยไม่ต้องเฝ้าจอ — Discord group ผ่าน Incoming Webhook, Email ส่งออกอย่างเดียว

ปรัชญา (สไตล์เดิมของโปรเจกต์):
- stdlib เท่านั้น: urllib (Discord webhook POST), smtplib + email (อีเมล)
- config-driven ผ่าน config_manager (Rule 23): อ่าน webhook URL / SMTP creds จาก config.json
  ที่ gitignored — **ไม่ commit, ไม่ print ค่า secret เต็ม ๆ**
- degrade graceful: ไม่มี config ของช่องไหน → ข้ามช่องนั้นเงียบ ๆ (log ว่า skipped) ไม่ crash
- ไม่โยน exception ออกไปให้ผู้เรียกพัง — คืน dict สรุปผลต่อช่องแทน (ทดสอบด้วย mock ได้)

Config keys (ใส่ใน config.json):
    DISCORD_WEBHOOK_URL
    SMTP_HOST, SMTP_PORT (ดีฟอลต์ 587), SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TO

Interface:
    notify(project_root, event, text, channels=("discord","email")) -> dict
        คืน {"discord": "<ผล>", "email": "<ผล>"} เฉพาะช่องที่ร้องขอ
        ค่าผล: "sent" | "skipped (no config)" | "error: <ย่อ>"
"""

from __future__ import annotations

import json
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

from app import config_manager

DISCORD_TIMEOUT = 10  # วินาที
SMTP_TIMEOUT = 15
VALID_CHANNELS = ("discord", "email")


def _compose(event: str, text: str) -> str:
    event = (event or "").strip()
    return f"**[{event}]** {text}" if event else text


def _send_discord(project_root: Path, event: str, text: str) -> str:
    webhook = config_manager.get_key(project_root, "DISCORD_WEBHOOK_URL")
    if not webhook:
        return "skipped (no config)"
    payload = json.dumps({"content": _compose(event, text)}).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "LCA-notifier/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=DISCORD_TIMEOUT) as resp:
            # Discord ตอบ 204 No Content เมื่อสำเร็จ (2xx ถือว่าผ่าน)
            if 200 <= resp.status < 300:
                return "sent"
            return f"error: http {resp.status}"
    except urllib.error.HTTPError as e:
        return f"error: http {e.code}"
    except (urllib.error.URLError, OSError) as e:
        # ไม่เผย webhook (มี secret) — log แค่เหตุผลย่อ
        return f"error: {e.__class__.__name__}"


def _send_email(project_root: Path, event: str, text: str) -> str:
    host = config_manager.get_key(project_root, "SMTP_HOST")
    user = config_manager.get_key(project_root, "SMTP_USER")
    password = config_manager.get_key(project_root, "SMTP_PASS")
    sender = config_manager.get_key(project_root, "SMTP_FROM") or user
    recipient = config_manager.get_key(project_root, "SMTP_TO")
    if not (host and sender and recipient):
        return "skipped (no config)"
    try:
        port = int(config_manager.get_key(project_root, "SMTP_PORT") or 587)
    except (TypeError, ValueError):
        port = 587

    msg = EmailMessage()
    msg["Subject"] = f"[LCA] {event}".strip() or "[LCA] notification"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(text)

    try:
        with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass  # เซิร์ฟเวอร์ไม่รองรับ STARTTLS — ส่งต่อแบบไม่เข้ารหัส (ขึ้นกับ config ผู้ใช้)
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return "sent"
    except (smtplib.SMTPException, OSError) as e:
        return f"error: {e.__class__.__name__}"


def notify(project_root: Path, event: str, text: str,
           channels=VALID_CHANNELS) -> dict:
    """ส่งแจ้งเตือน 1 เหตุการณ์ออกช่องที่ร้องขอ — คืน dict สรุปผลต่อช่อง
    ไม่เคย raise (ยกเว้น text ว่าง = ValueError เพราะเป็น bug ของผู้เรียก)"""
    text = (text or "").strip()
    if not text:
        raise ValueError("ต้องระบุ text ของการแจ้งเตือน")
    result = {}
    for ch in channels:
        if ch == "discord":
            result["discord"] = _send_discord(project_root, event, text)
        elif ch == "email":
            result["email"] = _send_email(project_root, event, text)
        else:
            result[ch] = "error: unknown channel"
    return result


# ---------- Adapter interface (ตระกูลเดียวกับ model_backend / storage_backend / auth_backend) ----------
# ของ 3 ช่อง (discord/email) ด้านบนพิสูจน์แล้วว่าใช้ได้ — เราไม่รื้อ แค่ครอบ "เต้ารับมาตรฐาน"
# ให้ผู้เรียกใช้ interface เดียว แล้วช่องใหม่ (LINE, Slack, webhook กลาง ฯลฯ) เสียบเองได้

class Notifier:
    """เต้ารับมาตรฐาน: ส่ง 1 เหตุการณ์ออกไป — คืน dict สรุปผลต่อช่อง"""
    name = "base"

    def send(self, event: str, text: str) -> dict:
        raise NotImplementedError


class MultiChannelNotifier(Notifier):
    """ของที่พิสูจน์แล้ววันนี้ — ห่อ notify() เดิม (discord + email ตาม config)"""
    name = "multichannel"

    def __init__(self, project_root, channels=VALID_CHANNELS):
        self.project_root = Path(project_root)
        self.channels = tuple(channels)

    def send(self, event: str, text: str) -> dict:
        return notify(self.project_root, event, text, channels=self.channels)


class NullNotifier(Notifier):
    """ไม่ส่งออกจริง — บันทึกว่าถูกเรียก (พิสูจน์ขอบเขต + ปิดการแจ้งเตือน/เทส)"""
    name = "null"

    def __init__(self):
        self.sent: list = []

    def send(self, event: str, text: str) -> dict:
        self.sent.append({"event": event, "text": text})
        return {"null": "noop"}


def get_notifier(project_root) -> Notifier:
    """เลือก notifier จาก config (default multichannel) — อ่านจากที่คนตั้งเท่านั้น
      NOTIFIER_BACKEND = multichannel | null   (default multichannel)
      NOTIFIER_CHANNELS = 'discord,email'      (เมื่อ multichannel; ไม่ใส่ = ทั้งคู่)
    """
    project_root = Path(project_root)
    sel = (config_manager.get_key(project_root, "NOTIFIER_BACKEND") or "multichannel").strip().lower()
    if sel == "null":
        return NullNotifier()
    raw = config_manager.get_key(project_root, "NOTIFIER_CHANNELS")
    if raw:
        chans = tuple(c.strip() for c in raw.split(",") if c.strip() in VALID_CHANNELS)
        chans = chans or VALID_CHANNELS
    else:
        chans = VALID_CHANNELS
    return MultiChannelNotifier(project_root, channels=chans)
