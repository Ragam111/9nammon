"""เปิดเซิร์ฟเวอร์ซ้ำบนพอร์ตที่มีคนฟังอยู่ต้องล้ม (กันเซิร์ฟเวอร์ซ้อนบน Windows)"""
import socket
import sys
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server


class ExclusiveBindTest(unittest.TestCase):
    def test_second_server_on_busy_port_raises(self):
        first = server.ExclusiveHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            port = first.server_address[1]
            with self.assertRaises(OSError):
                second = server.ExclusiveHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
                second.server_close()
        finally:
            first.server_close()

    def test_wildcard_and_loopback_cannot_share_a_port(self):
        # the real incident: one server on 0.0.0.0:8420 and another on 127.0.0.1:8420
        first = server.ExclusiveHTTPServer(("0.0.0.0", 0), BaseHTTPRequestHandler)
        try:
            port = first.server_address[1]
            with self.assertRaises(OSError):
                second = server.ExclusiveHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
                second.server_close()
        finally:
            first.server_close()

    def test_port_is_reusable_after_close(self):
        a = server.ExclusiveHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        port = a.server_address[1]
        a.server_close()
        b = server.ExclusiveHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
        b.server_close()


if __name__ == "__main__":
    unittest.main()
