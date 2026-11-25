"""/api/version ต้องอ่านไฟล์ VERSION ของโปรแกรม ไม่ใช่ของโฟลเดอร์ข้อมูลผู้ใช้"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server


class VersionEndpointTest(unittest.TestCase):
    def test_version_comes_from_program_version_file(self):
        expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        with tempfile.TemporaryDirectory() as data_dir:   # project folder without VERSION
            handler = server.make_handler(Path(data_dir), None)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
                c.request("GET", "/api/version", headers={"Host": f"127.0.0.1:{httpd.server_address[1]}"})
                body = json.loads(c.getresponse().read())
                c.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
        self.assertEqual(body["version"], expected)


if __name__ == "__main__":
    unittest.main()
