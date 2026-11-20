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

    def test_result_is_dict(self):
        cfg = server.resolve_server_config(_args(), env={})
        self.assertIsInstance(cfg, dict)

    def test_result_has_three_keys(self):
        cfg = server.resolve_server_config(_args(), env={})
        for key in ("host", "port", "token"):
            self.assertIn(key, cfg)

    def test_port_in_result_is_int(self):
        cfg = server.resolve_server_config(_args(host="0.0.0.0", token="x"), env={"PORT": "9876"})
        self.assertIsInstance(cfg["port"], int)

    def test_token_in_result_is_string_when_set(self):
        cfg = server.resolve_server_config(_args(host="0.0.0.0", token="mytoken"), env={})
        self.assertIsInstance(cfg["token"], str)

    def test_env_token_alone_still_requires_public_host(self):
        # LCA_TOKEN set but host is still localhost — rule 12 does not apply
        cfg = server.resolve_server_config(_args(), env={"LCA_TOKEN": "env-only"})
        self.assertEqual(cfg["host"], "127.0.0.1")
        self.assertEqual(cfg["token"], "env-only")

    def test_zero_port_accepted(self):
        # port=0 → OS chooses free port; resolve_server_config should not reject it
        cfg = server.resolve_server_config(_args(host="0.0.0.0", port=0, token="x"), env={})
        self.assertEqual(cfg["port"], 0)


if __name__ == "__main__":
    unittest.main()
