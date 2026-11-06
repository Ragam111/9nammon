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

    def test_localhost_needs_no_token(self):
        cfg = server.resolve_server_config(_args(host="127.0.0.1"), env={})
        self.assertIsNone(cfg["token"])


class ResolveServerConfigExtraTest(unittest.TestCase):
    def test_returns_dict(self):
        cfg = server.resolve_server_config(_args(), env={})
        self.assertIsInstance(cfg, dict)

    def test_has_host_key(self):
        cfg = server.resolve_server_config(_args(), env={})
        self.assertIn("host", cfg)

    def test_has_port_key(self):
        cfg = server.resolve_server_config(_args(), env={})
        self.assertIn("port", cfg)

    def test_port_is_int(self):
        cfg = server.resolve_server_config(_args(), env={})
        self.assertIsInstance(cfg["port"], int)

    def test_localhost_with_token_allowed(self):
        cfg = server.resolve_server_config(_args(token="tok"), env={})
        self.assertEqual(cfg["token"], "tok")

    def test_env_port_overrides_default_when_cli_is_default(self):
        cfg = server.resolve_server_config(
            _args(host="0.0.0.0", token="x"), env={"PORT": "9876"})
        self.assertEqual(cfg["port"], 9876)


if __name__ == "__main__":
    unittest.main()
