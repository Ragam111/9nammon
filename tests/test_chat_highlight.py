"""Chat code highlight + attach: static route of /highlight.js and the node suite.

Starts the real server on a random port (no Ollama needed) to check the route.
"""

import http.client
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class HighlightRouteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        handler = server.make_handler(Path(self._tmp.name), None)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _get(self, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, headers, body

    def test_highlight_js_route(self):
        self.assertIn("/highlight.js", server.STATIC_ROUTES)
        status, headers, body = self._get("/highlight.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get("content-type", ""))
        self.assertIsNotNone(headers.get("cache-control"))
        self.assertIn(b"LCAHighlight", body)

    def test_chat_page_loads_highlight_and_attach(self):
        status, _, body = self._get("/chat")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('src="/highlight.js"', html)
        self.assertLess(html.index('src="/highlight.js"'), html.index('src="/chat.js"'))
        self.assertIn('id="attach-btn"', html)
        self.assertIn('id="attach-file"', html)
        self.assertIn('id="attach-chips"', html)

    def test_no_cdn_in_highlighter(self):
        src = (ROOT / "app" / "highlight.js").read_text(encoding="utf-8")
        for banned in ("http://", "https://", "cdn", "unpkg", "innerHTML"):
            self.assertNotIn(banned, src)


class HighlightNodeSuiteTest(unittest.TestCase):
    def test_node_suite(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        proc = subprocess.run(
            [node, "--test", str(ROOT / "tests" / "highlight.test.mjs")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
