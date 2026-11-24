"""test_agent_tools_security.py — ความปลอดภัยของ run_command และการ confine path

ครอบคลุม: run_command ปิดเป็นค่าเริ่มต้น, allowlist ไม่มี python/find/git,
absolute path และ ../ ถูกปฏิเสธใน arg, read/list นอก root ถูกปฏิเสธ, symlink ชี้ออกนอก root ถูกปฏิเสธ.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import tools  # noqa: E402
from app.agent.tools import (  # noqa: E402
    DEFAULT_ALLOWED_COMMANDS, Sandbox, ToolError, build_registry,
)


class _TwoDirTest(unittest.TestCase):
    """root = workspace ที่ agent ทำงาน; outside = โฟลเดอร์นอก root ที่มี 'secret'"""

    def setUp(self):
        self._root_tmp = tempfile.TemporaryDirectory()
        self._out_tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._root_tmp.name).resolve()
        self.outside = Path(self._out_tmp.name).resolve()
        (self.root / "hello.txt").write_text("hello world", encoding="utf-8")
        (self.outside / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
        self.closed = Sandbox(self.root)
        self.open = Sandbox(self.root, allow_commands=True)

    def tearDown(self):
        self._root_tmp.cleanup()
        self._out_tmp.cleanup()


class RunCommandDefaultOffTest(_TwoDirTest):
    def test_run_command_off_by_default_raises(self):
        with self.assertRaises(ToolError):
            self.closed.run_command("echo hi")

    def test_run_command_off_even_for_allowed_name(self):
        with self.assertRaises(ToolError):
            self.closed.run_command("ls")

    def test_registry_run_command_off_by_default(self):
        reg = build_registry(self.closed)
        with self.assertRaises(ToolError):
            reg["run_command"]({"command": "echo hi"})

    def test_flag_must_be_explicit_true(self):
        sb = Sandbox(self.root, allow_commands=True)
        self.assertEqual(sb.run_command("echo ok").splitlines()[-1].strip(), "ok")


class AllowlistTest(_TwoDirTest):
    def test_python_find_git_removed_from_default(self):
        for name in ("python", "python3", "find", "git"):
            with self.subTest(name=name):
                self.assertNotIn(name, DEFAULT_ALLOWED_COMMANDS)

    def test_python_c_rejected(self):
        with self.assertRaises(ToolError):
            self.open.run_command('python -c "import os; os.system(\'id\')"')

    def test_find_exec_rejected(self):
        with self.assertRaises(ToolError):
            self.open.run_command("find . -exec cat {} ;")

    def test_git_rejected(self):
        with self.assertRaises(ToolError):
            self.open.run_command("git status")


class ArgPathTest(_TwoDirTest):
    def test_absolute_system_path_rejected(self):
        with self.assertRaises(ToolError):
            self.open.run_command("cat /etc/passwd")

    def test_dotdot_path_rejected(self):
        with self.assertRaises(ToolError):
            self.open.run_command("cat ../x")

    def test_absolute_path_inside_root_still_rejected(self):
        target = str(self.root / "hello.txt")
        with self.assertRaises(ToolError):
            self.open.run_command(["cat", target])

    def test_option_value_with_absolute_path_rejected(self):
        with self.assertRaises(ToolError):
            self.open.run_command("wc --files0-from=/etc/passwd")

    def test_relative_file_inside_root_allowed(self):
        self.assertIn("hello world", self.open.run_command("cat hello.txt"))


class ReadListConfinementTest(_TwoDirTest):
    def test_list_dir_dotdot_rejected(self):
        with self.assertRaises(ToolError):
            self.closed.list_dir("../..")

    def test_read_file_absolute_rejected(self):
        with self.assertRaises(ToolError):
            self.closed.read_file("/etc/passwd")

    def test_read_file_outside_root_rejected(self):
        with self.assertRaises(ToolError):
            self.closed.read_file(str(self.outside / "secret.txt"))


class SymlinkEscapeTest(_TwoDirTest):
    def _link(self, name: str, target: Path, is_dir: bool = False) -> None:
        link = self.root / name
        try:
            os.symlink(target, link, target_is_directory=is_dir)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"สร้าง symlink ไม่ได้บนเครื่องนี้ ({exc.__class__.__name__}) — ข้ามเทสต์")

    def test_symlink_file_outside_rejected_on_read(self):
        self._link("link.txt", self.outside / "secret.txt")
        with self.assertRaises(ToolError):
            self.closed.read_file("link.txt")

    def test_symlink_file_outside_rejected_in_command(self):
        self._link("link.txt", self.outside / "secret.txt")
        with self.assertRaises(ToolError):
            self.open.run_command("cat link.txt")

    def test_symlink_dir_outside_rejected_on_list(self):
        self._link("linkdir", self.outside, is_dir=True)
        with self.assertRaises(ToolError):
            self.closed.list_dir("linkdir")


if __name__ == "__main__":
    unittest.main()
