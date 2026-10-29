"""tools.py — เครื่องมือที่ agent เรียกใช้ได้ + sandbox (ความปลอดภัยสำคัญที่สุด)

agent "ลงมือ" ผ่าน tool เท่านั้น — ทุก tool ถูกคุมขอบเขต:
- ไฟล์: อ่าน/ลิสต์ได้เฉพาะ *ภายใน workspace ของงานนั้น* (กันอ่านไฟล์นอก เช่น /etc/passwd,
  config.json ที่มี secret) — resolve path จริงแล้วเช็กว่ายังอยู่ใต้ workspace
- คำสั่ง: รันได้เฉพาะชื่อใน allowlist, ไม่ผ่าน shell (กัน injection), timeout, cwd=workspace
- ไม่มี tool เขียน/ลบไฟล์ หรือ network ในชุดพื้นฐาน (P2 = อ่าน+ตรวจก่อน; เขียน/ลบ/เน็ต
  ค่อยเพิ่มพร้อม approval gate — ดู docs/AGENT_TECH_PLAN.md P6)

ซื่อตรง: นี่คือ sandbox ระดับ "จำกัดด้วย allowlist + confine path" ไม่ใช่ container/VM isolation
จริง — พอสำหรับงานอ่าน/ตรวจบนเครื่องที่เชื่อถือ ยังไม่ควรเปิดรับงานจากคนนอกที่ไม่ไว้ใจ

stdlib ล้วน (subprocess/pathlib).
"""

from __future__ import annotations

import ipaddress
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HTTP_TIMEOUT = 15            # วินาที/คำขอ
MAX_HTTP_CHARS = 8000        # ตัดเนื้อหายาว ๆ กัน context ระเบิด

# คำสั่งที่อนุญาต (อ่าน/ตรวจอย่างเดียว — ไม่มีคำสั่งเขียน/ลบ/ติดตั้ง/เครือข่าย)
DEFAULT_ALLOWED_COMMANDS = (
    "ls", "cat", "pwd", "echo", "head", "tail", "wc",
    "grep", "find", "python", "python3", "pytest", "git",
)
COMMAND_TIMEOUT = 30          # วินาที/คำสั่ง
MAX_OUTPUT_CHARS = 4000       # ตัด output ยาว ๆ กัน context ระเบิด


class ToolError(Exception):
    """tool ทำงานไม่ได้/ถูกปฏิเสธ — ป้อนข้อความนี้กลับให้ agent เป็น observation"""


class Sandbox:
    """ขอบเขตของงาน 1 งาน: ทุก path ต้องอยู่ใต้ root; คำสั่งต้องอยู่ใน allowlist"""

    def __init__(self, root, allowed_commands=DEFAULT_ALLOWED_COMMANDS):
        self.root = Path(root).resolve()
        self.allowed = tuple(allowed_commands)

    def _safe_path(self, rel: str) -> Path:
        """แปลง path ที่ agent ขอ → path จริงใต้ root; หลุดออกนอก = ToolError"""
        rel = (rel or "").strip()
        p = (self.root / rel).resolve()
        # เช็กว่ายังอยู่ใต้ root (กัน ../ หลุดออก หรือ symlink พาออก)
        if p != self.root and self.root not in p.parents:
            raise ToolError(f"ปฏิเสธ: path '{rel}' อยู่นอก workspace (กันอ่านไฟล์นอกขอบเขต)")
        return p

    # ---------- tools ----------
    def read_file(self, path: str) -> str:
        p = self._safe_path(path)
        if not p.is_file():
            raise ToolError(f"ไม่พบไฟล์: {path}")
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise ToolError(f"อ่านไฟล์ไม่ได้: {e.__class__.__name__}")
        return text[:MAX_OUTPUT_CHARS]

    def list_dir(self, path: str = ".") -> str:
        p = self._safe_path(path)
        if not p.is_dir():
            raise ToolError(f"ไม่ใช่โฟลเดอร์: {path}")
        names = sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())
        return "\n".join(names) if names else "(ว่าง)"

    def run_command(self, command) -> str:
        """รันคำสั่ง (list ของ args หรือ string) — เฉพาะใน allowlist, ไม่ผ่าน shell"""
        args = command.split() if isinstance(command, str) else list(command)
        if not args:
            raise ToolError("ไม่มีคำสั่ง")
        name = Path(args[0]).name   # กัน path เต็ม /usr/bin/rm เลี่ยง allowlist
        if name not in self.allowed:
            raise ToolError(f"ปฏิเสธคำสั่ง '{name}' (อนุญาตเฉพาะ: {', '.join(self.allowed)})")
        try:
            proc = subprocess.run(
                [name] + args[1:], cwd=str(self.root), capture_output=True,
                text=True, timeout=COMMAND_TIMEOUT, shell=False,   # shell=False = กัน injection
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"คำสั่งเกินเวลา {COMMAND_TIMEOUT}s — ยกเลิก")
        except (OSError, ValueError) as e:
            raise ToolError(f"รันคำสั่งไม่ได้: {e.__class__.__name__}")
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        out = out[:MAX_OUTPUT_CHARS]
        return f"(exit {proc.returncode})\n{out}".strip()

    def write_file(self, path: str, content: str) -> str:
        """เขียนไฟล์ใน workspace (confine ใต้ root). *irreversible* — ใช้ผ่าน approval เท่านั้น"""
        p = self._safe_path(path)
        if p == self.root:
            raise ToolError("เขียนทับ root ไม่ได้")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content if content is not None else "", encoding="utf-8")
        except OSError as e:
            raise ToolError(f"เขียนไฟล์ไม่ได้: {e.__class__.__name__}")
        return f"เขียนไฟล์แล้ว: {path} ({len(content or '')} ตัวอักษร)"


