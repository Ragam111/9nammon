"""test_agent_tools.py — Sandbox path confinement, command allowlist, SSRF guard"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.tools import (  # noqa: E402
    Sandbox, ToolError, _assert_public_url, build_registry,
    DEFAULT_ALLOWED_COMMANDS, MAX_OUTPUT_CHARS,
)


class SandboxPathConfinementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sb = Sandbox(self.tmp)
        Path(self.tmp, "hello.txt").write_text("hello world", encoding="utf-8")
        Path(self.tmp, "sub").mkdir()
        Path(self.tmp, "sub", "nested.txt").write_text("nested", encoding="utf-8")

    def test_read_file_in_workspace(self):
        self.assertIn("hello", self.sb.read_file("hello.txt"))

    def test_read_nested_file(self):
        self.assertIn("nested", self.sb.read_file("sub/nested.txt"))

    def test_path_traversal_rejected(self):
        with self.assertRaises(ToolError):
            self.sb.read_file("../../etc/passwd")

    def test_absolute_path_outside_rejected(self):
        with self.assertRaises(ToolError):
            self.sb._safe_path("/etc/passwd")

    def test_dotdot_in_middle_rejected(self):
        with self.assertRaises(ToolError):
            self.sb.read_file("sub/../../etc/passwd")

    def test_nonexistent_file_raises(self):
        with self.assertRaises(ToolError):
            self.sb.read_file("nope.txt")

    def test_list_dir_root(self):
        listing = self.sb.list_dir(".")
        self.assertIn("hello.txt", listing)
        self.assertIn("sub/", listing)

    def test_list_dir_not_a_dir(self):
        with self.assertRaises(ToolError):
            self.sb.list_dir("hello.txt")

    def test_empty_dir_returns_marker(self):
        Path(self.tmp, "empty").mkdir()
        result = self.sb.list_dir("empty")
        self.assertEqual(result, "(ว่าง)")


class SandboxCommandAllowlistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sb = Sandbox(self.tmp)

    def test_allowed_command_runs(self):
        result = self.sb.run_command("echo hello")
        self.assertIn("hello", result)
        self.assertIn("exit 0", result)

    def test_disallowed_command_rejected(self):
        with self.assertRaises(ToolError):
            self.sb.run_command("rm -rf /")

    def test_full_path_bypass_rejected(self):
        with self.assertRaises(ToolError):
            self.sb.run_command("/usr/bin/rm foo")

    def test_empty_command_rejected(self):
        with self.assertRaises(ToolError):
            self.sb.run_command("")

    def test_list_args_form(self):
        result = self.sb.run_command(["echo", "list", "form"])
        self.assertIn("list form", result)

    def test_pwd_runs_in_workspace(self):
        result = self.sb.run_command("pwd")
        self.assertIn(self.tmp, result)

    def test_custom_allowlist(self):
        sb2 = Sandbox(self.tmp, allowed_commands=("echo",))
        sb2.run_command("echo ok")
        with self.assertRaises(ToolError):
            sb2.run_command("ls")

    def test_default_allowed_commands_present(self):
        for cmd in ("ls", "cat", "grep", "git"):
            self.assertIn(cmd, DEFAULT_ALLOWED_COMMANDS)


class SandboxWriteFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sb = Sandbox(self.tmp)

    def test_write_new_file(self):
        result = self.sb.write_file("new.txt", "content")
        self.assertIn("new.txt", result)
        self.assertEqual(Path(self.tmp, "new.txt").read_text(encoding="utf-8"), "content")

    def test_write_creates_parent_dirs(self):
        self.sb.write_file("a/b/c.txt", "deep")
        self.assertTrue(Path(self.tmp, "a", "b", "c.txt").exists())

    def test_write_root_rejected(self):
        with self.assertRaises(ToolError):
            self.sb.write_file(".", "nope")

    def test_write_outside_workspace_rejected(self):
        with self.assertRaises(ToolError):
            self.sb.write_file("../../evil.txt", "pwned")

    def test_write_none_content(self):
        self.sb.write_file("empty.txt", None)
        self.assertEqual(Path(self.tmp, "empty.txt").read_text(encoding="utf-8"), "")


class SSRFGuardTest(unittest.TestCase):
    def test_rejects_non_http_scheme(self):
        with self.assertRaises(ToolError):
            _assert_public_url("ftp://example.com/file")

    def test_rejects_no_host(self):
        with self.assertRaises(ToolError):
            _assert_public_url("http:///path")

    def test_rejects_loopback(self):
        with self.assertRaises(ToolError):
            _assert_public_url("http://127.0.0.1/secret")

    def test_rejects_private_ip(self):
        with self.assertRaises(ToolError):
            _assert_public_url("http://10.0.0.1/internal")

    def test_rejects_link_local(self):
        with self.assertRaises(ToolError):
            _assert_public_url("http://169.254.169.254/latest/meta-data/")

    def test_rejects_localhost(self):
        with self.assertRaises(ToolError):
            _assert_public_url("http://localhost:8080/admin")

    @patch("socket.getaddrinfo", side_effect=OSError("resolve fail"))
    def test_unresolvable_host_rejected(self, _mock):
        with self.assertRaises(ToolError):
            _assert_public_url("http://nonexistent.invalid/")


class BuildRegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sb = Sandbox(self.tmp)
        Path(self.tmp, "data.txt").write_text("hello", encoding="utf-8")

    def test_basic_registry_has_3_tools(self):
        reg = build_registry(self.sb)
        self.assertIn("read_file", reg)
        self.assertIn("list_dir", reg)
        self.assertIn("run_command", reg)
        self.assertEqual(len(reg), 3)

    def test_read_file_via_registry(self):
        reg = build_registry(self.sb)
        result = reg["read_file"]({"path": "data.txt"})
        self.assertIn("hello", result)

    def test_net_ctx_adds_http_get(self):
        reg = build_registry(self.sb, net_ctx={"project_root": self.tmp})
        self.assertIn("http_get", reg)
        self.assertIn("call_connection", reg)

    def test_no_net_ctx_no_http_tools(self):
        reg = build_registry(self.sb)
        self.assertNotIn("http_get", reg)
        self.assertNotIn("call_connection", reg)


if __name__ == "__main__":
    unittest.main()
