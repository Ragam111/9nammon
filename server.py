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
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent))
from local_coder import call_ollama, get_system_prompt  # noqa: E402
from app.todo_store import load_todos, add_todo, toggle_todo, delete_todo  # noqa: E402
from app import org_store  # noqa: E402  (ระบบองค์กร: user/role/api key/quota)

APP_DIR = Path(__file__).parent / "app"
INDEX_HTML = APP_DIR / "index.html"


def make_handler(project_root: Path, auth_token: Optional[str]):
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

        # ---------- View: serve index.html ----------
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._serve_index()
            elif parsed.path == "/api/todos":
                self._handle_todos_get()
            elif parsed.path == "/api/me":
                self._handle_me()
            elif parsed.path == "/api/admin/users":
                self._handle_users_list()
            elif parsed.path == "/api/admin/apikeys":
                self._handle_apikeys_list()
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

        def _serve_index(self):
            try:
                html = INDEX_HTML.read_text(encoding="utf-8")
            except OSError as e:
                self._send_json(500, {"error": f"อ่าน index.html ไม่ได้: {e}"})
                return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # ---------- Controller: API routes ----------
        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/chat":
                    self._handle_chat()
                elif parsed.path == "/api/todos":
                    self._handle_todos_post()
                elif parsed.path == "/api/todos/toggle":
                    self._handle_todos_toggle()
                elif parsed.path == "/api/admin/users":
                    self._handle_users_create()
                elif parsed.path == "/api/admin/users/active":
                    self._handle_users_set_active()
                elif parsed.path == "/api/admin/apikeys":
                    self._handle_apikeys_create()
                elif parsed.path == "/api/admin/apikeys/revoke":
                    self._handle_apikeys_revoke()
                else:
                    self._send_json(404, {"error": "not found"})
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
            # bootstrap: ยังไม่มี user เลย → อนุญาตสร้าง CEO คนแรกโดยไม่ต้อง auth
            if org_store.bootstrap_needed(project_root):
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

        def _handle_chat(self):
            ident = self._require("USER")
            if ident is None:
                return
            # กินโควตาเฉพาะเมื่อเข้ามาด้วย API key (master/local ไม่มีโควตา)
            if ident.get("key_id"):
                ok, remaining = org_store.consume_quota(project_root, ident["key_id"])
                if not ok:
                    self._send_json(429, {"error": "เกินโควตาการใช้งานรายวันของ API key นี้แล้ว "
                                                   "(อัปเกรดเป็น tier paid เพื่อใช้ได้ไม่จำกัด)"})
                    return
            data = self._read_json_body()
            model = data.get("model", "qwen2.5-coder:0.5b")
            messages = data.get("messages", [])
            num_ctx = data.get("num_ctx", 8192)
            lang = data.get("lang", "th")
            if not messages:
                self._send_json(400, {"error": "ต้องมี messages"})
                return
            # ถ้า client ไม่ได้แนบ system prompt มา (เช่น index.html ที่ส่งแค่ user/assistant)
            # ให้ server แทรกให้เองตาม lang ที่เลือก
            if not messages or messages[0].get("role") != "system":
                messages = [{"role": "system", "content": get_system_prompt(lang)}] + messages
            # Model layer: เรียก Ollama ผ่านฟังก์ชันเดียวกับ CLI (ไม่ซ้ำ logic)
            try:
                reply = call_ollama(model, messages, num_ctx)
            except SystemExit:
                # call_ollama เดิมออกแบบมาให้ exit ตอน error (CLI context) — server ต้อง
                # ไม่ตายทั้งโปรเซส จึงจับ SystemExit แล้วแปลงเป็น error response แทน
                self._send_json(502, {"error": "เรียก Ollama ไม่สำเร็จ ตรวจสอบว่า ollama serve รันอยู่หรือไม่"})
                return
            self._send_json(200, {"reply": reply})

        def _handle_todos_get(self):
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

    return LocalAssistantHandler


def main():
    parser = argparse.ArgumentParser(description="Backend server สำหรับ Local Code Assistant web UI")
    parser.add_argument("project_dir", type=str, help="โฟลเดอร์โปรเจกต์ (ใช้กับ todo)")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                         help="bind address — ใช้ 127.0.0.1 เท่านั้นถ้าไม่ต้องการเปิดให้เครื่องอื่นเข้าถึง")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--token", type=str, default=None,
                         help="auth token — บังคับใส่ถ้า --host ไม่ใช่ 127.0.0.1 (ตาม Rule ข้อ 12)")
    args = parser.parse_args()

    project_root = Path(args.project_dir).resolve()
    if not project_root.exists():
        print(f"ไม่พบโฟลเดอร์: {project_root}")
        sys.exit(1)

    if args.host != "127.0.0.1" and not args.token:
        print("[ปฏิเสธ] ห้าม bind ออกนอก 127.0.0.1 โดยไม่ตั้ง --token "
              "(กันคนอื่นใน LAN สั่งแก้ไฟล์เครื่องนี้โดยไม่ยืนยันตัวตน) — ดู Rule ข้อ 12 ใน SKILL.md")
        sys.exit(1)

    handler_cls = make_handler(project_root, args.token)
    httpd = ThreadingHTTPServer((args.host, args.port), handler_cls)
    print(f"=== Local Assistant Server ===")
    print(f"โปรเจกต์: {project_root}")
    print(f"เปิดเบราว์เซอร์ที่: http://{args.host}:{args.port}")
    if args.token:
        print("[auth] ต้องใส่ header X-Auth-Token เพื่อเรียก API")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nปิด server แล้ว")
        httpd.shutdown()


if __name__ == "__main__":
    main()
