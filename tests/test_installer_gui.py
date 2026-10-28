"""test_installer_gui.py — ตรรกะติดตั้งของ installer GUI (ไม่แตะ tkinter/เน็ตจริง)

mock การดาวน์โหลด (urlretrieve) ด้วย zip ปลอมที่สร้างเอง → เทส do_install คัดลอกครบ +
progress ถึง 100 + สร้าง start-lca.bat + desktop icon. ไม่ import tkinter (อยู่ใน launch_gui เท่านั้น)
"""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

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

    def test_install_copies_program_and_reaches_100(self):
        seen = []
        with mock.patch.object(installer_gui.urllib.request, "urlretrieve", self._fake_urlretrieve):
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

    def test_desktop_icon_created_when_requested(self):
        desktop = self.base / "Desktop"
        desktop.mkdir()
        with mock.patch.object(installer_gui.urllib.request, "urlretrieve", self._fake_urlretrieve), \
             mock.patch.dict(installer_gui.os.environ, {"USERPROFILE": str(self.base)}):
            installer_gui.do_install(str(self.install_dir), make_desktop_icon=True,
                                     progress_cb=lambda p, m: None)
        icons = list(desktop.glob("*.bat"))
        self.assertEqual(len(icons), 1)
        self.assertIn("start-lca.bat", icons[0].read_text(encoding="utf-8"))

    def test_find_src_root_handles_github_folder(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "9nammon-main").mkdir()
            (t / "9nammon-main" / "server.py").write_text("x")
            self.assertEqual(installer_gui._find_src_root(t).name, "9nammon-main")

    def test_default_install_dir_nonempty(self):
        self.assertTrue(installer_gui.default_install_dir())


if __name__ == "__main__":
    unittest.main()
