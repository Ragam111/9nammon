"""test_cleanup.py — กันถอยหลังของงาน cleanup (PR phase2/cleanup)

- server ไม่ import local_coder (CLI ทั้งตัว) ตอนบูต → บูตเบาขึ้น + ไม่มีโมดูลซ้ำสองชื่อ
- ชื่อเดิมใน local_coder ยังใช้ได้ (re-export จาก app.ollama_client)
- `server.py --open browser|app` แทน `timeout /t 3` ใน .bat
- lca-tray.ps1 มีภาษาไทย → ต้องมี UTF-8 BOM (Windows PowerShell 5.1)
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from app import launch_ui, ollama_client  # noqa: E402


class _Auto:
    session_token_auto = True
    session_token = "tokXYZ"


class _Fixed:
    session_token_auto = False
    session_token = "user-secret"


class ServerBootImportsTest(unittest.TestCase):
    def test_server_does_not_import_cli_modules(self):
        code = ("import sys; sys.path.insert(0, %r); import server; "
                "bad=[m for m in ('local_coder','cli_session','config_manager','todo_store') if m in sys.modules]; "
                "print(','.join(bad))") % str(ROOT)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             cwd=str(ROOT), timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "", "server ไม่ควรโหลด CLI/โมดูลซ้ำชื่อ top-level")

    def test_local_coder_reexports_ollama_client(self):
        import local_coder
        for name in ("OLLAMA_URL", "SYSTEM_PROMPT_TH", "SYSTEM_PROMPT_EN",
                     "call_ollama", "get_system_prompt", "get_tuning_options"):
            self.assertIs(getattr(local_coder, name), getattr(ollama_client, name), name)

    def test_local_coder_version_matches_version_file(self):
        import local_coder
        self.assertEqual(local_coder.__version__, (ROOT / "VERSION").read_text(encoding="utf-8").strip())

    def test_lca_app_open_app_window_is_shared(self):
        import lca_app
        self.assertIs(lca_app.open_app_window, launch_ui.open_app_window)


class LaunchUiUrlTest(unittest.TestCase):
    def test_loopback_gets_chat_and_token_fragment(self):
        self.assertEqual(server.launch_ui_url({"host": "127.0.0.1", "port": 8421}, _Auto),
                         "http://127.0.0.1:8421/chat#lca_token=tokXYZ")

    def test_ipv6_loopback(self):
        self.assertTrue(server.launch_ui_url({"host": "::1", "port": 8420}, _Auto)
                        .startswith("http://[::1]:8420/chat"))

    def test_user_token_not_put_in_url(self):
        self.assertEqual(server.launch_ui_url({"host": "localhost", "port": 8420}, _Fixed),
                         "http://127.0.0.1:8420/chat")

    def test_non_loopback_never_auto_opens(self):
        for host in ("0.0.0.0", "192.168.1.5", "::"):
            self.assertIsNone(server.launch_ui_url({"host": host, "port": 8420}, _Auto), host)


class OpenUiDispatchTest(unittest.TestCase):
    def test_modes(self):
        with mock.patch.object(launch_ui, "open_browser") as b, \
             mock.patch.object(launch_ui, "open_app_window") as a:
            launch_ui.open_ui("u", "none")
            launch_ui.open_ui("u", "browser")
            launch_ui.open_ui("u", "app")
        b.assert_called_once_with("u")
        a.assert_called_once_with("u")

    def test_app_window_falls_back_to_browser(self):
        with mock.patch.object(launch_ui.sys, "platform", "linux"), \
             mock.patch.object(launch_ui.subprocess, "Popen", side_effect=OSError), \
             mock.patch.object(launch_ui, "open_browser") as b:
            launch_ui.open_app_window("http://x/")
        b.assert_called_once_with("http://x/")


class LauncherFilesTest(unittest.TestCase):
    def _bat(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_start_lca_uses_open_without_sleep(self):
        s = self._bat("start-lca.bat")
        self.assertIn("server.py", s)
        self.assertIn("--open", s)
        self.assertNotIn("timeout /t", s)

    def test_lca_desktop_reuses_start_lca(self):
        s = self._bat("lca-desktop.bat")
        self.assertIn("start-lca.bat", s)
        self.assertIn("--app", s)
        self.assertNotIn("timeout /t", s)

    def test_lca_tray_has_utf8_bom(self):
        self.assertTrue((ROOT / "lca-tray.ps1").read_bytes().startswith(b"\xef\xbb\xbf"))


class RemovedAdaptersTest(unittest.TestCase):
    def test_unused_backends_removed(self):
        self.assertFalse((ROOT / "app" / "auth_backend.py").exists())
        self.assertFalse((ROOT / "app" / "storage_backend.py").exists())


if __name__ == "__main__":
    unittest.main()
