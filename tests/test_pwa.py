"""
test_pwa.py — PWA: manifest, service worker, icons, offline page.

Starts a real server on a random port (no Ollama needed) and checks that the
PWA files are public, carry the right headers, and never cache private data.
"""

import http.client
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402

APP = ROOT / "app"
PWA_ROUTES = {
    "/manifest.webmanifest": "application/manifest+json",
    "/sw.js": "application/javascript",
    "/offline.html": "text/html",
    "/icons/icon-192.png": "image/png",
    "/icons/icon-512.png": "image/png",
    "/icons/icon-maskable-512.png": "image/png",
    "/icons/apple-touch-icon.png": "image/png",
}
MAIN_PAGES = ("chat.html", "login.html", "index.html", "support.html",
              "spaces.html", "models.html", "plans.html", "console-keys.html")


def png_size(data: bytes) -> tuple:
    """Return (width, height) of a PNG after validating signature, IHDR and CRCs."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("bad PNG signature")
    pos, w, h, seen_end, idat = 8, None, None, False, b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        if zlib.crc32(ctype + chunk) & 0xFFFFFFFF != crc:
            raise ValueError(f"bad CRC in {ctype!r}")
        if ctype == b"IHDR":
            w, h = struct.unpack(">II", chunk[:8])
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            seen_end = True
        pos += 12 + length
    if w is None or not seen_end:
        raise ValueError("missing IHDR/IEND")
    zlib.decompress(idat)  # must be a valid zlib stream
    return w, h


class _ServerMixin:
    master_token = "pwa-test-master-token"

    def _start(self, token):
        self._tmp = tempfile.TemporaryDirectory()
        handler = server.make_handler(Path(self._tmp.name), token)
        self.handler = handler
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path):
        # No auth header on purpose: PWA files must be public.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, headers, body


class PwaRoutesTest(_ServerMixin, unittest.TestCase):
    def setUp(self):
        # Master token set -> every /api call needs auth; static PWA files must not.
        self._start(self.master_token)

    def test_routes_public_with_content_types(self):
        for path, ctype in PWA_ROUTES.items():
            st, hdr, body = self._get(path)
            self.assertEqual(st, 200, f"{path} -> {st}")
            self.assertIn(ctype, hdr.get("content-type", ""), path)
            self.assertTrue(body, f"{path} empty")
            self.assertNotIn(self.master_token.encode(), body, f"{path} leaks token")

    def test_sw_headers(self):
        st, hdr, _ = self._get("/sw.js")
        self.assertEqual(st, 200)
        self.assertEqual(hdr.get("service-worker-allowed"), "/")
        self.assertIn("no-cache", hdr.get("cache-control", ""))

    def test_api_still_needs_auth(self):
        st, _, _ = self._get("/api/me")
        self.assertIn(st, (401, 403))


class PwaNoTokenLeakTest(_ServerMixin, unittest.TestCase):
    def setUp(self):
        # Auto session token: HTML pages get it injected on loopback hosts.
        self._start(None)

    def test_offline_and_sw_never_carry_session_token(self):
        tok = self.handler.session_token.encode()
        for path in PWA_ROUTES:
            st, _, body = self._get(path)
            self.assertEqual(st, 200, path)
            self.assertNotIn(tok, body, f"{path} leaks session token")
            self.assertNotIn(b"__LCA_SESSION_TOKEN", body, path)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.m = json.loads((APP / "manifest.webmanifest").read_text(encoding="utf-8"))

    def test_required_fields(self):
        m = self.m
        self.assertEqual(m["name"], "LCA Local AI")
        self.assertEqual(m["short_name"], "LCA")
        self.assertEqual(m["start_url"], "/chat")
        self.assertEqual(m["scope"], "/")
        self.assertEqual(m["display"], "standalone")
        css = (APP / "app.css").read_text(encoding="utf-8")
        for key in ("theme_color", "background_color"):
            self.assertRegex(m[key], r"^#[0-9a-fA-F]{6}$")
            self.assertIn(m[key].lower(), css.lower(), f"{key} not from app.css")

    def test_icons_exist_and_match_size(self):
        sizes, maskable = set(), False
        for icon in self.m["icons"]:
            self.assertEqual(icon["type"], "image/png")
            rel = icon["src"].lstrip("/")
            data = (APP / rel).read_bytes()
            w, h = png_size(data)
            declared = icon["sizes"]
            self.assertEqual(f"{w}x{h}", declared, icon["src"])
            sizes.add(declared)
            if "maskable" in icon.get("purpose", ""):
                maskable = True
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)
        self.assertTrue(maskable, "need a maskable icon")

    def test_apple_touch_icon_valid(self):
        w, h = png_size((APP / "icons" / "apple-touch-icon.png").read_bytes())
        self.assertEqual((w, h), (180, 180))


class ServiceWorkerSourceTest(unittest.TestCase):
    def setUp(self):
        self.src = (APP / "sw.js").read_text(encoding="utf-8")

    def test_versioned_cache_and_cleanup(self):
        self.assertRegex(self.src, r"CACHE_NAME\s*=\s*['\"]lca-shell-v\d+")
        self.assertIn("activate", self.src)
        self.assertIn("caches.delete", self.src)

    def test_precache_list_is_static_only(self):
        m = re.search(r"SHELL_ASSETS\s*=\s*\[(.*?)\]", self.src, re.S)
        self.assertIsNotNone(m)
        assets = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
        for want in ("/app.css", "/app.js", "/chat.js", "/highlight.js",
                     "/qr.js", "/offline.html", "/icons/icon-192.png"):
            self.assertIn(want, assets)
        for a in assets:
            self.assertFalse(a.startswith(("/api", "/v1", "/auth")), a)
            # HTML pages carry the session token -> never precached (except offline)
            self.assertFalse(a.endswith(".html") and a != "/offline.html", a)
            self.assertNotIn(a, ("/", "/chat", "/login", "/console", "/dev"))

    def test_exclusion_logic_present(self):
        for needle in ('"/api/"', '"/v1/"', '"/auth/"', '"authorization"',
                       '"x-auth-token"', '"GET"', "/offline.html", "navigate"):
            self.assertIn(needle, self.src, needle)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ServiceWorkerPolicyNodeTest(unittest.TestCase):
    """Run the real sw.js policy function in node with stub globals."""

    def _policy(self, cases):
        harness = r"""
