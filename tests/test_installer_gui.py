"""test_installer_gui.py — ตรรกะติดตั้งของ installer GUI (ไม่แตะ tkinter/เน็ตจริง)

mock การดาวน์โหลด (urlretrieve) ด้วย zip ปลอมที่สร้างเอง → เทส do_install คัดลอกครบ +
progress ถึง 100 + สร้าง start-lca.bat + desktop icon. ไม่ import tkinter (อยู่ใน launch_gui เท่านั้น)
"""

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import installer_gui  # noqa: E402


def _make_fake_zip(zip_path: Path):
    """สร้าง zip เลียนแบบ GitHub (โฟลเดอร์ราก 9nammon-main/ + ไฟล์โปรแกรม)"""
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("9nammon-main/server.py", "# server\n")
        zf.writestr("9nammon-main/local_coder.py", "# cli\n")
        zf.writestr("9nammon-main/app/__init__.py", "")
        zf.writestr("9nammon-main/app/model_backend.py", "# backend\n")
        zf.writestr("9nammon-main/sysmanager/__init__.py", "")
        zf.writestr("9nammon-main/lca-tray.bat", "@echo tray\n")
        zf.writestr("9nammon-main/lca-tray.ps1", "# tray\n")


class InstallerLogicTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.install_dir = self.base / "install"
        # zip ปลอมไว้ให้ urlretrieve "ดาวน์โหลด"
        self.fake_zip = self.base / "fake.zip"
        _make_fake_zip(self.fake_zip)

    def tearDown(self):
        self._tmp.cleanup()

    def _fake_urlretrieve(self, url, dest):
        import shutil
        shutil.copy2(self.fake_zip, dest)

    def _fake_download_zip(self, url, dest):
        import shutil
        shutil.copy2(self.fake_zip, dest)
        return "urllib"

    def test_install_copies_program_and_reaches_100(self):
        seen = []
        with mock.patch.object(installer_gui, "_download_zip", self._fake_download_zip):
            installer_gui.do_install(str(self.install_dir), make_desktop_icon=False,
                                     progress_cb=lambda p, m: seen.append(p))
        # ไฟล์โปรแกรมถูกคัดลอกครบ
        self.assertTrue((self.install_dir / "server.py").exists())
        self.assertTrue((self.install_dir / "app" / "model_backend.py").exists())
        self.assertTrue((self.install_dir / "sysmanager" / "__init__.py").exists())
        # มี start-lca.bat (ดับเบิลคลิกเปิดใช้งาน)
        self.assertTrue((self.install_dir / "start-lca.bat").exists())
        # progress ไปถึง 100
        self.assertEqual(seen[-1], 100)

    def test_install_copies_tray_files(self):
        with mock.patch.object(installer_gui, "_download_zip", self._fake_download_zip):
            installer_gui.do_install(str(self.install_dir), make_desktop_icon=False,
                                     progress_cb=lambda p, m: None)
        self.assertTrue((self.install_dir / "lca-tray.bat").exists())
        self.assertTrue((self.install_dir / "lca-tray.ps1").exists())

    def test_desktop_icon_created_when_requested(self):
        desktop = self.base / "Desktop"
        desktop.mkdir()
        with mock.patch.object(installer_gui, "_download_zip", self._fake_download_zip), \
             mock.patch.dict(installer_gui.os.environ, {"USERPROFILE": str(self.base)}):
            installer_gui.do_install(str(self.install_dir), make_desktop_icon=True,
                                     progress_cb=lambda p, m: None)
        icons = list(desktop.glob("*.bat"))
        self.assertEqual(len(icons), 1)
        self.assertIn("start-lca.bat", icons[0].read_text(encoding="utf-8"))

    def test_desktop_icon_use_tray_points_to_tray_bat(self):
        desktop = self.base / "Desktop"
        desktop.mkdir()
        with mock.patch.object(installer_gui, "_download_zip", self._fake_download_zip), \
             mock.patch.dict(installer_gui.os.environ, {"USERPROFILE": str(self.base)}):
            installer_gui.do_install(str(self.install_dir), make_desktop_icon=True,
                                     progress_cb=lambda p, m: None, use_tray=True)
        icons = list(desktop.glob("*.bat"))
        self.assertEqual(len(icons), 1)
        self.assertIn("lca-tray.bat", icons[0].read_text(encoding="utf-8"))

    def test_find_src_root_handles_github_folder(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "9nammon-main").mkdir()
            (t / "9nammon-main" / "server.py").write_text("x")
            self.assertEqual(installer_gui._find_src_root(t).name, "9nammon-main")

    def test_default_install_dir_nonempty(self):
        self.assertTrue(installer_gui.default_install_dir())