def _assert_public_url(url: str):
    """กัน SSRF: อนุญาตเฉพาะ http/https ที่ปลายทางเป็น IP สาธารณะ — ปฏิเสธ loopback/
    private/link-local/reserved (กัน agent ยิงเข้าในวงแลน/metadata endpoint ของ cloud).
    ซื่อตรง: resolve ตอนเช็ก แต่ urllib resolve ซ้ำตอน fetch (TOCTOU/DNS rebinding ยังเหลือ
    residual risk เล็กน้อย) — เป็น opt-in ให้ operator ที่เชื่อถือเปิดเองเท่านั้น"""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ToolError("อนุญาตเฉพาะ http/https")
    host = p.hostname
    if not host:
        raise ToolError("URL ไม่มี host")
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        raise ToolError("resolve host ไม่ได้")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ToolError(f"ปฏิเสธ: ปลายทาง {ip} เป็น IP ภายใน/สงวน (กัน SSRF)")
    return p


def http_get(url: str) -> str:
    """ดึงเนื้อหา URL สาธารณะ (GET อย่างเดียว) — ผ่านด่านกัน SSRF, timeout, ตัดขนาด"""
    _assert_public_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "LCA-agent"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read(MAX_HTTP_CHARS * 4)   # cap bytes ก่อน decode
    except urllib.error.URLError as e:
        raise ToolError(f"ดึง URL ไม่ได้: {e.__class__.__name__}")
    except OSError as e:
        raise ToolError(f"ดึง URL ไม่ได้: {e.__class__.__name__}")
    text = raw.decode("utf-8", errors="replace")[:MAX_HTTP_CHARS]
    return f"[{ctype}]\n{text}".strip()


# schema ของ tool (ให้ agent รู้ว่ามีอะไร เรียกยังไง) — ใช้ประกอบ system prompt
TOOL_SCHEMAS = [
    {"name": "read_file", "args": {"path": "str"}, "desc": "อ่านไฟล์ใน workspace"},
    {"name": "list_dir", "args": {"path": "str (default '.')"}, "desc": "ลิสต์ไฟล์ในโฟลเดอร์"},
    {"name": "run_command", "args": {"command": "str"}, "desc": f"รันคำสั่ง (เฉพาะ: {', '.join(DEFAULT_ALLOWED_COMMANDS)})"},
]


# tool "เสนอ" (P6) — ไม่ลงมือเอง สร้างคำขออนุมัติให้คนกด (ปรากฏเฉพาะเมื่อเปิด approvals)
PROPOSE_SCHEMAS = [
    {"name": "propose_write_file", "args": {"path": "str", "content": "str"},
     "desc": "เสนอเขียนไฟล์ (ต้องรอคนอนุมัติก่อน ไม่เขียนทันที)"},
    {"name": "propose_command", "args": {"command": "str"},
     "desc": "เสนอรันคำสั่งที่เปลี่ยนแปลงระบบ (ต้องรอคนอนุมัติก่อน)"},
]


# tool เครือข่าย (opt-in) — ผิวสัมผัสความปลอดภัยสูง เปิดเฉพาะเมื่อ skill ตั้ง tools_net
NET_SCHEMAS = [
    {"name": "http_get", "args": {"url": "str"},
     "desc": "ดึงเนื้อหา URL สาธารณะ (GET; กัน SSRF ปฏิเสธ IP ภายใน)"},
    {"name": "call_connection", "args": {"connection_id": "str", "prompt": "str"},
     "desc": "ถามสมอง (connection) อีกตัวเป็น sub-tool แล้วเอาคำตอบมาใช้ต่อ"},
]


def build_registry(sandbox: Sandbox, approvals_root=None, net_ctx=None) -> dict:
    """คืน map ชื่อ tool -> ฟังก์ชัน(args)->str. ถ้าให้ approvals_root จะเปิด tool 'เสนอ' (P6)
    ที่สร้างคำขออนุมัติแทนการลงมือเอง — ของจริงเกิดตอนคนกดอนุมัติที่ /dev เท่านั้น.
    ถ้าให้ net_ctx ({'project_root': ...}) จะเปิด tool เครือข่าย (http_get/call_connection)"""
    reg = {
        "read_file": lambda a: sandbox.read_file(a.get("path", "")),
        "list_dir": lambda a: sandbox.list_dir(a.get("path", ".")),
        "run_command": lambda a: sandbox.run_command(a.get("command", "")),
    }
    if approvals_root is not None:
        from app.agent import approvals   # lazy — กัน circular import
        ws = str(sandbox.root)

        def _propose(kind, detail):
            rec = approvals.request(approvals_root, kind, ws, detail)
            return f"⏳ เสนอแล้ว รออนุมัติที่ /dev (id: {rec['id']}) — ยังไม่ลงมือจนกว่าคนจะกดอนุมัติ"

        reg["propose_write_file"] = lambda a: _propose(
            approvals.KIND_WRITE, {"path": a.get("path", ""), "content": a.get("content", "")})
        reg["propose_command"] = lambda a: _propose(
            approvals.KIND_COMMAND, {"command": a.get("command", "")})
    if net_ctx is not None:
        pr = net_ctx.get("project_root")

        def _call_connection(a):
            from app import connections   # lazy — กัน circular import
            cid = (a.get("connection_id") or "").strip()
            prompt = (a.get("prompt") or "").strip()
            if not cid or not prompt:
                raise ToolError("ต้องระบุ connection_id และ prompt")
            try:
                return connections.chat(pr, cid, [{"role": "user", "content": prompt}])
            except connections.ConnectionError as e:
                raise ToolError(f"เรียก connection ไม่สำเร็จ: {e}")

        reg["http_get"] = lambda a: http_get(a.get("url", ""))
        reg["call_connection"] = _call_connection
    return reg