const fs = require('fs'); const vm = require('vm');
const ctx = { self: { addEventListener(){}, skipWaiting(){}, clients: {} },
  caches: {}, fetch(){}, URL, Response: function(){}, console };
ctx.self.location = { origin: 'http://127.0.0.1:9431' };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const p = ctx.self.__lcaSwPolicy;
const cases = JSON.parse(process.argv[2]);
const out = cases.map(c => p({ method: c.method, url: c.url, mode: c.mode || 'cors',
  headers: { has: (k) => (c.headers || []).includes(k.toLowerCase()) } }));
process.stdout.write(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", harness, str(APP / "sw.js"), json.dumps(cases)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_policy(self):
        o = "http://127.0.0.1:9431"
        cases = [
            ({"method": "GET", "url": o + "/app.css"}, "cache"),
            ({"method": "GET", "url": o + "/chat.js"}, "cache"),
            ({"method": "GET", "url": o + "/icons/icon-512.png"}, "cache"),
            ({"method": "GET", "url": o + "/api/me"}, "bypass"),
            ({"method": "GET", "url": o + "/api/chats?x=1"}, "bypass"),
            ({"method": "GET", "url": o + "/v1/models"}, "bypass"),
            ({"method": "GET", "url": o + "/auth/google"}, "bypass"),
            ({"method": "POST", "url": o + "/app.css"}, "bypass"),
            ({"method": "GET", "url": o + "/app.css", "headers": ["authorization"]}, "bypass"),
            ({"method": "GET", "url": o + "/app.css", "headers": ["x-auth-token"]}, "bypass"),
            ({"method": "GET", "url": "https://cdn.example.com/app.css"}, "bypass"),
            ({"method": "GET", "url": o + "/chat", "mode": "navigate"}, "navigate"),
            ({"method": "GET", "url": o + "/console", "mode": "navigate"}, "navigate"),
            ({"method": "GET", "url": o + "/rea-data.js"}, "bypass"),
        ]
        got = self._policy([c for c, _ in cases])
        for (c, want), g in zip(cases, got):
            self.assertEqual(g, want, c)


class OfflinePageTest(unittest.TestCase):
    def test_no_external_resources(self):
        html = (APP / "offline.html").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(src|href)\s*=\s*['\"]?(https?:)?//", html, re.I))
        self.assertNotIn("<script src", html.lower())
        self.assertNotIn("@import", html)
        self.assertNotIn("url(", html)
        self.assertIn("ออฟไลน์", html)
        self.assertIn("Ollama", html)


class PagesLinkManifestTest(unittest.TestCase):
    def test_main_pages_have_pwa_head(self):
        for name in MAIN_PAGES:
            html = (APP / name).read_text(encoding="utf-8")
            self.assertIn('rel="manifest" href="/manifest.webmanifest"', html, name)
            self.assertIn('name="theme-color"', html, name)
            self.assertIn('rel="apple-touch-icon"', html, name)

    def test_app_js_registers_sw_safely(self):
        js = (APP / "app.js").read_text(encoding="utf-8")
        self.assertIn('serviceWorker', js)
        self.assertIn('register("/sw.js"', js)
        self.assertIn("isSecureContext", js)
        self.assertIn("127.0.0.1", js)
        self.assertIn(".catch(", js)


if __name__ == "__main__":
    unittest.main()
