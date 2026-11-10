"""test_server_startup.py — `python server.py` เฉยๆ ต้องเปิดได้ (project_dir ไม่บังคับ)
และบรรทัดเริ่มต้นต้องพิมพ์ URL เต็มที่คลิกได้: /chat + #lca_token=

(Nammon เจอ `error: the following arguments are required: project_dir` บน Windows)
"""

import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class _H:
    session_token_auto = True
    session_token = "tok_ABC-123"


class _Fixed:
    session_token_auto = False
    session_token = "user-set-secret"


class StartupUrlTest(unittest.TestCase):
    def test_loopback_has_chat_and_token(self):
        url = server.startup_url({"host": "127.0.0.1", "port": 8420}, _H)
        self.assertEqual(url, "http://127.0.0.1:8420/chat#lca_token=tok_ABC-123")

    def test_wildcard_bind_shows_loopback(self):
        url = server.startup_url({"host": "0.0.0.0", "port": 9000}, _H)
        self.assertTrue(url.startswith("http://127.0.0.1:9000/chat"))

    def test_ipv6_bracketed(self):
        url = server.startup_url({"host": "::1", "port": 8420}, _H)
        self.assertTrue(url.startswith("http://[::1]:8420/chat"))

    def test_user_token_not_leaked_into_url(self):
        url = server.startup_url({"host": "0.0.0.0", "port": 8420}, _Fixed)
        self.assertEqual(url, "http://127.0.0.1:8420/chat")
        self.assertNotIn("user-set-secret", url)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class NoProjectDirArgTest(unittest.TestCase):
    def test_python_server_py_without_args_starts_in_cwd(self):
        port = _free_port()
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            for k in ("PORT", "LCA_HOST", "LCA_TOKEN"):
                env.pop(k, None)
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "server.py"), "--port", str(port)],
                cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            lines = []
            try:
                deadline = time.time() + 30
                while time.time() < deadline:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    lines.append(line)
                    if "X-Auth-Token" in line:
                        break
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()
            out = "".join(lines)
            self.assertNotIn("required", out)
            self.assertIn(str(Path(tmp).resolve()), out)  # project = โฟลเดอร์ปัจจุบัน
            self.assertRegex(
                out, re.escape(f"http://127.0.0.1:{port}/chat#lca_token=") + r"[A-Za-z0-9_\-]{20,}")


if __name__ == "__main__":
    unittest.main()
