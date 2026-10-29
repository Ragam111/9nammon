#!/usr/bin/env python3
"""
server.py — Backend server สำหรับ index.html (MVC-style, stdlib เท่านั้น)

Model      : เรียก Ollama ผ่าน call_ollama() (import จาก local_coder.py)
Controller : LocalAssistantHandler (รับ HTTP request แปลงเป็นเรียก Model/todo_store)
View       : app/index.html (หน้าเว็บ) + JSON response (สำหรับ client อื่นๆ)

ความปลอดภัย (ตาม Rule ข้อ 12): bind 127.0.0.1 เป็นค่าเริ่มต้นเท่านั้น
ถ้าจะเปิดให้อุปกรณ์อื่นใน LAN เข้าถึง ต้องระบุ --host และ --token เอง

การใช้งาน:
    python3 server.py ./my_project --host 127.0.0.1 --port 8420
    เปิดเบราว์เซอร์ที่ http://127.0.0.1:8420
"""

import argparse
import json
import os
import socket
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent))
from local_coder import get_system_prompt  # noqa: E402
from app.todo_store import load_todos, add_todo, toggle_todo, delete_todo  # noqa: E402
from app import org_store  # noqa: E402  (ระบบองค์กร: user/role/api key/quota)
from sysmanager.sysinfo import get_system_info  # noqa: E402  (spec เครื่องสำหรับ dev view)
from app import job_queue  # noqa: E402  (คิวงาน server เก็บด้วย SQLite)
from app import history_store  # noqa: E402  (ประวัติ snapshot + error log, SQLite)
from app import finance_ledger  # noqa: E402  (บันทึกการเงิน record-only, SQLite)
from app import usage_store  # noqa: E402  (บันทึกการใช้งาน API ต่อ key, SQLite)
from app.rate_limit import RateLimiter  # noqa: E402  (จำกัด request ต่อ IP)
from app import notifier  # noqa: E402  (แจ้งเตือน Discord/email, config-driven)
from app import support_store  # noqa: E402  (รับเรื่อง support/บั๊กจากลูกค้า, SQLite)
from app import dataset_store  # noqa: E402  (เก็บตัวอย่างไว้ทำ dataset fine-tune, SQLite)
from app import config_manager  # noqa: E402  (อ่าน flag COLLECT_TRAINING_DATA จาก config.json)
from app import resource_budget  # noqa: E402  (ก้านสมอง: เลือกโมเดล/backend ตาม RAM)
from app import model_backend  # noqa: E402  (adapter: Ollama / OpenAI-compatible สลับด้วย config)
from app import cluster_store  # noqa: E402  (ทะเบียน + มอนิเตอร์ health ของหลาย node)
from app import admission  # noqa: E402  (ยามคุมจำนวน generation พร้อมกัน กัน RAM thrash เครื่องสเปกต่ำ)
from app import hw_profile  # noqa: E402  (โปรไฟล์ฮาร์ดแวร์: จัดระดับเครื่อง + แนะนำ config)
from app import config_versions  # noqa: E402  (เวอร์ชัน + rollback ของ config — กัน incident)
from app import space_store  # noqa: E402  (พื้นที่ส่วนตัว/บริษัท + ข้อความ — RBAC)
from app import cluster_router  # noqa: E402  (สมองจัดคิวงานของคลัสเตอร์ — route งานไป node ที่พร้อม)
from app import cluster_forward  # noqa: E402  (แขนคลัสเตอร์: forward งาน chat ไปทำที่ node ที่ router เลือกจริง)
from app import watchdog  # noqa: E402  (เฝ้าระบบ 24/7 + เตือนเมื่อผิดปกติ — observe/alert เท่านั้น)
from app import feature_flags  # noqa: E402  (ศูนย์กลางเปิด/ปิดฟีเจอร์ server + มอนิเตอร์)
from app import schedule_gate  # noqa: E402  (เวลาเปิด-ปิดเซิร์ฟเวอร์ตามเวลาไทย — ประหยัดค่าไฟ/cloud)
from app.agent import jobs as agent_jobs  # noqa: E402  (คิวงาน agent — ให้ n8n/automation ป้อนงาน)
from app.agent import approvals as agent_approvals  # noqa: E402  (P6: ด่านอนุมัติก่อนทำสิ่งย้อนไม่ได้)
from app import connections  # noqa: E402  (ทะเบียนต่อสมอง AI ภายนอก — Console)
from app import conn_usage  # noqa: E402  (นับ token/ค่าใช้จ่ายต่อ connection — Observability)
from app import skills_store  # noqa: E402  (Skills: prompt+สมองสำเร็จรูป ใช้ซ้ำได้)
from app import bots  # noqa: E402  (Bot: skill + run endpoint ให้ automation เรียก)
from sysmanager.monitor import collect as _collect, Analyzer as _Analyzer  # noqa: E402
from sysmanager.monitor import lca_context as _lca_context  # noqa: E402  (Phase 2: บริบท Ollama)