class DefaultInstallDirTest(unittest.TestCase):
    def test_uses_localappdata_when_set(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\Nam\AppData\Local"}):
            result = installer_gui.default_install_dir()
            self.assertIn("LocalCodeAssistant", result)
            self.assertIn("AppData", result)

    def test_falls_back_to_home_when_no_localappdata(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LOCALAPPDATA", None)
            result = installer_gui.default_install_dir()
            self.assertIn("LocalCodeAssistant", result)


class FindSrcRootTest(unittest.TestCase):
    def test_finds_direct(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "server.py").write_text("# server", encoding="utf-8")
            self.assertEqual(installer_gui._find_src_root(p), p)

    def test_raises_when_no_server_py(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "random.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                installer_gui._find_src_root(p)


class EnsureStartLauncherTest(unittest.TestCase):
    def test_creates_launcher_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            installer_gui._ensure_start_launcher(p)
            self.assertTrue((p / "start-lca.bat").exists())

    def test_keeps_existing_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            marker = "USER CUSTOM LAUNCHER"
            (p / "start-lca.bat").write_text(marker, encoding="utf-8")
            installer_gui._ensure_start_launcher(p)
            self.assertIn("USER CUSTOM LAUNCHER",
                          (p / "start-lca.bat").read_text(encoding="utf-8"))

    def test_launcher_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            installer_gui._ensure_start_launcher(p)
            content = (p / "start-lca.bat").read_text(encoding="utf-8")
            self.assertIn("python", content.lower())
            self.assertIn("server.py", content)


class MakeDesktopIconTest(unittest.TestCase):
    def test_no_desktop_dir_no_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            fake_home = Path(tmp) / "fake-home-no-desktop"
            fake_home.mkdir()
            with patch.dict(os.environ, {"USERPROFILE": str(fake_home)}):
                installer_gui._make_desktop_icon(p)  # must not raise

    def test_prefers_desktop_bat(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            home = Path(tmp) / "home"
            desktop = home / "Desktop"
            desktop.mkdir(parents=True)
            (p / "lca-desktop.bat").write_text("@echo", encoding="utf-8")
            (p / "start-lca.bat").write_text("@echo", encoding="utf-8")
            with patch.dict(os.environ, {"USERPROFILE": str(home)}):
                installer_gui._make_desktop_icon(p, use_tray=False)
            shortcut = desktop / "เปิด Local Code Assistant.bat"
            self.assertTrue(shortcut.exists())
            self.assertIn("lca-desktop.bat", shortcut.read_text(encoding="utf-8"))

    def test_use_tray_picks_tray_bat(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            home = Path(tmp) / "home"
            desktop = home / "Desktop"
            desktop.mkdir(parents=True)
            (p / "lca-tray.bat").write_text("@echo", encoding="utf-8")
            (p / "lca-desktop.bat").write_text("@echo", encoding="utf-8")
            with patch.dict(os.environ, {"USERPROFILE": str(home)}):
                installer_gui._make_desktop_icon(p, use_tray=True)
            shortcut = desktop / "เปิด Local Code Assistant.bat"
            self.assertIn("lca-tray.bat", shortcut.read_text(encoding="utf-8"))

    def test_fallback_to_start_lca(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            home = Path(tmp) / "home"
            desktop = home / "Desktop"
            desktop.mkdir(parents=True)
            (p / "start-lca.bat").write_text("@echo", encoding="utf-8")
            with patch.dict(os.environ, {"USERPROFILE": str(home)}):
                installer_gui._make_desktop_icon(p, use_tray=True)
            shortcut = desktop / "เปิด Local Code Assistant.bat"
            self.assertIn("start-lca.bat", shortcut.read_text(encoding="utf-8"))


class CopyManifestTest(unittest.TestCase):
    def test_tray_files_in_copy_list(self):
        self.assertIn("lca-tray.bat", installer_gui.COPY_FILES)
        self.assertIn("lca-tray.ps1", installer_gui.COPY_FILES)

    def test_essential_files_in_copy_list(self):
        self.assertIn("server.py", installer_gui.COPY_FILES)
        self.assertIn("start-lca.bat", installer_gui.COPY_FILES)


class DownloadZipTest(unittest.TestCase):
    """bug fix v0.1.2: SSL cert fail → fallback curl → fallback unverified"""

    def test_urllib_success_returns_urllib(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.zip"

            def fake_urlretrieve(url, path):
                Path(path).write_bytes(b"PK\x03\x04fakezip")
            with mock.patch.object(installer_gui.urllib.request, "urlretrieve",
                                   fake_urlretrieve):
                method = installer_gui._download_zip("https://example.com/x.zip", dest)
            self.assertEqual(method, "urllib")

    def test_ssl_fail_falls_back_to_curl(self):
        """ถ้า urllib fail (SSL cert) → ต้องลอง curl ก่อน unverified"""
        import ssl as ssl_module

        def ssl_fail(url, path):
            raise ssl_module.SSLError("CERTIFICATE_VERIFY_FAILED")

        def fake_curl_run(cmd, capture_output, timeout):
            # cmd = ["curl", "-fsSL", "--output", dest, url] → เขียน file ให้
            dest_idx = cmd.index("--output") + 1
            Path(cmd[dest_idx]).write_bytes(b"PK\x03\x04curldata")
            m = mock.MagicMock()
            m.returncode = 0
            return m

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.zip"
            with mock.patch.object(installer_gui.urllib.request, "urlretrieve", ssl_fail), \
                 mock.patch.object(installer_gui.shutil, "which", return_value="/usr/bin/curl"), \
                 mock.patch.object(installer_gui.subprocess, "run", fake_curl_run):
                # Path.exists ต้องคืน True สำหรับ curl path
                with mock.patch("pathlib.Path.exists", return_value=True):
                    method = installer_gui._download_zip("https://x.com/y.zip", dest)
            self.assertEqual(method, "curl")

    def test_both_fail_raises_with_helpful_message(self):
        """ทั้ง urllib และ curl fail → RuntimeError + ข้อความชี้วิธีแก้"""
        def ssl_fail(url, path):
            raise OSError("ssl error")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.zip"
            with mock.patch.object(installer_gui.urllib.request, "urlretrieve", ssl_fail), \
                 mock.patch.object(installer_gui.shutil, "which", return_value=None):
                with self.assertRaises(RuntimeError) as cm:
                    installer_gui._download_zip("https://x.com/y.zip", dest)
            self.assertIn("certifi", str(cm.exception))  # มี recovery message


class CheckFreeDiskTest(unittest.TestCase):
    def test_sufficient_space_returns_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            # ใช้ค่า min เล็กมาก (1 byte) — ยังไงดิสก์จริงก็มีเกิน
            ok, free, msg = installer_gui.check_free_disk(tmp, min_bytes=1)
            self.assertTrue(ok)
            self.assertGreater(free, 0)
            self.assertEqual(msg, "")

    def test_insufficient_space_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            # min ใหญ่กว่าดิสก์จริง (10 PB) → ok=False + ข้อความช่วย recovery
            huge = 10 * 1024 * 1024 * 1024 * 1024 * 1024
            ok, _, msg = installer_gui.check_free_disk(tmp, min_bytes=huge)
            self.assertFalse(ok)
            self.assertIn("MB", msg)
            self.assertIn("ไม่พอ", msg)

    def test_check_nonexistent_parent_falls_back(self):
        # path ที่ยังไม่มี parent — ควร walk up หา parent ที่มีจริง ไม่ crash
        fake = "/tmp/no-such-dir-12345/sub/deeper/install-target"
        ok, _, _ = installer_gui.check_free_disk(fake, min_bytes=1)
        self.assertTrue(ok)  # /tmp มีจริง → check ผ่าน

    def test_error_message_mentions_both_locations(self):
        """bug fix v0.1.1: error message ต้องบอกทั้ง install_dir และ TEMP"""
        with tempfile.TemporaryDirectory() as tmp:
            huge = 10 * 1024 * 1024 * 1024 * 1024 * 1024
            ok, _, msg = installer_gui.check_free_disk(tmp, min_bytes=huge)
            self.assertFalse(ok)
            self.assertIn("install_dir", msg)
            self.assertIn("TEMP", msg)

    def test_probe_free_returns_bytes(self):
        """helper _probe_free คืนจำนวน bytes ว่างของดิสก์"""
        with tempfile.TemporaryDirectory() as tmp:
            free = installer_gui._probe_free(tmp)
            self.assertGreater(free, 0)

    def test_probe_free_walks_up_nonexistent(self):
        """walk up หา parent ที่มีจริง"""
        fake = "/tmp/zzzz-no-such-dir/deeper/install"
        free = installer_gui._probe_free(fake)
        self.assertGreater(free, 0)

    def test_do_install_raises_if_insufficient_disk(self):
        # Mock check_free_disk ให้คืน (False, ...) → do_install ต้อง raise ก่อนดาวน์โหลด
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(installer_gui, "check_free_disk",
                          return_value=(False, 0, "พื้นที่ว่างไม่พอ: test")):
            with self.assertRaises(RuntimeError) as cm:
                installer_gui.do_install(tmp, False, lambda p, m: None)
            self.assertIn("ไม่พอ", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
