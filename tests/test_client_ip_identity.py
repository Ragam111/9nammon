"""
test_client_ip_identity.py — real client IP behind a trusted proxy + rate limit per identity

Acceptance (shift 2, task 1):
  1) loopback peer + LCA_TRUST_PROXY=1 + two different CF-Connecting-IP = two buckets
  2) non-loopback peer with forged XFF = peer IP used
  3) LCA_TRUST_PROXY unset = old behaviour (peer IP)
  4) two API keys from one IP get separate buckets
"""

import http.client
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import org_store  # noqa: E402


class ResolveClientIpTest(unittest.TestCase):
    def test_loopback_trusted_uses_cf_header(self):
        ip = server.resolve_client_ip("127.0.0.1", {"CF-Connecting-IP": "203.0.113.5"}, trust=True)
        self.assertEqual(ip, "203.0.113.5")

    def test_loopback_trusted_falls_back_to_first_xff(self):
        ip = server.resolve_client_ip(
            "::1", {"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}, trust=True)
        self.assertEqual(ip, "198.51.100.7")

    def test_non_loopback_peer_ignores_forged_headers(self):
        hdrs = {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"}
        self.assertEqual(server.resolve_client_ip("192.168.1.20", hdrs, trust=True), "192.168.1.20")

    def test_untrusted_ignores_headers(self):
        hdrs = {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"}
        self.assertEqual(server.resolve_client_ip("127.0.0.1", hdrs, trust=False), "127.0.0.1")

    def test_garbage_header_falls_back_to_peer(self):
        hdrs = {"CF-Connecting-IP": "not-an-ip", "X-Forwarded-For": "<script>"}
        self.assertEqual(server.resolve_client_ip("127.0.0.1", hdrs, trust=True), "127.0.0.1")

    def test_trust_reads_env(self):
        hdrs = {"CF-Connecting-IP": "203.0.113.9"}
        with mock.patch.dict(os.environ, {"LCA_TRUST_PROXY": "1"}):
            self.assertEqual(server.resolve_client_ip("127.0.0.1", hdrs), "203.0.113.9")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LCA_TRUST_PROXY", None)
            self.assertEqual(server.resolve_client_ip("127.0.0.1", hdrs), "127.0.0.1")


class _ServerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        handler = server.make_handler(self.root, None, rate_limit_max=1, rate_limit_window=60)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status


class TrustedProxyHttpTest(_ServerCase):
    def test_trusted_proxy_two_cf_ips_two_buckets(self):
        with mock.patch.dict(os.environ, {"LCA_TRUST_PROXY": "1"}):
            self.assertEqual(self._get("/api/health", {"CF-Connecting-IP": "203.0.113.1"}), 200)
            self.assertEqual(self._get("/api/health", {"CF-Connecting-IP": "203.0.113.2"}), 200)
            self.assertEqual(self._get("/api/health", {"CF-Connecting-IP": "203.0.113.1"}), 429)

    def test_untrusted_cf_header_shares_peer_bucket(self):
        os.environ.pop("LCA_TRUST_PROXY", None)
        self.assertEqual(self._get("/api/health", {"CF-Connecting-IP": "203.0.113.1"}), 200)
        self.assertEqual(self._get("/api/health", {"CF-Connecting-IP": "203.0.113.2"}), 429)


class PerKeyBucketHttpTest(_ServerCase):
    def test_two_api_keys_from_one_ip_separate_buckets(self):
        org_store.create_user(self.root, "boss", "password123", "CEO")
        org_store.create_user(self.root, "u1", "password123", "USER", created_by_role="CEO")
        k1 = org_store.create_api_key(self.root, "u1", "free", "CEO")["key"]
        k2 = org_store.create_api_key(self.root, "u1", "free", "CEO")["key"]
        self.assertEqual(self._get("/api/health", {"X-API-Key": k1}), 200)
        self.assertEqual(self._get("/api/health", {"X-API-Key": k2}), 200)
        self.assertEqual(self._get("/api/health", {"X-API-Key": k1}), 429)
        # anonymous still per IP (its own bucket)
        self.assertEqual(self._get("/api/health"), 200)
        self.assertEqual(self._get("/api/health"), 429)


if __name__ == "__main__":
    unittest.main()
