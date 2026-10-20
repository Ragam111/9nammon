"""cluster_store.py — ทะเบียน + มอนิเตอร์ "คลัสเตอร์ LCA" (หลาย node รวมดูที่เดียว)

ทำไมต้องมี (ตามที่ user สั่ง): LCA ไม่ได้รันเครื่องเดียว — เครื่องพี่ + เพื่อน +
เครื่องสาขาอื่น ต่างก็เป็น node ที่รัน server.py ของตัวเอง แต่ละ node มี /api/health
อยู่แล้ว (ollama up?, RAM ตึง?, โมเดลที่แนะนำ, backend). ตัวนี้ = "จอรวม" ดึง health
จากทุก node มาไว้ที่เดียว ให้ CEO/ADMIN เห็นสุขภาพคลัสเตอร์ในหน้าเดียว

9arm-honest: นี่ไม่ใช่ HPC scheduler/orchestrator — มันคือ health aggregator ที่
"ทำได้จริงวันนี้" บนของที่มี (แต่ละ node เสิร์ฟ /api/health เองอยู่แล้ว). การสั่งงาน
ข้าม node / load-balance เป็นงานอนาคต ตัวนี้วาง "การมองเห็น" ก่อน — วัดก่อนจัดการ

สไตล์เดิม: stdlib ล้วน (json/urllib), per-project store (cluster.json),
degrade graceful (node ล่ม = reachable:false ไม่ทำให้ทั้งจอพัง), ไม่ raise ออกนอก
ยกเว้น input ผิด (ValueError) ให้ผู้เรียกแปลงเป็น 400

Interface:
    add_node(project_root, name, url) -> dict        # ชื่อซ้ำ = อัปเดต url
    remove_node(project_root, name) -> bool
    list_nodes(project_root) -> list[dict]           # [{name, url}]
    fetch_node_health(url, timeout=2.0) -> dict       # ดึง /api/health ของ node เดียว
    cluster_health(project_root, timeout=2.0) -> dict # รวมทุก node + summary
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from app import config_manager

CLUSTER_FILE_NAME = "cluster.json"
_MAX_NAME = 60
_MAX_NODES = 100
HEALTH_PATH = "/api/health"
NODES_PATH = "/api/admin/cluster/nodes"

# config keys ของ "ตัวตน node นี้ + hub ที่สังกัด" (เก็บใน config.json ที่ gitignored)
#   NODE_NAME : ชื่อเครื่องนี้ในคลัสเตอร์
#   NODE_URL  : url ที่เครื่องอื่น/hub ใช้ต่อมาหาเครื่องนี้ (เช่น http://192.168.1.50:8420)
#   HUB_URL   : url ของ hub (เครื่องที่เป็นจอรวม) ที่เครื่องนี้จะ register ตัวเองเข้าไป
#   HUB_TOKEN : token ของ hub (X-Auth-Token) ใช้ตอน register — ไม่ print เต็ม
SETTINGS_KEYS = ("NODE_NAME", "NODE_URL", "HUB_URL", "HUB_TOKEN")


def _path(project_root: Path) -> Path:
    return Path(project_root) / CLUSTER_FILE_NAME


def _load(project_root: Path) -> list:
    p = _path(project_root)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(project_root: Path, nodes: list) -> None:
    try:
        _path(project_root).write_text(
            json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[cluster][error] เขียน {CLUSTER_FILE_NAME} ไม่ได้: {e}")


def _normalize_url(url: str) -> str:
    """รับเฉพาะ http/https + มี host — กัน scheme แปลก (file://, ftp://) ตั้งแต่ประตู"""
    url = (url or "").strip().rstrip("/")
    if not url:
        raise ValueError("ต้องระบุ url ของ node")
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError(f"url ไม่ถูกต้อง: {url!r} (ต้องเป็น http(s)://host:port)")
    return url


def list_nodes(project_root: Path) -> list:
    return _load(project_root)


def add_node(project_root: Path, name: str, url: str) -> dict:
    """เพิ่ม node (หรืออัปเดต url ถ้าชื่อซ้ำ) — คืน {name, url}"""
    name = (name or "").strip()
    if not name:
        raise ValueError("ต้องระบุ name ของ node")
    if len(name) > _MAX_NAME:
        raise ValueError(f"name ยาวเกิน {_MAX_NAME} ตัวอักษร")
    url = _normalize_url(url)
    nodes = _load(project_root)
    for n in nodes:
        if n.get("name") == name:
            n["url"] = url  # ชื่อซ้ำ = อัปเดต url (ไม่สร้างซ้ำ)
            _save(project_root, nodes)
            return {"name": name, "url": url}
    if len(nodes) >= _MAX_NODES:
        raise ValueError(f"มี node ครบ {_MAX_NODES} แล้ว (ลบตัวเก่าก่อน)")
    node = {"name": name, "url": url}
    nodes.append(node)
    _save(project_root, nodes)
    return node


def remove_node(project_root: Path, name: str) -> bool:
    name = (name or "").strip()
    nodes = _load(project_root)
    kept = [n for n in nodes if n.get("name") != name]
    if len(kept) == len(nodes):
        return False
    _save(project_root, kept)
    return True


def fetch_node_health(url: str, timeout: float = 2.0) -> dict:
    """ดึง /api/health ของ node เดียว — คืน {reachable, health}|{reachable:false, error}
    ไม่เคย raise (node ล่มเป็นเรื่องปกติของคลัสเตอร์ ต้อง degrade ไม่ใช่พัง)"""
    try:
        base = _normalize_url(url)
    except ValueError as e:
        return {"reachable": False, "error": str(e)}
    req = urllib.request.Request(base + HEALTH_PATH,
                                 headers={"User-Agent": "LCA-cluster-monitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        health = json.loads(raw)
        return {"reachable": True, "health": health}
    except urllib.error.HTTPError as e:
        return {"reachable": False, "error": f"http {e.code}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        # ValueError = JSON พัง; URLError/OSError = ต่อไม่ติด/timeout
        return {"reachable": False, "error": e.__class__.__name__}


def cluster_health(project_root: Path, timeout: float = 2.0) -> dict:
    """ดึง health จากทุก node — คืน {nodes:[...], summary:{total, up, down}}
    (ดึงแบบลำดับ: node น้อย + timeout สั้น พอสำหรับ netbook; ขนานเป็น optimize ทีหลัง)"""
    nodes = _load(project_root)
    results = []
    up = 0
    for n in nodes:
        res = fetch_node_health(n.get("url", ""), timeout=timeout)
        entry = {"name": n.get("name"), "url": n.get("url"), **res}
        if res.get("reachable"):
            up += 1
        results.append(entry)
    return {
        "nodes": results,
        "summary": {"total": len(nodes), "up": up, "down": len(nodes) - up},
    }


# ---------- Ecosystem settings: ตัวตน node นี้ + register เข้า hub ----------

def get_settings(project_root: Path) -> dict:
    """อ่านการตั้งค่า ecosystem ของเครื่องนี้ — ไม่คืน HUB_TOKEN เต็ม (แค่บอกว่าตั้งไว้ไหม)"""
    s = {k: (config_manager.get_key(project_root, k) or "") for k in SETTINGS_KEYS}
    token = s.pop("HUB_TOKEN", "")
    s["hub_token_set"] = bool(token)  # บอกสถานะ ไม่เผยค่า (Rule 23: ไม่ print secret)
    return s


def set_settings(project_root: Path, values: dict) -> dict:
    """ตั้งค่า ecosystem — เขียนเฉพาะคีย์ที่รู้จัก, validate url. คืน get_settings ใหม่"""
    for key in ("NODE_URL", "HUB_URL"):
        if values.get(key):
            _normalize_url(values[key])  # โยน ValueError ถ้า url เพี้ยน
    for key in SETTINGS_KEYS:
        if key in values and values[key] is not None:
            val = str(values[key]).strip()
            if key in ("NODE_URL", "HUB_URL") and val:
                val = _normalize_url(val)
            config_manager.set_key(project_root, key, val)
    return get_settings(project_root)


def register_with_hub(project_root: Path, timeout: float = 3.0) -> dict:
    """ประกาศตัวเครื่องนี้เข้า hub: POST {name,url} ไปที่ HUB_URL/api/admin/cluster/nodes
    ต้องตั้ง NODE_NAME, NODE_URL, HUB_URL, HUB_TOKEN ครบก่อน — degrade ไม่ raise ออกนอก
    (คืน {ok, ...} ให้ผู้เรียกแปลงเป็น response)"""
    name = config_manager.get_key(project_root, "NODE_NAME")
    node_url = config_manager.get_key(project_root, "NODE_URL")
    hub_url = config_manager.get_key(project_root, "HUB_URL")
    hub_token = config_manager.get_key(project_root, "HUB_TOKEN")
    missing = [k for k, v in (("NODE_NAME", name), ("NODE_URL", node_url),
                              ("HUB_URL", hub_url), ("HUB_TOKEN", hub_token)) if not v]
    if missing:
        return {"ok": False, "error": f"ยังตั้งค่าไม่ครบ: {', '.join(missing)}"}
    try:
        hub = _normalize_url(hub_url)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    payload = json.dumps({"name": name, "url": node_url}).encode("utf-8")
    req = urllib.request.Request(
        hub + NODES_PATH, data=payload, method="POST",
        headers={"Content-Type": "application/json", "X-Auth-Token": hub_token,
                 "User-Agent": "LCA-cluster-node/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        body = json.loads(raw) if raw else {}
        return {"ok": True, "hub": hub, "registered": body.get("node", {"name": name, "url": node_url})}
    except urllib.error.HTTPError as e:
        # 401/403 = token ผิด/สิทธิ์ไม่พอ; อื่นๆ = ตาม code (ไม่เผย token)
        return {"ok": False, "error": f"hub ตอบ http {e.code} (เช็ค HUB_TOKEN / สิทธิ์)"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "error": f"ต่อ hub ไม่ได้: {e.__class__.__name__}"}
