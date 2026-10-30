"""test_lca_app.py — LCA Desktop (แอปก้อนเดียว): resource root ตอน frozen + build_server"""

import http.client
import io
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
import lca_app  # noqa: E402


class ResourceRootTest(unittest.TestCase):
    def test_not_frozen_uses_script_dir(self):
        # ปกติ (ไม่ได้ถูกแพ็กเป็น .exe) → รากไฟล์ = โฟลเดอร์ของ server.py
        self.assertEqual(server._resource_root(), Path(server.__file__).resolve().parent)


class FirstRunTest(unittest.TestCase):
    """v0.1.2+: _is_first_run เช็ค connections.json เพื่อ redirect ไป /console"""

    def test_no_connections_file_is_first_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(lca_app._is_first_run(Path(tmp)))

    def test_empty_connections_is_first_run(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "connections.json").write_text(
                json.dumps({"schema_version": 1, "records": []}), encoding="utf-8")
            self.assertTrue(lca_app._is_first_run(p))

    def test_has_connection_not_first_run(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "connections.json").write_text(
                json.dumps({"schema_version": 1, "records": [{"id": "c1"}]}),
                encoding="utf-8")
            self.assertFalse(lca_app._is_first_run(p))

    def test_corrupted_json_treated_as_first_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "connections.json").write_text("NOT JSON", encoding="utf-8")
            self.assertTrue(lca_app._is_first_run(p))

    def test_frozen_uses_meipass(self):
        # จำลอง pyinstaller: sys.frozen + sys._MEIPASS → ใช้ path นั้น
        def _restore():
            for attr in ("frozen", "_MEIPASS"):
                if hasattr(sys, attr):
                    delattr(sys, attr)
        self.addCleanup(_restore)
        sys.frozen = True
        sys._MEIPASS = "/tmp/_meipass_test"
        self.assertEqual(server._resource_root(), Path("/tmp/_meipass_test"))


class DataDirTest(unittest.TestCase):
    def test_data_dir_created_under_localappdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            import os
            old = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = tmp
            try:
                d = lca_app.data_dir()
                self.assertTrue(d.is_dir())
                self.assertEqual(d, Path(tmp) / "LocalCodeAssistant" / "data")
            finally:
                if old is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = old


class BuildServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.call_ollama = lambda model, messages, num_ctx=8192: "mocked"

    def test_build_server_binds_and_serves(self):
        with tempfile.TemporaryDirectory() as tmp:
            httpd, port = lca_app.build_server(tmp, preferred_port=0)   # 0 = หา port ว่างเอง
            self.assertGreater(port, 0)
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/health")
                r = conn.getresponse()
                self.assertEqual(r.status, 200)
                r.read(); conn.close()
                # เสิร์ฟหน้าเว็บ shell ได้ (bind 127.0.0.1 = local = CEO ไม่ต้อง auth)
                conn2 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn2.request("GET", "/")
                r2 = conn2.getresponse()
                self.assertEqual(r2.status, 200)
                r2.read(); conn2.close()
            finally:
                httpd.shutdown()
                httpd.server_close()


class VersionFlagTest(unittest.TestCase):
    """`--version` CLI flag ต้องตรงกับ VERSION file และ /api/version endpoint"""

    def test_lca_app_version_flag(self):
        # เรียก lca_app.py --version → stdout ขึ้นเวอร์ชันแล้ว exit 0
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, str(root / "lca_app.py"), "--version"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("LCA Desktop", result.stdout)
        # ต้องมี version string (X.Y.Z หรือ unknown)
        self.assertTrue(any(c.isdigit() for c in result.stdout) or "unknown" in result.stdout)

    def test_server_version_flag(self):
        # เรียก server.py --version → ต้องมี "LCA" + version + python version
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, str(root / "server.py"), "--version"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("LCA", result.stdout)
        self.assertIn("python", result.stdout)


class ReadVersionTest(unittest.TestCase):
    """server.read_version() helper — shared ระหว่าง /api/version กับ --version CLI"""

    def test_reads_version_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            self.assertEqual(server.read_version(p), "9.9.9")

    def test_fallback_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(server.read_version(Path(tmp)), "unknown")

    def test_fallback_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "VERSION").write_text("", encoding="utf-8")
            self.assertEqual(server.read_version(p), "unknown")

    def test_strips_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "VERSION").write_text("  0.1.5  \n\n", encoding="utf-8")
            self.assertEqual(server.read_version(p), "0.1.5")

    def test_default_root_resource_root(self):
        # ไม่ส่ง root → ใช้ _resource_root() = ที่อยู่ server.py (มี VERSION อยู่จริง)
        self.assertNotEqual(server.read_version(), "")


if __name__ == "__main__":
    unittest.main()
