"""cluster_forward.py — ส่งงาน chat ไปทำที่ node อื่นจริง (HPC ขั้น 3+: จาก "ตัดสินใจ" → "ลงมือ")

ต่อจาก cluster_router (ตัดสินใจว่างานควรไป node ไหน) ตัวนี้คือ "แขน" ที่ยื่นงานไปจริง:
hub รับ /api/chat → เลือก node ที่พร้อม → forward ไปที่ /api/chat ของ node นั้น → เอาคำตอบกลับมา

ปรัชญา (สไตล์เดิม + 9arm-honest):
- **opt-in**: ปิดเป็นค่าเริ่มต้น (CLUSTER_FORWARD_ENABLED). ไม่เปิด = ทำงานที่เครื่องนี้เองเหมือนเดิม
  (ไม่เปลี่ยนพฤติกรรมใคร จนกว่าจะตั้งใจเปิด)
- **degrade graceful**: forward พลาด (node ล่มกลางคัน/ต่อไม่ติด) → คืนสัญญาณให้ผู้เรียก fallback
  ไปทำ local แทน — งานของผู้ใช้ต้องไม่หายเพราะ node ปลายทางมีปัญหา
- **ปลอดภัย**: hub ต้องมี token (CLUSTER_FORWARD_TOKEN) ไว้ยืนยันตัวกับ node ปลายทาง
  (node เปิดออกนอก 127.0.0.1 บังคับ auth อยู่แล้ว). ไม่ตั้ง token = forward ไม่ได้ → local
- stdlib ล้วน (urllib/json). เน็ตคือคอขวด: timeout กว้างกว่า health check (งาน generate ใช้เวลาจริง)

Config keys (config.json, gitignored):
    CLUSTER_FORWARD_ENABLED   เปิด forward ไหม (1/true/yes) — default ปิด
    CLUSTER_FORWARD_TOKEN     token ที่ hub ใช้ auth กับ node ปลายทาง (X-Auth-Token)
    CLUSTER_FORWARD_STRATEGY  prefer_free (default) | round_robin
    CLUSTER_FORWARD_TIMEOUT   วินาที (default 300 — generate ช้าได้บนเครื่องอ่อน)

Interface:
    is_enabled(project_root) -> bool
    pick_target(project_root, rr_index) -> {node, reason, rr_index}   # node=None = ทำ local
    forward_chat(node_url, token, payload, timeout) -> str            # blocking; raise ForwardError
    forward_chat_stream(node_url, token, payload, timeout) -> gen[str] # yield delta; raise ForwardError
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from app import cluster_router, cluster_store, config_manager

CHAT_PATH = "/api/chat"
CHAT_STREAM_PATH = "/api/chat/stream"
DEFAULT_TIMEOUT = 300.0


class ForwardError(Exception):
    """forward ไป node ปลายทางไม่สำเร็จ — ผู้เรียกควร fallback ไปทำ local"""


def is_enabled(project_root) -> bool:
    val = str(config_manager.get_key(project_root, "CLUSTER_FORWARD_ENABLED") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _token(project_root) -> str:
    return (config_manager.get_key(project_root, "CLUSTER_FORWARD_TOKEN") or "").strip()


def _strategy(project_root) -> str:
    s = (config_manager.get_key(project_root, "CLUSTER_FORWARD_STRATEGY") or "prefer_free").strip()
    return s or "prefer_free"


def _timeout(project_root) -> float:
    try:
        return float(config_manager.get_key(project_root, "CLUSTER_FORWARD_TIMEOUT") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def pick_target(project_root, rr_index: int = 0) -> dict:
    """เลือก node ปลายทางสำหรับงานใหม่ (ดู health ปัจจุบันของคลัสเตอร์)
    คืน {node, reason, rr_index(ถัดไป)} — node=None = ไม่มีตัวพร้อม → ทำ local เอง"""
    health = cluster_store.cluster_health(project_root)
    res = cluster_router.pick_node(health.get("nodes", []),
                                   strategy=_strategy(project_root), rr_index=rr_index)
    return res


def _request(node_url: str, path: str, token: str, payload: dict, timeout: float):
    base = cluster_store._normalize_url(node_url)   # กัน scheme แปลก (ใช้ตัวเดียวกับ store)
    headers = {"Content-Type": "application/json", "User-Agent": "LCA-cluster-forward/1.0"}
    if token:
        headers["X-Auth-Token"] = token
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="POST", headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def forward_chat(node_url: str, token: str, payload: dict, timeout: float = DEFAULT_TIMEOUT) -> str:
    """ยื่นงาน chat (blocking) ไป node ปลายทาง → คืน reply. พลาด → ForwardError (ให้ผู้เรียก fallback)"""
    try:
        resp = _request(node_url, CHAT_PATH, token, payload, timeout)
    except urllib.error.HTTPError as e:
        raise ForwardError(f"node ตอบ http {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ForwardError(f"ต่อ node ไม่ได้ ({e.__class__.__name__})")
    with resp:
        try:
            body = json.loads(resp.read().decode("utf-8"))
        except ValueError:
            raise ForwardError("คำตอบ node ไม่ใช่ JSON")
    reply = body.get("reply")
    if not reply:
        raise ForwardError("node ไม่ส่ง reply กลับมา")
    return reply


def forward_chat_stream(node_url: str, token: str, payload: dict, timeout: float = DEFAULT_TIMEOUT):
    """ยื่นงาน chat แบบ stream ไป node ปลายทาง แล้ว relay คำตอบทีละ chunk กลับมา (generator)

    อ่าน SSE ของ node (`data: {"delta"/"done"/"error"}`) แล้ว yield เฉพาะข้อความ delta.
    node ส่ง error กลางคัน / ต่อไม่ติด → ForwardError. *การ fallback หลัง yield ไปแล้ว
    ทำไม่ได้* (คำตอบบางส่วนออกไปหาผู้ใช้แล้ว) → ผู้เรียกต้อง fallback ก่อน yield chunk แรกเท่านั้น"""
    try:
        resp = _request(node_url, CHAT_STREAM_PATH, token, payload, timeout)
    except urllib.error.HTTPError as e:
        raise ForwardError(f"node ตอบ http {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ForwardError(f"ต่อ node ไม่ได้ ({e.__class__.__name__})")
    with resp:
        for raw in resp:
            line = raw.strip()
            if not line.startswith(b"data:"):
                continue
            try:
                evt = json.loads(line[5:].strip())
            except ValueError:
                continue
            if "delta" in evt:
                yield evt["delta"]
            elif evt.get("error"):
                raise ForwardError(str(evt["error"]))
            elif evt.get("done"):
                break
