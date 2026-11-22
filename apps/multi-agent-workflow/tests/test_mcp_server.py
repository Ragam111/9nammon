"""Read-only MCP server tests. Denied, outside and binary paths must be refused in every form."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from mawf.files import FileSandbox
from mawf.mcp_server import MAX_LINE_BYTES, McpServer

APP_DIR = Path(__file__).resolve().parent.parent


def init(version: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}}


class McpServerTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "lca"
        self.root.mkdir()
        self.outside = self.base / "outside.md"
        self.outside.write_text("outside", encoding="utf-8")
        self.server = McpServer(FileSandbox(self.root))

    def write(self, rel: str, data: str | bytes) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")

    def send(self, message: dict[str, Any]) -> dict[str, Any] | None:
        return self.server.handle_message(json.dumps(message))

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        reply = self.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}})
        assert reply is not None and "result" in reply, reply
        return reply["result"]

    def payload(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.call(name, arguments)
        self.assertFalse(result["isError"], result)
        return json.loads(result["content"][0]["text"])

    def assert_refused(self, name: str, arguments: dict[str, Any], reason: str | None = None) -> None:
        result = self.call(name, arguments)
        self.assertTrue(result["isError"], arguments)
        if reason is not None:
            self.assertEqual(result["content"][0]["text"], reason)

    def test_supported_version_is_echoed(self) -> None:
        result = self.send(init("2025-03-26"))["result"]  # type: ignore[index]
        self.assertEqual(result["protocolVersion"], "2025-03-26")
        self.assertEqual(result["capabilities"], {"tools": {}})
        self.assertEqual(result["serverInfo"], {"name": "mawf-lca-files", "version": "0.1.0"})

    def test_unsupported_version_gets_newest_supported(self) -> None:
        reply = self.send(init("1999-01-01"))
        assert reply is not None
        self.assertEqual(reply["result"]["protocolVersion"], "2025-06-18")

    def test_notifications_get_no_reply(self) -> None:
        self.assertIsNone(self.send({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(self.send({"jsonrpc": "2.0", "method": "notifications/unknown"}))

    def test_ping_returns_empty_result(self) -> None:
        reply = self.send({"jsonrpc": "2.0", "id": 5, "method": "ping"})
        self.assertEqual(reply, {"jsonrpc": "2.0", "id": 5, "result": {}})

    def test_tools_list_is_exactly_two_tools(self) -> None:
        reply = self.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert reply is not None
        tools = reply["result"]["tools"]
        self.assertEqual(sorted(t["name"] for t in tools), ["list_dir", "read_file"])
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIn("description", tool)

    def test_reads_allowed_markdown(self) -> None:
        self.write("notes.md", "hello สวัสดี")
        data = self.payload("read_file", {"path": "notes.md"})
        self.assertEqual(data, {"path": "notes.md", "text": "hello สวัสดี", "truncated": False})

    def test_truncates_to_max_bytes(self) -> None:
        self.write("big.txt", "a" * 300)
        data = self.payload("read_file", {"path": "big.txt", "max_bytes": 100})
        self.assertEqual(len(data["text"]), 100)
        self.assertTrue(data["truncated"])

    def test_truncation_never_splits_a_utf8_character(self) -> None:
        self.write("thai.txt", "ก" * 10)  # 3 bytes each
        data = self.payload("read_file", {"path": "thai.txt", "max_bytes": 4})
        self.assertEqual(data["text"], "ก")
        self.assertTrue(data["truncated"])

    def test_denied_names_are_refused(self) -> None:
        for name in ["config.json", "org.json", "a.db", "x.db-wal", ".env", "my_secret.md", "api_key.txt", "token.log"]:
            self.write(name, "value")
            self.assert_refused("read_file", {"path": name}, "denied")

    def test_alternate_data_stream_cannot_hide_a_denied_name(self) -> None:
        # NTFS "name:stream" used to pass the denylist because only the whole segment was compared.
        self.write("config.json", "{}")
        self.write("sample.db", "x")
        self.write("notes.md", "plain")
        for base in ["config.json", "sample.db", "notes.md"]:
            try:
                with open(self.root / f"{base}:x.txt", "w", encoding="utf-8") as handle:
                    handle.write("MARKER-ADS")
            except OSError:
                self.skipTest("this file system does not allow alternate data streams")
        for path in ["config.json:x.txt", "CONFIG.JSON:x.md", "sample.db:x.txt",
                     "notes.md:x.txt", "config.json::$DATA", "sub/config.json:x.txt"]:
            self.assert_refused("read_file", {"path": path}, "denied")
        self.assert_refused("list_dir", {"path": "config.json:x.txt"}, "denied")

    def test_list_dir_hides_denied_entries(self) -> None:
        for name in ["notes.md", "config.json", "a.db", ".env", "my_secret.md"]:
            self.write(name, "x")
        self.write("LocalCodeAssistant/data.json", "{}")
        data = self.payload("list_dir", {"path": ""})
        self.assertEqual([e["name"] for e in data["entries"]], ["notes.md"])
        self.assertEqual(data["entries"][0], {"name": "notes.md", "type": "file", "size": 1})
        self.assert_refused("list_dir", {"path": "LocalCodeAssistant"}, "denied")
        self.assert_refused("read_file", {"path": "LocalCodeAssistant/data.json"}, "denied")

    def test_parent_absolute_and_drive_paths_are_refused(self) -> None:
        for path in ["../outside.md", "sub/../../outside.md", str(self.outside), "C:/outside.md", "/outside.md"]:
            self.assert_refused("read_file", {"path": path})

    def test_symlink_pointing_outside_is_refused(self) -> None:
        try:
            os.symlink(self.outside, self.root / "link.md")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks need extra rights on this machine")
        self.assert_refused("read_file", {"path": "link.md"})
        self.assertEqual(self.payload("list_dir", {"path": ""})["entries"], [])

    def test_directory_link_pointing_outside_is_refused(self) -> None:
        # A directory junction on Windows needs no privilege, so it is tried when symlinks are refused.
        outside_dir = self.base / "outside_dir"
        outside_dir.mkdir()
        (outside_dir / "plain-outside.md").write_text("outside", encoding="utf-8")
        link = self.root / "link_out"
        try:
            os.symlink(outside_dir, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                self.skipTest("symlinks need extra rights on this machine")
            done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside_dir)],
                                  capture_output=True)
            if done.returncode != 0 or not link.exists():
                self.skipTest("cannot create a directory link on this machine")
        self.assert_refused("read_file", {"path": "link_out/plain-outside.md"}, "invalid path or outside root")
        self.assert_refused("list_dir", {"path": "link_out"}, "invalid path or outside root")
        names = [entry["name"] for entry in self.payload("list_dir", {"path": ""})["entries"]]
        self.assertNotIn("link_out", names)

    def test_hard_link_to_outside_file_is_refused(self) -> None:
        # A hard link aliases the outside file's bytes under an allowed name; the path check alone cannot see it.
        secret = self.base / "outside-secret.txt"
        secret.write_text("MARKER-HARDLINK", encoding="utf-8")
        try:
            os.link(secret, self.root / "innocent.txt")
        except (OSError, NotImplementedError):
            self.skipTest("hard links are not available on this file system")
        self.assert_refused("read_file", {"path": "innocent.txt"}, "denied")
        names = [entry["name"] for entry in self.payload("list_dir", {"path": ""})["entries"]]
        self.assertNotIn("innocent.txt", names)

    def test_hard_link_to_denied_file_is_refused(self) -> None:
        self.write("config.json", '{"key": "value"}')
        try:
            os.link(self.root / "config.json", self.root / "readme.md")
        except (OSError, NotImplementedError):
            self.skipTest("hard links are not available on this file system")
        self.assert_refused("read_file", {"path": "readme.md"}, "denied")

    def test_binary_file_is_refused(self) -> None:
        self.write("data.txt", b"abc\x00def")
        self.assert_refused("read_file", {"path": "data.txt"}, "binary file refused")

    def test_extension_outside_allowlist_is_refused(self) -> None:
        self.write("script.py", "print(1)")
        self.assert_refused("read_file", {"path": "script.py"}, "extension not allowed")

    def test_missing_file_is_a_tool_error(self) -> None:
        self.assert_refused("read_file", {"path": "nope.md"}, "not found")

    def test_unknown_method_is_32601(self) -> None:
        reply = self.send({"jsonrpc": "2.0", "id": 9, "method": "resources/list"})
        self.assertEqual(reply["error"]["code"], -32601)  # type: ignore[index]
        self.assertEqual(reply["id"], 9)  # type: ignore[index]

    def test_malformed_json_is_32700(self) -> None:
        reply = self.server.handle_message("{not json")
        assert reply is not None
        self.assertEqual(reply["error"]["code"], -32700)
        self.assertIsNone(reply["id"])

    def test_invalid_request_shape_is_32600(self) -> None:
        reply = self.server.handle_message("[1, 2]")
        assert reply is not None
        self.assertEqual(reply["error"]["code"], -32600)

    def test_oversized_line_is_refused_before_parsing(self) -> None:
        reply = self.server.handle_message("x" * (MAX_LINE_BYTES + 1))
        assert reply is not None
        self.assertEqual(reply["error"]["code"], -32600)
        self.assertIsNone(reply["id"])

    def test_missing_required_param_is_32602(self) -> None:
        reply = self.send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                           "params": {"name": "read_file", "arguments": {}}})
        assert reply is not None
        self.assertEqual(reply["error"]["code"], -32602)

    def test_bad_max_bytes_is_32602(self) -> None:
        self.write("notes.md", "x")
        for value in (0, 200_001, True, "10"):
            reply = self.send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                               "params": {"name": "read_file", "arguments": {"path": "notes.md", "max_bytes": value}}})
            assert reply is not None
            self.assertEqual(reply["error"]["code"], -32602, value)

    def test_unknown_tool_is_a_tool_error_not_rpc_error(self) -> None:
        self.assert_refused("write_file", {"path": "x.md"}, "unknown tool")

    def test_subprocess_answers_two_lines_on_stdout(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(APP_DIR)
        stdin = "\n".join([
            json.dumps(init("2025-06-18")),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]) + "\n"
        proc = subprocess.run(
            [sys.executable, "-m", "mawf.mcp_server", "--root", str(self.root)],
            input=stdin.encode("utf-8"), capture_output=True, cwd=str(APP_DIR), env=env, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        lines = proc.stdout.decode("utf-8").splitlines()
        self.assertEqual(len(lines), 2, lines)
        first, second = json.loads(lines[0]), json.loads(lines[1])
        self.assertEqual(first["id"], 1)
        self.assertEqual(second["id"], 2)
        self.assertEqual(len(second["result"]["tools"]), 2)


if __name__ == "__main__":
    unittest.main()
