"""test_auth_backend.py — auth backend: master token, API key, local CEO, static tokens"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth_backend  # noqa: E402


class LocalAuthMasterTokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.backend = auth_backend.LocalAuthBackend(self.tmp, master_token="secret-master")

    def test_master_token_returns_ceo(self):
        result = self.backend.authenticate("secret-master")
        self.assertEqual(result["role"], "CEO")
        self.assertEqual(result["source"], "master_token")

    def test_wrong_token_returns_none(self):
        result = self.backend.authenticate("wrong-token")
        self.assertIsNone(result)

    def test_empty_token_no_ip_returns_none(self):
        result = self.backend.authenticate("", client_ip="192.168.1.100")
        self.assertIsNone(result)

    def test_none_token_no_ip_returns_none(self):
        result = self.backend.authenticate(None, client_ip="10.0.0.1")
        self.assertIsNone(result)

    def test_whitespace_token_treated_as_none(self):
        result = self.backend.authenticate("   ", client_ip="127.0.0.1")
        self.assertEqual(result["role"], "CEO")
        self.assertEqual(result["source"], "local")


class LocalAuthLocalCeoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.backend = auth_backend.LocalAuthBackend(self.tmp, master_token=None)

    def test_localhost_ipv4_no_token_is_ceo(self):
        result = self.backend.authenticate(None, client_ip="127.0.0.1")
        self.assertEqual(result["role"], "CEO")
        self.assertEqual(result["source"], "local")

    def test_localhost_ipv6_no_token_is_ceo(self):
        result = self.backend.authenticate(None, client_ip="::1")
        self.assertEqual(result["role"], "CEO")

    def test_localhost_name_no_token_is_ceo(self):
        result = self.backend.authenticate(None, client_ip="localhost")
        self.assertEqual(result["role"], "CEO")

    def test_remote_ip_no_token_returns_none(self):
        result = self.backend.authenticate(None, client_ip="203.0.113.50")
        self.assertIsNone(result)

    def test_no_master_token_skips_master_check(self):
        result = self.backend.authenticate("anything", client_ip="127.0.0.1")
        self.assertIsNone(result)


class StaticTokenBackendTest(unittest.TestCase):
    def test_valid_token_returns_role(self):
        b = auth_backend.StaticTokenBackend({"tok-a": "CEO", "tok-b": "USER"})
        r = b.authenticate("tok-a")
        self.assertEqual(r["role"], "CEO")
        self.assertEqual(r["source"], "static")

    def test_unknown_token_returns_none(self):
        b = auth_backend.StaticTokenBackend({"tok-a": "CEO"})
        self.assertIsNone(b.authenticate("unknown"))

    def test_invalid_role_filtered_out(self):
        b = auth_backend.StaticTokenBackend({"tok-bad": "SUPERUSER"})
        self.assertIsNone(b.authenticate("tok-bad"))

    def test_case_insensitive_role_validation(self):
        b = auth_backend.StaticTokenBackend({"tok": "admin"})
        r = b.authenticate("tok")
        self.assertEqual(r["role"], "ADMIN")

    def test_empty_tokens(self):
        b = auth_backend.StaticTokenBackend({})
        self.assertIsNone(b.authenticate("anything"))

    def test_none_tokens(self):
        b = auth_backend.StaticTokenBackend(None)
        self.assertIsNone(b.authenticate("anything"))

    def test_no_token_returns_none(self):
        b = auth_backend.StaticTokenBackend({"tok": "CEO"})
        self.assertIsNone(b.authenticate(None))


class GetAuthBackendTest(unittest.TestCase):
    def test_default_is_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = auth_backend.get_auth_backend(tmp, master_token="mt")
            self.assertIsInstance(b, auth_backend.LocalAuthBackend)

    def test_static_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"AUTH_BACKEND": "static", "STATIC_TOKENS": '{"t1":"CEO"}'}
            Path(tmp, "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            b = auth_backend.get_auth_backend(tmp)
            self.assertIsInstance(b, auth_backend.StaticTokenBackend)
            r = b.authenticate("t1")
            self.assertEqual(r["role"], "CEO")

    def test_static_with_bad_json_falls_back_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"AUTH_BACKEND": "static", "STATIC_TOKENS": "NOT JSON"}
            Path(tmp, "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            b = auth_backend.get_auth_backend(tmp)
            self.assertIsInstance(b, auth_backend.StaticTokenBackend)
            self.assertIsNone(b.authenticate("anything"))


class AuthenticateConvenienceTest(unittest.TestCase):
    def test_convenience_function_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = auth_backend.authenticate(tmp, None, client_ip="127.0.0.1")
            self.assertEqual(r["role"], "CEO")

    def test_convenience_function_rejects_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = auth_backend.authenticate(tmp, None, client_ip="8.8.8.8")
            self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