def _resource_root() -> Path:
    """โฟลเดอร์รากของไฟล์โปรแกรม — รองรับตอนถูกแพ็กเป็น .exe ด้วย pyinstaller
    (ตอน frozen ไฟล์ถูกแตกไว้ที่ sys._MEIPASS ไม่ใช่ข้าง __file__)"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return Path(__file__).parent


APP_DIR = _resource_root() / "app"

# ตารางหน้าเว็บ (web) ทั้งหมดในระบบ — route -> (ไฟล์ใน app/, content-type, cache?)
# เพิ่มหน้าใหม่ = เพิ่ม 1 บรรทัดที่นี่ + วางไฟล์ใน app/ (ไม่ต้องเขียน method serve ใหม่ทุกหน้า)
# ทุกหน้าเสิร์ฟ shell ได้โดยไม่ต้อง auth — ข้อมูลจริงถูก gate ที่ /api/* อีกชั้น
STATIC_ROUTES = {
    "/":        ("index.html",   "text/html; charset=utf-8",              False),
    "/dev":     ("dev.html",     "text/html; charset=utf-8",              False),
    "/login":   ("login.html",   "text/html; charset=utf-8",              False),
    "/support": ("support.html", "text/html; charset=utf-8",              False),
    "/spaces":  ("spaces.html",  "text/html; charset=utf-8",              False),
    "/install": ("install.html", "text/html; charset=utf-8",              False),
    "/console": ("console.html", "text/html; charset=utf-8",              False),
    "/app.css": ("app.css",      "text/css; charset=utf-8",               True),
    "/app.js":  ("app.js",       "application/javascript; charset=utf-8",  True),
}


def make_handler(project_root: Path, auth_token: Optional[str],
                 rate_limit_max: int = 300, rate_limit_window: float = 60.0,
                 bind_host: str = "127.0.0.1"):
    # limiter เดียวใช้ร่วมทุก thread ของ server นี้ (in-memory ต่อ process)
    # ค่าเริ่มต้น 300 req/60s ต่อ IP — กันยิงถล่มโดยไม่รบกวนการใช้งานปกติ
    api_rate_limiter = RateLimiter(rate_limit_max, rate_limit_window)
    # ยามคุม generation พร้อมกัน (admission control) — เดียวต่อ process ใช้ร่วมทุก thread
    # netbook default = 1 (กัน RAM thrash → HDD swap → ค้าง); ตั้งเพิ่มด้วย config
    gen_gate = admission.gate_from_config(project_root)
    # ตัวชี้ round-robin ของ cluster router (mutable เพื่อให้ preview วนเวียนได้จริง)
    _rr_state = [0]

    # watchdog เฝ้าระบบ 24/7 — สร้างไว้ (ยังไม่ start); main() จะ start ถ้า config เปิด
    def _ollama_reachable():
        try:
            with socket.create_connection(("127.0.0.1", 11434), timeout=0.3):
                return True
        except OSError:
            return False

    def _watchdog_check():
        down = cluster_store.cluster_health(project_root).get("summary", {}).get("down", 0)
        return watchdog.evaluate(ollama_up=_ollama_reachable(),
                                 ram_pressure=resource_budget.ram_pressure(),
                                 cluster_down=down)

    def _watchdog_notify(level, msg):
        try:
            notifier.get_notifier(project_root).send(f"watchdog:{level}", msg)
        except Exception:  # pragma: no cover - การเตือนล้มต้องไม่ล้ม watchdog
            pass

    sys_watchdog = watchdog.Watchdog(_watchdog_check, _watchdog_notify)
    if watchdog.is_enabled(project_root):
        sys_watchdog.start()   # daemon thread — เฝ้า 24/7 (ปิดเป็นค่าเริ่มต้น; เปิดด้วย WATCHDOG_ENABLED)
        print("[watchdog] เปิดการเฝ้าระบบ 24/7 (RAM/Ollama/cluster) — แจ้งเตือนเมื่อผิดปกติ")

    class LocalAssistantHandler(BaseHTTPRequestHandler):
        # ปิด log เริ่มต้นของ http.server ที่รก stdout — ใช้ log สั้นแทน
        def log_message(self, fmt, *args):
            print(f"[server] {self.address_string()} - {fmt % args}")

        def _identity(self) -> Optional[dict]:
            """ระบุว่า request นี้คือใคร มีสิทธิ์อะไร คืน dict หรือ None (ไม่ผ่าน auth)

            ลำดับการตรวจ:
              1. master token ผ่าน header X-Auth-Token (= สิทธิ์ CEO สำหรับ bootstrap/ดูแลระบบ)
              2. API key ผ่าน header X-API-Key (resolve เป็น user/role/tier จาก org_store)
              3. ถ้าไม่ได้ตั้ง master token เลย = โหมด local ล้วน (ตาม Rule 12) → ถือเป็น CEO
                 (ปลอดภัยเพราะ bind 127.0.0.1 เท่านั้นถึงจะไม่ตั้ง token ได้)
            """
            if auth_token and self.headers.get("X-Auth-Token") == auth_token:
                return {"username": "__master__", "role": "CEO", "tier": "paid", "key_id": None}
            raw_key = self.headers.get("X-API-Key")
            if raw_key:
                rec = org_store.verify_api_key(project_root, raw_key)
                if rec:
                    return rec
            if not auth_token and not raw_key:
                # โหมด local ล้วน (ไม่ได้ตั้ง token, ไม่ได้ส่ง API key) — เหมือนพฤติกรรมเดิม
                return {"username": "__local__", "role": "CEO", "tier": "paid", "key_id": None}
            return None

        def _send_json(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def _rate_limited(self, parsed) -> bool:
            """จำกัดเฉพาะ /api/ ต่อ IP — ถ้าเกินโควตาตอบ 429 แล้วคืน True (ผู้เรียกต้อง return)"""
            if not parsed.path.startswith("/api/"):
                return False
            client = self.client_address[0] if self.client_address else "unknown"
            if not api_rate_limiter.allow(client):
                self._send_json(429, {"error": "เรียก API ถี่เกินไป — รอสักครู่แล้วลองใหม่ (rate limit)"})
                return True
            return False

        # เส้นทาง "เปิดเสมอ" ที่ schedule gate ไม่ปิด — ให้ลูกค้าเช็คสถานะ/health ได้ตลอด
        _SCHEDULE_ALLOWLIST = (
            "/api/health", "/api/status", "/", "/console", "/web", "/install",
            "/app.css", "/favicon.ico",
        )

        def _schedule_gated(self, parsed) -> bool:
            """ถ้า schedule gate ปิดอยู่ (เลยเวลาทำการ) ตอบ 503 แล้วคืน True.
            ยกเว้น: path ใน allowlist, CEO/ADMIN (ให้ดูแลระบบตอนปิดได้).
            schedule gate ปิดเป็นค่าเริ่มต้น (SCHEDULE_ENABLED=False) → ฟังก์ชันนี้ no-op"""
            if parsed.path in self._SCHEDULE_ALLOWLIST:
                return False
            if not schedule_gate.enabled(project_root):
                return False
            info = schedule_gate.status(project_root)
            if info.get("state") == "open":
                return False
            # closed — ปล่อย CEO/ADMIN ผ่าน เพื่อดูแลระบบตอนปิด
            ident = self._identity()
            if ident and ident.get("role") in ("CEO", "ADMIN"):
                return False
            body = json.dumps(info, ensure_ascii=False).encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            retry_after = max(1, int(info.get("seconds_until_change") or 60))
            self.send_header("Retry-After", str(retry_after))
            self.end_headers()
            self.wfile.write(body)
            return True

        def _handle_status(self):
            """สถานะเซิร์ฟเวอร์ตาม schedule (public, ไม่ auth) — ลูกค้าดูได้ตลอด
            คืน state (open/closed), เวลาเปลี่ยนสถานะถัดไป, และข้อความอ่านง่าย"""
            self._send_json(200, schedule_gate.status(project_root))

        # ---------- View: serve index.html ----------
        def do_GET(self):
            parsed = urlparse(self.path)
            if self._rate_limited(parsed):
                return
            if self._schedule_gated(parsed):
                return
            if parsed.path in STATIC_ROUTES:
                self._serve_static(parsed.path)
            elif parsed.path == "/api/todos":
                self._handle_todos_get()
            elif parsed.path == "/api/health":
                self._handle_health()
            elif parsed.path == "/api/status":
                self._handle_status()
            elif parsed.path == "/api/sysinfo":
                self._handle_sysinfo()
            elif parsed.path == "/api/metrics":
                self._handle_metrics(parsed)
            elif parsed.path == "/api/me":
                self._handle_me()
            elif parsed.path == "/api/admin/users":
                self._handle_users_list()
            elif parsed.path == "/api/admin/apikeys":
                self._handle_apikeys_list()
            elif parsed.path == "/api/admin/jobs":
                self._handle_jobs_list(parsed)
            elif parsed.path == "/api/admin/history/snapshots":
                self._handle_history_snapshots(parsed)
            elif parsed.path == "/api/admin/history/errors":
                self._handle_history_errors(parsed)
            elif parsed.path == "/api/admin/finance":
                self._handle_finance_list(parsed)
            elif parsed.path == "/api/admin/finance/summary":
                self._handle_finance_summary()
            elif parsed.path == "/api/admin/usage":
                self._handle_usage_list(parsed)
            elif parsed.path == "/api/admin/usage/summary":
                self._handle_usage_summary()
            elif parsed.path == "/api/admin/support/tickets":
                self._handle_support_list(parsed)
            elif parsed.path == "/api/admin/dataset":
                self._handle_dataset_list(parsed)
            elif parsed.path == "/api/admin/dataset/export":
                self._handle_dataset_export(parsed)
            elif parsed.path == "/api/admin/cluster/nodes":
                self._handle_cluster_nodes_list()
            elif parsed.path == "/api/admin/cluster/health":
                self._handle_cluster_health()
            elif parsed.path == "/api/admin/cluster/route":
                self._handle_cluster_route(parsed)
            elif parsed.path == "/api/admin/watchdog":
                self._handle_watchdog()
            elif parsed.path == "/api/admin/features":
                self._handle_features_get()
            elif parsed.path == "/api/agent/jobs":
                self._handle_agent_jobs_get(parsed)
            elif parsed.path == "/api/agent/approvals":
                self._handle_agent_approvals_get()
            elif parsed.path == "/api/admin/cluster/settings":
                self._handle_cluster_settings_get()
            elif parsed.path == "/api/admin/model-backend/settings":
                self._handle_model_backend_settings_get()
            elif parsed.path == "/api/admin/hw-profile":
                self._handle_hw_profile(parsed)
            elif parsed.path == "/api/admin/config/versions":
                self._handle_config_versions_list()
            elif parsed.path == "/api/spaces":
                self._handle_spaces_list()
            elif parsed.path == "/api/spaces/items":
                self._handle_space_items_list(parsed)
            elif parsed.path == "/api/connections":
                self._handle_connections_list()
            elif parsed.path == "/api/skills":
                self._handle_skills_list()
            elif parsed.path == "/api/bots":
                self._handle_bots_list()
            elif parsed.path == "/api/connections/usage":
                self._handle_connections_usage()
            else:
                self._send_json(404, {"error": "not found"})

        # ---------- RBAC helper ----------
        def _require(self, min_role: str) -> Optional[dict]:
            """คืน identity ถ้าผ่าน auth + สิทธิ์ถึง min_role, ไม่งั้นตอบ error แล้วคืน None
            ผู้เรียกต้องเช็ค `if ident is None: return` ทันที"""
            ident = self._identity()
            if ident is None:
                self._send_json(401, {"error": "unauthorized — ต้องมี X-Auth-Token หรือ X-API-Key ที่ถูกต้อง"})
                return None
            if not org_store.role_at_least(ident["role"], min_role):
                self._send_json(403, {"error": f"forbidden — ต้องมีสิทธิ์ {min_role} ขึ้นไป (คุณคือ {ident['role']})"})
                return None
            return ident

        def _handle_me(self):
            ident = self._identity()
            if ident is None:
                self._send_json(401, {"error": "unauthorized"})
                return
            self._send_json(200, {
                "username": ident.get("username"),
                "role": ident.get("role"),
                "tier": ident.get("tier"),
            })

        def _handle_users_list(self):
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"users": org_store.list_users(project_root)})

        def _handle_apikeys_list(self):
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"api_keys": org_store.list_api_keys(project_root)})

        def _handle_jobs_list(self, parsed):
            if self._require("ADMIN") is None:
                return
            qs = parse_qs(parsed.query)
            status = qs.get("status", [None])[0]
            try:
                jobs = job_queue.list_jobs(project_root, status=status)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"jobs": jobs})

        def _handle_history_snapshots(self, parsed):
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"snapshots": history_store.list_snapshots(project_root)})

        def _handle_history_errors(self, parsed):
            if self._require("ADMIN") is None:
                return
            qs = parse_qs(parsed.query)
            level = qs.get("level", [None])[0]
            try:
                errors = history_store.list_errors(project_root, level=level)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"errors": errors})

        def _handle_finance_list(self, parsed):
            if self._require("ADMIN") is None:
                return
            qs = parse_qs(parsed.query)
            status = qs.get("status", [None])[0]
            direction = qs.get("direction", [None])[0]
            try:
                entries = finance_ledger.list_entries(project_root, status=status, direction=direction)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"entries": entries})

        def _handle_finance_summary(self):
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"summary": finance_ledger.summary(project_root)})

        def _handle_usage_list(self, parsed):
            if self._require("ADMIN") is None:
                return
            qs = parse_qs(parsed.query)
            key_id = qs.get("key_id", [None])[0]
            self._send_json(200, {"usage": usage_store.list_usage(project_root, key_id=key_id)})

        def _handle_usage_summary(self):
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"summary": usage_store.summary(project_root)})

        def _handle_support_list(self, parsed):
            if self._require("ADMIN") is None:
                return
            qs = parse_qs(parsed.query)
            status = qs.get("status", [None])[0]
            kind = qs.get("kind", [None])[0]
            try:
                tickets = support_store.list_tickets(project_root, status=status, kind=kind)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"tickets": tickets, "counts": support_store.counts_by_status(project_root)})

        def _handle_cluster_nodes_list(self):
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"nodes": cluster_store.list_nodes(project_root)})

        def _handle_cluster_health(self):
            # มอนิเตอร์คลัสเตอร์: ดึง /api/health จากทุก node มารวม (degrade ถ้า node ล่ม)
            if self._require("ADMIN") is None:
                return
            self._send_json(200, cluster_store.cluster_health(project_root))

        def _handle_watchdog(self):
            # สถานะ watchdog: เปิดอยู่ไหม + ผลตรวจสด (manual check, ไม่ส่งเตือน) — ADMIN+
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {
                "enabled": watchdog.is_enabled(project_root),
                "findings": _watchdog_check(),
            })

        def _handle_features_get(self):
            # มอนิเตอร์ฟีเจอร์: เปิด/ปิดอะไรอยู่บ้าง — ADMIN+
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"features": feature_flags.status(project_root)})

        def _handle_features_set(self):
            # เปิด/ปิดฟีเจอร์ — CEO เท่านั้น (เปลี่ยนพฤติกรรม server ทั้งระบบ)
            ident = self._require("CEO")
            if ident is None:
                return
            data = self._read_json_body()
            key = data.get("key", "")
            enabled = bool(data.get("enabled", False))
            # set_flag โยน ValueError ถ้า key ไม่รู้จัก -> 400 ใน do_POST
            res = feature_flags.set_flag(project_root, key, enabled)
            self._send_json(200, {"updated": res})

        def _handle_agent_jobs_post(self):
            # n8n/automation ป้อนงานเข้าคิว agent — USER+ และฟีเจอร์ agent ต้องเปิด
            ident = self._require("USER")
            if ident is None:
                return
            if not feature_flags.is_on(project_root, "agent"):
                self._send_json(403, {"error": "ฟีเจอร์ agent ปิดอยู่ — เปิดที่ /dev (Server features) ก่อน"})
                return
            data = self._read_json_body()
            task = data.get("task", "")
            workspace = data.get("workspace", ".")
            # enqueue โยน ValueError ถ้า task ว่าง -> 400 ใน do_POST
            job = agent_jobs.enqueue(project_root, task, workspace, source=data.get("source", "api"))
            self._send_json(200, {"job": job})

        def _handle_agent_jobs_get(self, parsed):
            # เช็กสถานะงาน (n8n poll) — ?id=<job> ดูงานเดียว, ไม่ใส่ = สรุป+ล่าสุด. USER+
            ident = self._require("USER")
            if ident is None:
                return
            qs = parse_qs(parsed.query)
            job_id = (qs.get("id") or [""])[0].strip()
            if job_id:
                job = agent_jobs.get(project_root, job_id)
                if job is None:
                    self._send_json(404, {"error": "ไม่พบงานนี้"})
                    return
                self._send_json(200, {"job": job})
                return
            self._send_json(200, {"stats": agent_jobs.stats(project_root),
                                  "recent": agent_jobs.list_jobs(project_root, limit=20)})

        def _handle_agent_approvals_get(self):
            # P6: ดูคำขออนุมัติที่ agent เสนอ (เขียนไฟล์/รันคำสั่งที่ย้อนไม่ได้) — ADMIN+
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"pending": agent_approvals.list_pending(project_root),
                                  "recent": agent_approvals.list_all(project_root, limit=20),
                                  "stats": agent_approvals.stats(project_root)})

        def _handle_agent_approvals_decide(self):
            # P6: คนตัดสิน (approve→ลงมือจริง / reject→ทิ้ง) — CEO เท่านั้น (ทำสิ่งย้อนไม่ได้)
            ident = self._require("CEO")
            if ident is None:
                return
            data = self._read_json_body()
            approval_id = data.get("id", "")
            decision = data.get("decision", "")
            # decide โยน ValueError ถ้า decision ผิด -> 400 ใน do_POST
            res = agent_approvals.decide(project_root, approval_id, decision,
                                         by=ident.get("username") or "ceo")
            if res.get("error"):
                self._send_json(404, res)
                return
            self._send_json(200, {"decided": res})

        # ---------- Console: Connections (ต่อสมอง AI ภายนอก) ----------
        def _handle_connections_list(self):
            # ดูทุก connection (redacted — ไม่เผย api_key เต็ม) — ADMIN+
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"connections": connections.list_connections(project_root)})

        def _handle_connections_usage(self):
            # Observability: นับ requests/tokens/cost ต่อ connection (ประมาณการ) — ADMIN+
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"usage": conn_usage.summary(project_root)})

        def _handle_connections_create(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            rec = connections.add(
                project_root, data.get("name", ""), data.get("kind", ""),
                base_url=data.get("base_url", ""), model=data.get("model", ""),
                api_key=data.get("api_key", ""), enabled=bool(data.get("enabled", True)))
            self._send_json(200, {"connection": rec})

        def _handle_connections_update(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            rec = connections.update(project_root, data.get("id", ""), data)
            self._send_json(200, {"connection": rec})

        def _handle_connections_delete(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            ok = connections.remove(project_root, data.get("id", ""))
            self._send_json(200 if ok else 404,
                            {"removed": ok} if ok else {"error": "ไม่พบ connection นี้"})

        def _handle_connections_test(self):
            # กดทดสอบว่า "ต่อติดไหม" (ไม่ generate จริง ไม่กิน token) — ADMIN+
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            self._send_json(200, {"result": connections.test(project_root, data.get("id", ""))})

        def _handle_connections_chat(self):
            # Playground: ยิงข้อความไปสมองโดยตรง (ทดสอบ connection) — ADMIN+
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            messages = data.get("messages")
            if not isinstance(messages, list) or not messages:
                prompt = (data.get("prompt") or "").strip()
                if not prompt:
                    self._send_json(400, {"error": "ต้องมี messages[] หรือ prompt"})
                    return
                messages = [{"role": "user", "content": prompt}]
            output = connections.chat(project_root, data.get("id", ""), messages,
                                      model=data.get("model", ""))
            self._send_json(200, {"output": output})

        def _sse_open(self):
            """เปิดสตรีม SSE (ส่ง 200 + header) แล้วคืนฟังก์ชัน sse(obj) ไว้เขียน event ทีละก้อน"""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")   # กัน reverse-proxy buffer สตรีม
            self.end_headers()

            def sse(obj):
                self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            return sse

        def _sse_stream(self, gen):
            """iterate generator ของ chunk → sse({delta}); จบด้วย {done}; พังกลางคัน → {error}.
            validate ต้องทำ *ก่อน* เรียกตัวนี้ (หลังส่ง 200 แล้วเปลี่ยนเป็น 400 ไม่ได้)"""
            sse = self._sse_open()
            try:
                for chunk in gen:
                    sse({"delta": chunk})
            except (connections.ConnectionError, bots.BotError) as e:
                sse({"error": str(e)})          # สมองพังกลางสตรีม — 200 ออกไปแล้ว ส่ง error event
                return
            except (BrokenPipeError, ConnectionResetError):
                return                          # client ปิดแท็บกลางคัน — เงียบไว้
            sse({"done": True})

        def _handle_connections_chat_stream(self):
            # Playground stream: ยิงข้อความไปสมองแล้วเห็นคำตอบทยอยขึ้นทีละคำ — ADMIN+
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            messages = data.get("messages")
            if not isinstance(messages, list) or not messages:
                prompt = (data.get("prompt") or "").strip()
                if not prompt:
                    self._send_json(400, {"error": "ต้องมี messages[] หรือ prompt"})
                    return
                messages = [{"role": "user", "content": prompt}]
            # chat_stream validate (ไม่พบ/ปิด/ไม่มี model) แบบ eager → ConnectionError → 400 ใน do_POST
            gen = connections.chat_stream(project_root, data.get("id", ""), messages,
                                          model=data.get("model", ""))
            self._sse_stream(gen)

        def _handle_bots_run_stream(self):
            # stream คำตอบ bot โหมด chat — USER+ และฟีเจอร์ connections ต้องเปิด
            ident = self._require("USER")
            if ident is None:
                return
            if not feature_flags.is_on(project_root, "connections"):
                self._send_json(403, {"error": "ฟีเจอร์ Connections ปิดอยู่ — เปิดที่ /dev (Server features) ก่อน"})
                return
            data = self._read_json_body()
            # run_stream validate (ไม่พบ/ปิด/agent/ไม่มี connection) แบบ eager → BotError → 400 ใน do_POST
            gen = bots.run_stream(project_root, data.get("id", ""), data.get("input", ""),
                                  model=data.get("model", ""))
            self._sse_stream(gen)

        # ---------- Console: Skills ----------
        def _handle_skills_list(self):
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"skills": skills_store.list_skills(project_root)})

        def _handle_skills_create(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            rec = skills_store.add(
                project_root, data.get("name", ""), data.get("system_prompt", ""),
                connection_id=data.get("connection_id", ""), model=data.get("model", ""),
                description=data.get("description", ""), temperature=data.get("temperature"))
            self._send_json(200, {"skill": rec})

        def _handle_skills_update(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            rec = skills_store.update(project_root, data.get("id", ""), data)
            self._send_json(200, {"skill": rec})

        def _handle_skills_delete(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            ok = skills_store.remove(project_root, data.get("id", ""))
            self._send_json(200 if ok else 404,
                            {"removed": ok} if ok else {"error": "ไม่พบ skill นี้"})

        # ---------- Console: Bots ----------
        def _handle_bots_list(self):
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"bots": bots.list_bots(project_root)})

        def _handle_bots_create(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            rec = bots.add(project_root, data.get("name", ""), data.get("skill_id", ""),
                           description=data.get("description", ""),
                           enabled=bool(data.get("enabled", True)))
            self._send_json(200, {"bot": rec})

        def _handle_bots_update(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            rec = bots.update(project_root, data.get("id", ""), data)
            self._send_json(200, {"bot": rec})

        def _handle_bots_delete(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            ok = bots.remove(project_root, data.get("id", ""))
            self._send_json(200 if ok else 404,
                            {"removed": ok} if ok else {"error": "ไม่พบ bot นี้"})

        def _handle_bots_run(self):
            # รัน bot กับข้อความเข้า (ให้ n8n/automation เรียกได้) — USER+ และฟีเจอร์ connections ต้องเปิด
            ident = self._require("USER")
            if ident is None:
                return
            if not feature_flags.is_on(project_root, "connections"):
                self._send_json(403, {"error": "ฟีเจอร์ Connections ปิดอยู่ — เปิดที่ /dev (Server features) ก่อน"})
                return
            data = self._read_json_body()
            res = bots.run(project_root, data.get("id", ""), data.get("input", ""),
                           model=data.get("model", ""), workspace=data.get("workspace", "."))
            self._send_json(200, {"result": res})

        def _handle_cluster_route(self, parsed):
            # preview: งานใหม่จะถูก route ไป node ไหน (ตาม health ปัจจุบัน) — ADMIN+
            # ?strategy=prefer_free|round_robin (default prefer_free)
            if self._require("ADMIN") is None:
                return
            strategy = (parse_qs(parsed.query).get("strategy", ["prefer_free"])[0]).strip()
            health = cluster_store.cluster_health(project_root)
            preview = cluster_router.route_preview(health, strategy=strategy, rr_index=_rr_state[0])
            _rr_state[0] = preview["rr_index"]   # เลื่อน round-robin จริง
            self._send_json(200, {"route": preview, "summary": health.get("summary"),
                                  "forward_enabled": cluster_forward.is_enabled(project_root)})

        def _handle_cluster_node_add(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            node = cluster_store.add_node(project_root, data.get("name"), data.get("url"))
            self._send_json(200, {"node": node})

        def _handle_cluster_node_remove(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            ok = cluster_store.remove_node(project_root, data.get("name"))
            self._send_json(200 if ok else 404,
                            {"removed": ok} if ok else {"error": "ไม่พบ node ชื่อนี้"})

        def _handle_cluster_settings_get(self):
            # ตัวตน node นี้ + hub ที่สังกัด (ไม่เผย HUB_TOKEN เต็ม)
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"settings": cluster_store.get_settings(project_root)})

        def _handle_cluster_settings_set(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            settings = cluster_store.set_settings(project_root, data)
            self._send_json(200, {"settings": settings})

        def _handle_cluster_join(self):
            # เครื่องนี้ register ตัวเองเข้า hub (ต้องตั้ง NODE_*/HUB_* ครบก่อน)
            if self._require("ADMIN") is None:
                return
            result = cluster_store.register_with_hub(project_root)
            self._send_json(200 if result.get("ok") else 400, result)

        def _handle_model_backend_settings_get(self):
            # ตั้งค่า model backend (เสียบ cloud GPU ผ่าน OpenAI-compatible) — ไม่เผย key เต็ม
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"settings": model_backend.get_backend_settings(project_root)})

        def _handle_hw_profile(self, parsed):
            # โปรไฟล์ฮาร์ดแวร์ + คำแนะนำ config (ADMIN+) — ค่าเริ่มต้นไม่วัด disk (ตอบไว);
            # ?disk=1 ให้วัด disk จริง (ช้าขึ้นแต่รู้ HDD/SSD)
            if self._require("ADMIN") is None:
                return
            want_disk = parse_qs(parsed.query).get("disk", ["0"])[0] in ("1", "true", "yes")
            try:
                p = hw_profile.profile(project_root=project_root, measure_disk=want_disk)
            except Exception as e:  # pragma: no cover - degrade แทนพังทั้งหน้า
                self._send_json(500, {"error": f"อ่านโปรไฟล์เครื่องไม่สำเร็จ: {e.__class__.__name__}"})
                return
            self._send_json(200, {"profile": p})

        # ---------- Spaces: พื้นที่ส่วนตัว/บริษัท (USER ขึ้นไป) ----------
        def _handle_spaces_list(self):
            ident = self._require("USER")
            if ident is None:
                return
            spaces = space_store.list_spaces(project_root, ident["username"], ident["role"])
            self._send_json(200, {"spaces": spaces})

        def _handle_space_create(self):
            ident = self._require("USER")
            if ident is None:
                return
            data = self._read_json_body()
            try:
                space = space_store.create_space(
                    project_root, data.get("name", ""), owner=ident["username"],
                    visibility=data.get("visibility", "private"))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"space": space})

        def _space_or_403(self, ident, space_id):
            """คืน space ถ้าเข้าถึงได้, ไม่งั้นตอบ error แล้วคืน None"""
            space = space_store.get_space(project_root, space_id)
            if space is None:
                self._send_json(404, {"error": "ไม่พบพื้นที่"})
                return None
            if not space_store.can_access(space, ident["username"], ident["role"]):
                self._send_json(403, {"error": "ไม่มีสิทธิ์เข้าพื้นที่นี้"})
                return None
            return space

        def _handle_space_items_list(self, parsed):
            ident = self._require("USER")
            if ident is None:
                return
            space_id = (parse_qs(parsed.query).get("space", [""])[0]).strip()
            if self._space_or_403(ident, space_id) is None:
                return
            self._send_json(200, {"items": space_store.list_items(project_root, space_id)})

        def _handle_space_item_add(self):
            ident = self._require("USER")
            if ident is None:
                return
            data = self._read_json_body()
            space_id = (data.get("space") or "").strip()
            if self._space_or_403(ident, space_id) is None:
                return
            try:
                item = space_store.add_item(project_root, space_id, ident["username"],
                                            data.get("text", ""))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"item": item})

        def _handle_space_member_add(self):
            ident = self._require("USER")
            if ident is None:
                return
            data = self._read_json_body()
            space_id = (data.get("space") or "").strip()
            space = space_store.get_space(project_root, space_id)
            if space is None:
                self._send_json(404, {"error": "ไม่พบพื้นที่"})
                return
            # เชิญสมาชิกได้เฉพาะเจ้าของ หรือ ADMIN ขึ้นไป
            if ident["username"] != space.get("owner") and not org_store.role_at_least(ident["role"], "ADMIN"):
                self._send_json(403, {"error": "เฉพาะเจ้าของพื้นที่หรือแอดมินเชิญสมาชิกได้"})
                return
            try:
                updated = space_store.add_member(project_root, space_id, (data.get("member") or "").strip())
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"space": updated})

        def _handle_config_versions_list(self):
            # รายการเวอร์ชัน config (metadata เท่านั้น — ไม่เผย secret) — ADMIN+
            if self._require("ADMIN") is None:
                return
            self._send_json(200, {"versions": config_versions.list_versions(project_root)})

        def _handle_config_snapshot(self):
            # เก็บ snapshot ของ config ปัจจุบัน (เช่น ก่อนปล่อยของ) — ADMIN+
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            meta = config_versions.snapshot(project_root, label=data.get("label", ""))
            self._send_json(200, {"snapshot": meta})

        def _handle_config_rollback(self):
            # ย้อน config กลับเวอร์ชันก่อน (powerful: เปลี่ยน backend/key ได้) — CEO เท่านั้น
            if self._require("CEO") is None:
                return
            data = self._read_json_body()
            version_id = (data.get("id") or "").strip()
            if not version_id:
                self._send_json(400, {"error": "ต้องระบุ id ของเวอร์ชัน"})
                return
            try:
                result = config_versions.rollback(project_root, version_id)
            except ValueError as e:
                self._send_json(404, {"error": str(e)})
                return
            self._send_json(200, {"rolledback": result})

        def _handle_model_backend_settings_set(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            settings = model_backend.set_backend_settings(project_root, data)
            self._send_json(200, {"settings": settings})

        def _handle_model_backend_test(self):
            # กดทดสอบว่า backend ที่ตั้งไว้ "ต่อติดไหม" (ไม่ generate จริง ไม่กิน token)
            if self._require("ADMIN") is None:
                return
            self._send_json(200, model_backend.probe_backend(project_root))

        def _serve_static(self, route: str):
            # เสิร์ฟหน้าเว็บ/asset ตาม STATIC_ROUTES ตัวเดียวจบ (html/css/js)
            # อ่านเป็น bytes ตรงๆ — ไฟล์ทุกตัวเป็น utf-8 อยู่แล้ว ไม่ต้อง decode/encode วน
            filename, content_type, cache = STATIC_ROUTES[route]
            try:
                body = (APP_DIR / filename).read_bytes()
            except OSError as e:
                self._send_json(500, {"error": f"อ่าน {filename} ไม่ได้: {e}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if cache:
                # asset ที่ไม่ค่อยเปลี่ยน (css/js) — ให้ browser cache ลดภาระเครื่องอ่อน
                self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)

        def _ollama_up(self, host="127.0.0.1", port=11434, timeout=0.3) -> bool:
            """เช็กเบาๆ ว่า Ollama เปิด port อยู่ไหม (TCP connect สั้นๆ ไม่ยิง request)"""
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True
            except OSError:
                return False

        def _handle_health(self):
            """สัญญาณชีพของระบบ (public, ไม่ auth) — ข้อมูลไม่ลับ:
            Ollama เปิดไหม, RAM ตึงไหม, โมเดล/ backend ที่แนะนำสำหรับเครื่องนี้"""
            rec = resource_budget.pick_model(project_root=project_root)
            local = bind_host in ("127.0.0.1", "localhost", "::1")
            self._send_json(200, {
                "ok": True,
                "ollama": "up" if self._ollama_up() else "down",
                "ram_pressure": resource_budget.ram_pressure(),
                "recommended_model": rec["model"],
                "recommend_reason": rec["reason"],
                "backend": resource_budget.pick_backend(project_root),
                # โหมดเครือข่าย (N4) — บอกว่าตอนนี้เปิดแค่เครื่องนี้ หรือออก LAN แล้ว
                "network": {
                    "bind": bind_host,
                    "mode": "local" if local else "lan",
                    "auth_required": (not local) or bool(auth_token),
                },
            })

        def _handle_sysinfo(self):
            # spec เครื่อง (static) สำหรับ dev view / ระบบจัดการทรัพยากร — ADMIN ขึ้นไป
            if self._require("ADMIN") is None:
                return
            self._send_json(200, get_system_info().to_dict())

        def _handle_metrics(self, parsed):
            # Phase 2: metrics สด (snapshot + วิเคราะห์คอขวด + บริบท LCA/Ollama) — ADMIN ขึ้นไป
            # ไม่เก็บลง db (ใช้ /api/admin/history/snapshot ถ้าต้องการเก็บ)
            if self._require("ADMIN") is None:
                return
            qs = parse_qs(parsed.query)
            try:
                interval = float(qs.get("interval", ["0.3"])[0])
            except (TypeError, ValueError):
                interval = 0.3
            report = _Analyzer().analyze(_collect(interval=interval))
            findings = [
                {
                    "resource": f.resource,
                    "severity": f.severity.label,
                    "value": round(f.value, 2),
                    "message": f.message,
                    "suggestion": f.suggestion,
                }
                for f in report.findings
            ]
            self._send_json(200, {
                "snapshot": report.snapshot.to_dict(),
                "verdict": report.verdict,
                "worst_severity": report.worst.label,
                "findings": findings,
                "lca": _lca_context.correlate(report),
            })

        # ---------- Controller: API routes ----------
        def do_POST(self):
            parsed = urlparse(self.path)
            if self._rate_limited(parsed):
                return
            if self._schedule_gated(parsed):
                return
            try:
                if parsed.path == "/api/chat":
                    self._handle_chat()
                elif parsed.path == "/api/chat/stream":
                    self._handle_chat_stream()
                elif parsed.path == "/api/todos":
                    self._handle_todos_post()
                elif parsed.path == "/api/todos/toggle":
                    self._handle_todos_toggle()
                elif parsed.path == "/api/todos/delete":
                    self._handle_todos_delete()
                elif parsed.path == "/api/admin/users":
                    self._handle_users_create()
                elif parsed.path == "/api/admin/users/active":
                    self._handle_users_set_active()
                elif parsed.path == "/api/admin/apikeys":
                    self._handle_apikeys_create()
                elif parsed.path == "/api/admin/apikeys/revoke":
                    self._handle_apikeys_revoke()
                elif parsed.path == "/api/admin/jobs":
                    self._handle_jobs_create()
                elif parsed.path == "/api/admin/jobs/status":
                    self._handle_jobs_set_status()
                elif parsed.path == "/api/admin/jobs/delete":
                    self._handle_jobs_delete()
                elif parsed.path == "/api/admin/history/snapshot":
                    self._handle_history_record_snapshot()
                elif parsed.path == "/api/admin/history/errors":
                    self._handle_history_log_error()
                elif parsed.path == "/api/admin/finance":
                    self._handle_finance_record()
                elif parsed.path == "/api/admin/finance/status":
                    self._handle_finance_set_status()
                elif parsed.path == "/api/admin/finance/delete":
                    self._handle_finance_delete()
                elif parsed.path == "/api/admin/notify":
                    self._handle_notify()
                elif parsed.path == "/api/support/ticket":
                    self._handle_support_create()
                elif parsed.path == "/api/admin/support/tickets/status":
                    self._handle_support_set_status()
                elif parsed.path == "/api/admin/dataset":
                    self._handle_dataset_add()
                elif parsed.path == "/api/admin/dataset/delete":
                    self._handle_dataset_delete()
                elif parsed.path == "/api/admin/cluster/nodes":
                    self._handle_cluster_node_add()
                elif parsed.path == "/api/admin/cluster/nodes/remove":
                    self._handle_cluster_node_remove()
                elif parsed.path == "/api/admin/cluster/settings":
                    self._handle_cluster_settings_set()
                elif parsed.path == "/api/admin/cluster/join":
                    self._handle_cluster_join()
                elif parsed.path == "/api/admin/model-backend/settings":
                    self._handle_model_backend_settings_set()
                elif parsed.path == "/api/admin/model-backend/test":
                    self._handle_model_backend_test()
                elif parsed.path == "/api/admin/config/snapshot":
                    self._handle_config_snapshot()
                elif parsed.path == "/api/admin/config/rollback":
                    self._handle_config_rollback()
                elif parsed.path == "/api/spaces":
                    self._handle_space_create()
                elif parsed.path == "/api/spaces/items":
                    self._handle_space_item_add()
                elif parsed.path == "/api/spaces/members":
                    self._handle_space_member_add()
                elif parsed.path == "/api/admin/features":
                    self._handle_features_set()
                elif parsed.path == "/api/agent/jobs":
                    self._handle_agent_jobs_post()
                elif parsed.path == "/api/agent/approvals/decide":
                    self._handle_agent_approvals_decide()
                elif parsed.path == "/api/connections":
                    self._handle_connections_create()
                elif parsed.path == "/api/connections/update":
                    self._handle_connections_update()
                elif parsed.path == "/api/connections/delete":
                    self._handle_connections_delete()
                elif parsed.path == "/api/connections/test":
                    self._handle_connections_test()
                elif parsed.path == "/api/connections/chat":
                    self._handle_connections_chat()
                elif parsed.path == "/api/connections/chat/stream":
                    self._handle_connections_chat_stream()
                elif parsed.path == "/api/skills":
                    self._handle_skills_create()
                elif parsed.path == "/api/skills/update":
                    self._handle_skills_update()
                elif parsed.path == "/api/skills/delete":
                    self._handle_skills_delete()
                elif parsed.path == "/api/bots":
                    self._handle_bots_create()
                elif parsed.path == "/api/bots/update":
                    self._handle_bots_update()
                elif parsed.path == "/api/bots/delete":
                    self._handle_bots_delete()
                elif parsed.path == "/api/bots/run":
                    self._handle_bots_run()
                elif parsed.path == "/api/bots/run/stream":
                    self._handle_bots_run_stream()
                else:
                    self._send_json(404, {"error": "not found"})
            except (connections.ConnectionError, skills_store.SkillError, bots.BotError) as e:
                # input ผิด/ไม่พบ/ต่อสมองไม่ได้ — ตอบ 400 (ข้อความอ่านรู้เรื่อง)
                self._send_json(400, {"error": str(e)})
            except (json.JSONDecodeError, KeyError) as e:
                self._send_json(400, {"error": f"request ผิดรูปแบบ: {e}"})
            except ValueError as e:
                # org_store โยน ValueError เมื่อ input ผิด/สิทธิ์ไม่พอ/ชื่อซ้ำ
                self._send_json(400, {"error": str(e)})

        # ---------- Controller: Org / Admin routes ----------
        def _handle_users_create(self):
            data = self._read_json_body()
            username = data.get("username", "")
            password = data.get("password", "")
            role = data.get("role", "USER")
            # bootstrap: ยังไม่มี user เลย → สร้าง CEO คนแรกได้
            # แต่ถ้าตั้ง master token ไว้ (เช่น เปิดออกนอก 127.0.0.1) ต้องยืนยันด้วย token
            # ก่อน กัน attacker ใน network ชิงสร้าง CEO คนแรกก่อนเจ้าของเครื่อง
            if org_store.bootstrap_needed(project_root):
                if auth_token and self.headers.get("X-Auth-Token") != auth_token:
                    self._send_json(401, {"error": "bootstrap: ต้องใส่ X-Auth-Token ให้ตรง master token "
                                                   "ก่อนสร้าง CEO คนแรก (กันการชิงสิทธิ์บน network)"})
                    return
                rec = org_store.create_user(project_root, username, password, role)
                self._send_json(200, {"created": rec, "bootstrap": True})
                return
            ident = self._require("ADMIN")
            if ident is None:
                return
            rec = org_store.create_user(project_root, username, password, role,
                                        created_by_role=ident["role"])
            self._send_json(200, {"created": rec})

        def _handle_users_set_active(self):
            ident = self._require("ADMIN")
            if ident is None:
                return
            data = self._read_json_body()
            username = data.get("username")
            active = bool(data.get("active", True))
            if not username:
                self._send_json(400, {"error": "ต้องระบุ username"})
                return
            ok = org_store.set_user_active(project_root, username, active, actor_role=ident["role"])
            self._send_json(200 if ok else 404, {"success": ok})

        def _handle_apikeys_create(self):
            ident = self._require("ADMIN")
            if ident is None:
                return
            data = self._read_json_body()
            owner = data.get("owner")
            tier = data.get("tier", "free")
            if not owner:
                self._send_json(400, {"error": "ต้องระบุ owner (username เจ้าของ key)"})
                return
            issued = org_store.create_api_key(project_root, owner, tier, actor_role=ident["role"])
            # issued มี 'key' เต็ม — โชว์ครั้งเดียว ผู้ใช้ต้องเก็บเอง
            self._send_json(200, {"api_key": issued,
                                  "note": "เก็บค่า key นี้ไว้เดี๋ยวนี้ — ระบบจะไม่โชว์อีก"})

        def _handle_apikeys_revoke(self):
            ident = self._require("ADMIN")
            if ident is None:
                return
            data = self._read_json_body()
            key_id = data.get("key_id")
            if not key_id:
                self._send_json(400, {"error": "ต้องระบุ key_id"})
                return
            ok = org_store.revoke_api_key(project_root, key_id, actor_role=ident["role"])
            self._send_json(200 if ok else 404, {"success": ok})

        # ---------- Controller: Dataset routes (ADMIN) — เก็บไว้ fine-tune ทีหลัง ----------
        def _handle_dataset_list(self, parsed):
            if self._require("ADMIN") is None:
                return
            qs = parse_qs(parsed.query)
            min_rating = qs.get("min_rating", [None])[0]
            samples = dataset_store.list_samples(
                project_root, min_rating=(int(min_rating) if min_rating else None))
            self._send_json(200, {"samples": samples, "count": dataset_store.count(project_root)})

        def _handle_dataset_add(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            sample = dataset_store.add_sample(  # ValueError -> 400 ใน do_POST
                project_root,
                prompt=data.get("prompt", ""),
                response=data.get("response", ""),
                model=data.get("model"),
                rating=data.get("rating"),
                source=data.get("source", "manual"),
            )
            self._send_json(200, {"sample": sample})

        def _handle_dataset_delete(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            sample_id = data.get("id")
            if sample_id is None:
                self._send_json(400, {"error": "ต้องระบุ id"})
                return
            ok = dataset_store.delete_sample(project_root, int(sample_id))
            self._send_json(200 if ok else 404, {"success": ok})

        def _handle_dataset_export(self, parsed):
            # export JSONL พร้อม fine-tune — ส่งเป็น text/plain ให้โหลดไปใช้ต่อ
            if self._require("ADMIN") is None:
                return
            qs = parse_qs(parsed.query)
            fmt = qs.get("fmt", ["messages"])[0]
            min_rating = qs.get("min_rating", [None])[0]
            try:
                jsonl = dataset_store.export_jsonl(
                    project_root, fmt=fmt,
                    min_rating=(int(min_rating) if min_rating else None))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            body = (jsonl + ("\n" if jsonl else "")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="lca_dataset.jsonl"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # ---------- Controller: Job queue routes (ADMIN) ----------
        def _handle_jobs_create(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            name = data.get("name", "")
            payload = data.get("payload")
            job = job_queue.enqueue(project_root, name, payload)  # ValueError -> 400 ใน do_POST
            self._send_json(200, {"job": job})

        def _handle_jobs_set_status(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            job_id = data.get("id")
            status = data.get("status", "")
            if job_id is None:
                self._send_json(400, {"error": "ต้องระบุ id"})
                return
            ok = job_queue.set_status(project_root, int(job_id), status)  # ValueError -> 400
            self._send_json(200 if ok else 404, {"success": ok})

        def _handle_jobs_delete(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            job_id = data.get("id")
            if job_id is None:
                self._send_json(400, {"error": "ต้องระบุ id"})
                return
            ok = job_queue.delete_job(project_root, int(job_id))
            self._send_json(200 if ok else 404, {"success": ok})

        # ---------- Controller: History / log routes (ADMIN) ----------
        def _handle_history_record_snapshot(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            interval = float(data.get("interval", 0.3)) if data else 0.3  # ValueError -> 400
            report = _Analyzer().analyze(_collect(interval=interval))
            rep = {
                "snapshot": report.snapshot.to_dict(),
                "verdict": report.verdict,
                "worst_severity": report.worst.label,
            }
            stored = history_store.record_snapshot(project_root, rep)
            self._send_json(200, {"snapshot": stored})

        def _handle_history_log_error(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            entry = history_store.log_error(
                project_root,
                data.get("level", ""),
                data.get("source", ""),
                data.get("message", ""),
            )  # ValueError -> 400 ใน do_POST
            self._send_json(200, {"error_entry": entry})

        # ---------- Controller: Finance ledger routes (ADMIN, record-only) ----------
        def _handle_finance_record(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            entry = finance_ledger.record_entry(
                project_root,
                data.get("amount"),
                data.get("direction", ""),
                note=data.get("note", ""),
                category=data.get("category", ""),
                status=data.get("status", "pending"),
            )  # ValueError -> 400 ใน do_POST
            self._send_json(200, {"entry": entry})

        def _handle_finance_set_status(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            entry_id = data.get("id")
            status = data.get("status", "")
            if entry_id is None:
                self._send_json(400, {"error": "ต้องระบุ id"})
                return
            entry = finance_ledger.set_status(project_root, int(entry_id), status)  # ValueError -> 400
            if entry is None:
                self._send_json(404, {"success": False})
                return
            self._send_json(200, {"entry": entry})

        def _handle_finance_delete(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            entry_id = data.get("id")
            if entry_id is None:
                self._send_json(400, {"error": "ต้องระบุ id"})
                return
            ok = finance_ledger.delete_entry(project_root, int(entry_id))
            self._send_json(200 if ok else 404, {"success": ok})

        # ---------- Controller: Support tickets ----------
        def _handle_support_create(self):
            # ลูกค้าที่ล็อกอิน (USER ขึ้นไป) แจ้งปัญหา/ขอฟีเจอร์ได้ — reporter = ตัวตนจริง
            ident = self._require("USER")
            if ident is None:
                return
            data = self._read_json_body()
            ticket = support_store.create_ticket(  # ValueError -> 400 ใน do_POST
                project_root,
                reporter=ident.get("username"),
                subject=data.get("subject", ""),
                body=data.get("body", ""),
                kind=data.get("kind", "bug"),
                channel=data.get("channel", "web"),
            )
            # ยิงแจ้งเตือนให้ทีมรู้ทันที (Discord/email) — ไม่มี config = skip เงียบ ไม่ทำ response พัง
            notified = {}
            try:
                notified = notifier.notify(
                    project_root,
                    event=f"support:{ticket['kind']}",
                    text=f"#{ticket['id']} [{ticket['channel']}] {ticket['subject']} "
                         f"(โดย {ticket.get('reporter') or 'ไม่ระบุ'})",
                )
            except (ValueError, OSError) as e:
                print(f"[support][warn] แจ้งเตือน ticket ไม่สำเร็จ: {e}")
            self._send_json(200, {"ticket": ticket, "notified": notified})

        def _handle_support_set_status(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            ticket_id = data.get("id")
            status = data.get("status", "")
            if ticket_id is None:
                self._send_json(400, {"error": "ต้องระบุ id"})
                return
            ticket = support_store.set_status(project_root, int(ticket_id), status)  # ValueError -> 400
            if ticket is None:
                self._send_json(404, {"success": False})
                return
            self._send_json(200, {"ticket": ticket})

        # ---------- Controller: Notify route (ADMIN) ----------
        def _handle_notify(self):
            if self._require("ADMIN") is None:
                return
            data = self._read_json_body()
            event = data.get("event", "")
            text = data.get("text", "")
            channels = data.get("channels") or list(notifier.VALID_CHANNELS)
            # notifier.notify โยน ValueError ถ้า text ว่าง -> 400 ใน do_POST
            result = notifier.notify(project_root, event, text, channels=channels)
            self._send_json(200, {"result": result})

        def _chat_prepare(self, ident):
            """auth/quota peek + อ่าน body + เลือก model + เติม system prompt
            คืน (model, messages, num_ctx) ถ้าพร้อม, หรือ None (ตอบ error ให้แล้ว)
            ใช้ร่วมกันทั้ง /api/chat (blocking) และ /api/chat/stream — logic เดียว ไม่ซ้ำ"""
            # peek โควตาก่อนลงมือ (ปฏิเสธเร็ว) — หักจริงหลังตอบสำเร็จเท่านั้น เพื่อไม่ให้
            # request ที่ body พังหรือ Ollama ล่มไปกินโควตาของผู้ใช้ฟรีทิ้งเปล่าๆ
            if ident.get("key_id") and not org_store.has_quota(project_root, ident["key_id"]):
                self._send_json(429, {"error": "เกินโควตาการใช้งานรายวันของ API key นี้แล้ว "
                                               "(อัปเกรดเป็น tier paid เพื่อใช้ได้ไม่จำกัด)"})
                return None
            data = self._read_json_body()
            # Auto-scale compute: ถ้า client ไม่ระบุ model (หรือขอ "auto") ให้เลือก
            # โมเดลใหญ่สุดที่ RAM ว่างตอนนี้รับไหว (resource_budget) — เครื่องอ่อนได้ 0.5b,
            # เครื่องแรงได้ตัวใหญ่ขึ้นอัตโนมัติ; ถ้าระบุ model มาเองก็เคารพตามนั้น
            requested = (data.get("model") or "").strip()
            if not requested or requested.lower() == "auto":
                model = resource_budget.pick_model(project_root=project_root)["model"]
            else:
                model = requested
            messages = data.get("messages", [])
            num_ctx = data.get("num_ctx", 8192)
            lang = data.get("lang", "th")
            if not messages:
                self._send_json(400, {"error": "ต้องมี messages"})
                return None
            # ถ้า client ไม่ได้แนบ system prompt มา (เช่น index.html ที่ส่งแค่ user/assistant)
            # ให้ server แทรกให้เองตาม lang ที่เลือก
            if not messages or messages[0].get("role") != "system":
                messages = [{"role": "system", "content": get_system_prompt(lang)}] + messages
            return model, messages, num_ctx

        def _chat_finalize(self, ident, model, messages, reply):
            """หักโควตา + บันทึก usage + เก็บ dataset — หลังได้คำตอบเต็มแล้ว (blocking/stream ใช้ร่วม)"""
            # หักโควตาหลังได้คำตอบจริงเท่านั้น (master/local ไม่มี key_id = ไม่หัก)
            # แล้วบันทึก usage ลง SQLite ด้วย (metering ย้อนหลัง/คิดเงินต่อ tier)
            if ident.get("key_id"):
                org_store.consume_quota(project_root, ident["key_id"])
                try:
                    usage_store.record_usage(
                        project_root, ident["key_id"], ident.get("owner"),
                        ident.get("tier"), endpoint="chat", units=1,
                    )
                except (ValueError, OSError, sqlite3.Error) as e:
                    # metering ล้ม (db locked/disk เต็ม ฯลฯ) ต้องไม่ทำ response ของผู้ใช้พัง
                    print(f"[usage][warn] บันทึก usage ไม่สำเร็จ: {e}")
            # เก็บคู่สนทนาไว้ทำ dataset fine-tune — "ปิดเป็นค่าเริ่มต้น" (ความเป็นส่วนตัว)
            # เปิดเมื่อ config COLLECT_TRAINING_DATA เป็น 1/true/yes เท่านั้น (ต้องขอ consent ผู้ใช้)
            if str(config_manager.get_key(project_root, "COLLECT_TRAINING_DATA") or "").lower() in ("1", "true", "yes"):
                last_user = next((m.get("content") for m in reversed(messages)
                                  if m.get("role") == "user"), None)
                if last_user:
                    try:
                        dataset_store.add_sample(project_root, last_user, reply,
                                                 model=model, source="chat")
                    except (ValueError, OSError, sqlite3.Error) as e:
                        print(f"[dataset][warn] เก็บตัวอย่างไม่สำเร็จ: {e}")

        def _forward_target(self, payload):
            """ถ้าเปิด cluster forward + มี node พร้อม → คืน node ปลายทาง (dict) ไม่งั้น None (ทำ local).
            เลื่อน round-robin จริงด้วย _rr_state (ใช้ตัวชี้เดียวกับ /api/admin/cluster/route)"""
            if not cluster_forward.is_enabled(project_root):
                return None
            token = cluster_forward._token(project_root)
            if not token:
                print("[forward][warn] เปิด CLUSTER_FORWARD_ENABLED แต่ไม่ได้ตั้ง CLUSTER_FORWARD_TOKEN — ทำ local")
                return None
            res = cluster_forward.pick_target(project_root, rr_index=_rr_state[0])
            _rr_state[0] = res["rr_index"]
            return res["node"]   # None = ไม่มี node พร้อม → local

        def _handle_chat(self):
            ident = self._require("USER")
            if ident is None:
                return
            prepared = self._chat_prepare(ident)
            if prepared is None:
                return
            model, messages, num_ctx = prepared
            payload = {"model": model, "messages": messages, "num_ctx": num_ctx}
            # HPC ขั้น 3+: ลองยื่นงานไป node อื่นที่พร้อม (ถ้าเปิด forward) — งาน generate
            # ไปกินแรงที่ node ปลายทาง ไม่ใช่เครื่องนี้ (จึงไม่ถือ gen_gate ของ local)
            node = self._forward_target(payload)
            if node is not None:
                try:
                    reply = cluster_forward.forward_chat(
                        node["url"], cluster_forward._token(project_root), payload,
                        timeout=cluster_forward._timeout(project_root))
                    self._chat_finalize(ident, model, messages, reply)
                    self._send_json(200, {"reply": reply, "served_by": node.get("name")})
                    return
                except cluster_forward.ForwardError as e:
                    # node ปลายทางมีปัญหา → ไม่ทิ้งงานผู้ใช้ ทำ local แทน (degrade graceful)
                    print(f"[forward][warn] ส่งไป {node.get('name')} ไม่สำเร็จ ({e}) — ทำ local แทน")
            # Model layer: เรียกผ่าน adapter (เลือก Ollama / OpenAI-compatible ตาม config)
            # แอปไม่ผูกกับ runtime ตัวใดตัวหนึ่ง — สลับ backend ได้โดยไม่แก้ตรงนี้
            try:
                # ยามคุม generation พร้อมกัน: เครื่องเต็ม/คิวยาว → 503 (กัน RAM thrash จนค้าง)
                with gen_gate.slot():
                    reply = model_backend.generate(project_root, model, messages, num_ctx)
            except admission.Busy as e:
                self._send_json(503, {"error": str(e)})
                return
            except model_backend.BackendError as e:
                self._send_json(502, {"error": str(e)})
                return
            self._chat_finalize(ident, model, messages, reply)
            self._send_json(200, {"reply": reply})

        def _handle_chat_stream(self):
            """เหมือน /api/chat แต่ stream คำตอบทีละ chunk แบบ SSE (text/event-stream) —
            ผู้ใช้เห็นคำตอบทยอยขึ้นทันที ไม่ต้องรอทั้งก้อน (สำคัญบนเครื่องช้า ~10 tok/s)
            รูปแบบ: `data: {"delta": "..."}` ต่อ chunk, จบด้วย `data: {"done": true}`,
            ถ้าพังกลางคัน `data: {"error": "..."}` (status เป็น 200 ไปแล้ว เปลี่ยนไม่ได้)"""
            ident = self._require("USER")
            if ident is None:
                return
            prepared = self._chat_prepare(ident)
            if prepared is None:
                return
            model, messages, num_ctx = prepared
            # HPC ขั้น 3+: ลอง relay สตรีมจาก node อื่นก่อน (ถ้าเปิด forward + มี node พร้อม)
            payload = {"model": model, "messages": messages, "num_ctx": num_ctx}
            node = self._forward_target(payload)
            if node is not None and self._stream_from_node(ident, model, messages, node, payload):
                return   # forward สำเร็จ (relay สตรีมจาก node ปลายทางแล้ว)
            # ยามคุม generation: ขอสล็อตก่อนส่ง 200 header — ถ้าเต็ม ยังตอบ 503 (JSON) ได้
            # (กัน RAM thrash: สตรีมหลายตัวพร้อมกันบนเครื่องบางก็ทำให้ค้างเหมือนกัน)
            try:
                with gen_gate.slot():
                    # เปิดสตรีม: HTTP/1.0 ไม่มี Content-Length → ปิด connection ที่ท้าย = client อ่านจบเอง
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("X-Accel-Buffering", "no")  # กัน reverse-proxy (nginx) buffer สตรีมไว้
                    self.end_headers()

                    def sse(obj):
                        self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
                        self.wfile.flush()

                    parts = []
                    try:
                        for chunk in model_backend.generate_stream(project_root, model, messages, num_ctx):
                            parts.append(chunk)
                            sse({"delta": chunk})
                    except model_backend.BackendError as e:
                        sse({"error": str(e)})
                        return
                    except (BrokenPipeError, ConnectionResetError):
                        # client ปิดแท็บกลางคัน — ไม่ใช่ error ของเรา เงียบไว้ (ไม่หักโควตา)
                        return
                    # finalize หลังสตรีมจบครบ (หักโควตา/usage/dataset เหมือน blocking)
                    self._chat_finalize(ident, model, messages, "".join(parts))
                    sse({"done": True})
            except admission.Busy as e:
                self._send_json(503, {"error": str(e)})

        def _stream_from_node(self, ident, model, messages, node, payload):
            """relay สตรีมจาก node ปลายทางมาหาผู้ใช้. คืน True = รับงานแล้ว (ส่ง 200 ไปแล้ว),
            False = ยังต่อ node ไม่ติดตั้งแต่ chunk แรก → ผู้เรียกทำ local แทนได้ (ยังไม่ส่ง header)"""
            token = cluster_forward._token(project_root)
            timeout = cluster_forward._timeout(project_root)
            gen = cluster_forward.forward_chat_stream(node["url"], token, payload, timeout=timeout)
            # prime chunk แรก: ถ้าต่อไม่ติด/node พังตั้งแต่ต้น → ForwardError ตรงนี้ ยัง fallback local ได้
            try:
                first = next(gen)
            except cluster_forward.ForwardError as e:
                print(f"[forward][warn] relay สตรีมจาก {node.get('name')} ไม่สำเร็จ ({e}) — ทำ local แทน")
                return False
            except StopIteration:
                first = None   # node ไม่ส่งอะไรเลย (คำตอบว่าง) — ถือว่ารับงานแล้ว ปิดด้วย done
            # commit: ส่ง 200 + header แล้ว (หลังจุดนี้ fallback ไม่ได้ — คำตอบเริ่มออกไปแล้ว)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            def sse(obj):
                self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()

            parts = []
            try:
                if first is not None:
                    parts.append(first)
                    sse({"delta": first})
                for chunk in gen:
                    parts.append(chunk)
                    sse({"delta": chunk})
            except cluster_forward.ForwardError as e:
                sse({"error": str(e)})   # node พังกลางสตรีม — header ส่งแล้ว เปลี่ยนเป็น local ไม่ได้
                return True
            except (BrokenPipeError, ConnectionResetError):
                return True   # ผู้ใช้ปิดแท็บ
            self._chat_finalize(ident, model, messages, "".join(parts))
            sse({"done": True, "served_by": node.get("name")})
            return True

        def _handle_todos_get(self):
            # เดิม GET /api/todos เปิดสาธารณะ — ปิดให้ต้อง USER ขึ้นไป (สอดคล้องกับ
            # POST/toggle/delete). โหมด local (ไม่ตั้ง token) ยังถือเป็น CEO จึงใช้ได้ตามเดิม
            if self._require("USER") is None:
                return
            todos = load_todos(project_root)
            self._send_json(200, todos)

        def _handle_todos_post(self):
            if self._require("USER") is None:
                return
            data = self._read_json_body()
            text = data.get("text", "").strip()
            if not text:
                self._send_json(400, {"error": "ต้องระบุ text"})
                return
            item = add_todo(project_root, text)
            self._send_json(200, item)

        def _handle_todos_toggle(self):
            if self._require("USER") is None:
                return
            data = self._read_json_body()
            todo_id = data.get("id")
            if todo_id is None:
                self._send_json(400, {"error": "ต้องระบุ id"})
                return
            ok = toggle_todo(project_root, int(todo_id))
            self._send_json(200 if ok else 404, {"success": ok})

        def _handle_todos_delete(self):
            if self._require("USER") is None:
                return
            data = self._read_json_body()
            todo_id = data.get("id")
            if todo_id is None:
                self._send_json(400, {"error": "ต้องระบุ id"})
                return
            ok = delete_todo(project_root, int(todo_id))
            self._send_json(200 if ok else 404, {"success": ok})

    return LocalAssistantHandler


def find_free_port(preferred: int, host: str = "127.0.0.1", tries: int = 20) -> int:
    """คืนพอร์ตที่ว่างจริง — ลอง preferred ก่อน ถ้าชนไล่ขึ้นทีละ 1 (preferred+1, +2, ...)
    กันปัญหา 'พอร์ต 8420 ถูกใช้อยู่แล้ว server เปิดไม่ขึ้น' — หาที่ว่างให้อัตโนมัติ
    หา tries พอร์ตไม่เจอ → สุดท้ายให้ OS เลือกพอร์ตว่างเอง (port 0)"""
    for p in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue   # พอร์ตนี้ถูกใช้อยู่ ลองตัวถัดไป
    # หาไม่เจอในช่วงที่ลอง → ให้ OS เลือกพอร์ตว่างใด ๆ
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def resolve_server_config(args, env=None):
    """รวม args + environment variable เป็น config สุดท้าย (host, port, token)
    — แยกออกมาให้เทสได้ และให้ deploy บน cloud ได้โดยไม่ต้องแก้ไฟล์

    ลำดับความสำคัญ: args (--flag) > env > default
      PORT        : cloud host (Render/Fly/HF/Cloud Run) ฉีด $PORT มาเอง ต้องอ่าน
      LCA_HOST    : cloud ต้อง bind 0.0.0.0 (รับ traffic จากข้างนอก container)
      LCA_TOKEN   : auth token — บังคับเมื่อ bind ออกนอก 127.0.0.1 (Rule 12)

    กฎความปลอดภัยเดิมคงอยู่: bind ออกนอก localhost โดยไม่มี token = ValueError
    (cloud จึง *ต้อง* ตั้ง LCA_TOKEN — กันคนทั้งอินเทอร์เน็ตสั่งแก้ไฟล์)
    คืน dict {host, port, token}
    """
    env = env if env is not None else os.environ
    # host: --host ถ้าผู้ใช้ตั้ง (ไม่ใช่ default), ไม่งั้น env LCA_HOST, ไม่งั้น default
    host = args.host
    if host == "127.0.0.1" and env.get("LCA_HOST"):
        host = env["LCA_HOST"].strip()
    # port: --port ถ้าตั้ง (ไม่ใช่ default), ไม่งั้น $PORT (cloud), ไม่งั้น default
    port = args.port
    if port == 8420 and env.get("PORT"):
        try:
            port = int(env["PORT"])
        except (TypeError, ValueError):
            raise ValueError(f"$PORT ไม่ใช่ตัวเลข: {env['PORT']!r}")
    token = args.token or env.get("LCA_TOKEN") or None
    if host != "127.0.0.1" and not token:
        raise ValueError(
            "ห้าม bind ออกนอก 127.0.0.1 โดยไม่ตั้ง token (กันคนอื่นสั่งแก้ไฟล์เครื่องนี้ "
            "โดยไม่ยืนยันตัวตน) — ตั้ง --token หรือ env LCA_TOKEN. ดู Rule ข้อ 12 ใน SKILL.md")
    return {"host": host, "port": port, "token": token}


def main():
    parser = argparse.ArgumentParser(description="Backend server สำหรับ Local Code Assistant web UI")
    parser.add_argument("project_dir", type=str, help="โฟลเดอร์โปรเจกต์ (ใช้กับ todo)")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                         help="bind address — ใช้ 127.0.0.1 เท่านั้นถ้าไม่ต้องการเปิดให้เครื่องอื่นเข้าถึง "
                              "(cloud: ตั้ง env LCA_HOST=0.0.0.0)")
    parser.add_argument("--port", type=int, default=8420,
                         help="พอร์ต (cloud: อ่าน $PORT ให้อัตโนมัติถ้าไม่ระบุ)")
    parser.add_argument("--token", type=str, default=None,
                         help="auth token — บังคับใส่ถ้า bind ไม่ใช่ 127.0.0.1 (ตาม Rule ข้อ 12); "
                              "cloud ตั้ง env LCA_TOKEN ได้")
    args = parser.parse_args()

    project_root = Path(args.project_dir).resolve()
    if not project_root.exists():
        print(f"ไม่พบโฟลเดอร์: {project_root}")
        sys.exit(1)

    try:
        cfg = resolve_server_config(args)
    except ValueError as e:
        print(f"[ปฏิเสธ] {e}")
        sys.exit(1)

    handler_cls = make_handler(project_root, cfg["token"], bind_host=cfg["host"])
    try:
        httpd = ThreadingHTTPServer((cfg["host"], cfg["port"]), handler_cls)
    except OSError:
        # พอร์ตถูกใช้อยู่ — ถ้าเป็นเครื่อง local (ไม่ใช่ cloud ที่ฉีด $PORT มา) หาพอร์ตว่างให้อัตโนมัติ
        if os.environ.get("PORT"):
            print(f"[ปฏิเสธ] พอร์ต {cfg['port']} ($PORT) ถูกใช้อยู่ — cloud ต้องปล่อยพอร์ตนี้ให้ว่าง")
            sys.exit(1)
        new_port = find_free_port(cfg["port"] + 1, cfg["host"])
        print(f"[info] พอร์ต {cfg['port']} ถูกใช้อยู่ — เปลี่ยนไปใช้พอร์ตว่าง {new_port} แทน")
        cfg["port"] = new_port
        httpd = ThreadingHTTPServer((cfg["host"], cfg["port"]), handler_cls)
    print(f"=== Local Assistant Server ===")
    print(f"โปรเจกต์: {project_root}")
    print(f"เปิดเบราว์เซอร์ที่: http://{cfg['host']}:{cfg['port']}")
    if cfg["token"]:
        print("[auth] ต้องใส่ header X-Auth-Token เพื่อเรียก API")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nปิด server แล้ว")
        httpd.shutdown()


if __name__ == "__main__":
    main()
