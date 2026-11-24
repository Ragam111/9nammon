"""test_server_config.py — เทส resolve_server_config: args + env → config สุดท้าย

ครอบคลุม deploy บน cloud: อ่าน $PORT/$LCA_HOST/$LCA_TOKEN + คงกฎความปลอดภัย
(bind ออกนอก localhost โดยไม่มี token = ปฏิเสธ — Rule 12)
"""

import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


def _args(host="127.0.0.1", port=8420, token=None):
    return argparse.Namespace(host=host, port=port, token=token)


class ResolveServerConfigTest(unittest.TestCase):
    def test_defaults_localhost(self):
        cfg = server.resolve_server_config(_args(), env={})
        self.assertEqual(cfg, {"host": "127.0.0.1", "port": 8420, "token": None})

    def test_env_port_read_when_not_overridden(self):
        # cloud ฉีด $PORT — ต้องอ่าน (ค่า --port ยัง default)
        cfg = server.resolve_server_config(
            _args(host="0.0.0.0", token="x"), env={"PORT": "10000"})
        self.assertEqual(cfg["port"], 10000)

    def test_cli_port_wins_over_env(self):
        cfg = server.resolve_server_config(
            _args(host="0.0.0.0", port=9999, token="x"), env={"PORT": "10000"})
        self.assertEqual(cfg["port"], 9999)

    def test_env_host_and_token(self):
        cfg = server.resolve_server_config(
            _args(), env={"LCA_HOST": "0.0.0.0", "LCA_TOKEN": "secret"})
        self.assertEqual(cfg["host"], "0.0.0.0")
        self.assertEqual(cfg["token"], "secret")

    def test_cli_token_wins_over_env(self):
        cfg = server.resolve_server_config(
            _args(host="0.0.0.0", token="cli"), env={"LCA_TOKEN": "env"})
        self.assertEqual(cfg["token"], "cli")

    def test_bind_public_without_token_rejected(self):
        # Rule 12: bind ออกนอก 127.0.0.1 โดยไม่มี token = ValueError
        with self.assertRaises(ValueError):
            server.resolve_server_config(_args(host="0.0.0.0"), env={})

    def test_env_host_public_without_token_rejected(self):
        with self.assertRaises(ValueError):
            server.resolve_server_config(_args(), env={"LCA_HOST": "0.0.0.0"})

    def test_bad_port_env_raises(self):
        with self.assertRaises(ValueError):
            server.resolve_server_config(
                _args(host="0.0.0.0", token="x"), env={"PORT": "not-a-number"})

    def test_port_out_of_range_rejected(self):
        for bad in (65536, 99999, -1):
            with self.subTest(port=bad), self.assertRaises(ValueError):
                server.resolve_server_config(_args(port=bad), env={})

    def test_env_port_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            server.resolve_server_config(
                _args(host="0.0.0.0", token="x"), env={"PORT": "70000"})

    def test_port_boundaries_accepted(self):
        for ok in (0, 65535):
            with self.subTest(port=ok):
                cfg = server.resolve_server_config(_args(port=ok), env={})
                self.assertEqual(cfg["port"], ok)

    def test_main_exits_cleanly_on_bad_port(self):
        # ต้องไม่มี traceback — แค่ข้อความ + exit code ไม่เป็น 0
        import io
        import contextlib
        from unittest import mock
        project = Path(__file__).resolve().parent
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["server.py", str(project), "--port", "99999"]), \
                mock.patch.dict("os.environ", {}, clear=False), \
                contextlib.redirect_stdout(out), \
                self.assertRaises(SystemExit) as cm:
            server.main()
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("0-65535", out.getvalue())

    def test_localhost_needs_no_token(self):
        cfg = server.resolve_server_config(_args(host="127.0.0.1"), env={})
        self.assertIsNone(cfg["token"])


if __name__ == "__main__":
    unittest.main()
