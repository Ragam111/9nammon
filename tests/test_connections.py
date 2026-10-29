"""test_connections.py — ทะเบียนต่อสมอง AI ภายนอก (CRUD + redaction + test + chat)

ไม่ต่อ endpoint จริง — monkeypatch _backend_for ให้คืน backend ปลอม (เช็ก logic ล้วน)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import connections  # noqa: E402
from app import model_backend  # noqa: E402


class _FakeBackend:
    def __init__(self, available=True, reply="pong"):
        self._available = available
        self._reply = reply
        self.last = None

    def is_available(self):
        return self._available

    def generate(self, model, messages, num_ctx=8192, options=None):
        self.last = {"model": model, "messages": messages, "options": options}
        return self._reply


class ConnectionsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_backend_for = connections._backend_for   # กู้คืนกัน test ปน

    def tearDown(self):
        connections._backend_for = self._orig_backend_for
        self._tmp.cleanup()

    def test_add_list_redacts_api_key(self):
        rec = connections.add(self.root, "Brain1", "openai",
                              base_url="https://api.x.com/v1", model="m", api_key="sk-secret")
        self.assertTrue(rec["id"].startswith("con-"))
        self.assertTrue(rec["api_key_set"])
        self.assertNotIn("api_key", rec)            # ไม่คืน key เต็ม
        listed = connections.list_connections(self.root)
        self.assertEqual(len(listed), 1)
        self.assertNotIn("api_key", listed[0])
        self.assertTrue(listed[0]["api_key_set"])
        # raw ภายในเท่านั้น ถึงจะเห็น key จริง
        raw = connections.get(self.root, rec["id"], raw=True)
        self.assertEqual(raw["api_key"], "sk-secret")

    def test_openai_requires_base_url(self):
        with self.assertRaises(connections.ConnectionError):
            connections.add(self.root, "NoBase", "openai")

    def test_bad_kind_rejected(self):
        with self.assertRaises(connections.ConnectionError):
            connections.add(self.root, "X", "telepathy")

    def test_duplicate_name_rejected(self):
        connections.add(self.root, "Dup", "ollama")
        with self.assertRaises(connections.ConnectionError):
            connections.add(self.root, "Dup", "ollama")

    def test_update_keeps_key_when_blank(self):
        rec = connections.add(self.root, "B", "openai", base_url="https://a/v1", api_key="sk-1")
        connections.update(self.root, rec["id"], {"model": "m2"})          # ไม่ส่ง api_key
        raw = connections.get(self.root, rec["id"], raw=True)
        self.assertEqual(raw["api_key"], "sk-1")                           # ของเดิมยังอยู่
        self.assertEqual(raw["model"], "m2")
        connections.update(self.root, rec["id"], {"api_key": "sk-2"})      # ส่งมา → เปลี่ยน
        self.assertEqual(connections.get(self.root, rec["id"], raw=True)["api_key"], "sk-2")

    def test_remove(self):
        rec = connections.add(self.root, "B", "ollama")
        self.assertTrue(connections.remove(self.root, rec["id"]))
        self.assertFalse(connections.remove(self.root, rec["id"]))
        self.assertEqual(connections.list_connections(self.root), [])

    def test_test_probe(self):
        rec = connections.add(self.root, "B", "ollama")
        connections._backend_for = lambda r: _FakeBackend(available=True)
        res = connections.test(self.root, rec["id"])
        self.assertTrue(res["available"])

    def test_chat_routes_to_backend(self):
        rec = connections.add(self.root, "B", "openai", base_url="https://a/v1", model="deflt")
        fake = _FakeBackend(reply="hello-from-brain")
        connections._backend_for = lambda r: fake
        out = connections.chat(self.root, rec["id"], [{"role": "user", "content": "hi"}])
        self.assertEqual(out, "hello-from-brain")
        self.assertEqual(fake.last["model"], "deflt")                      # ใช้ default model

    def test_chat_disabled_connection_errors(self):
        rec = connections.add(self.root, "B", "ollama", model="m", enabled=False)
        connections._backend_for = lambda r: _FakeBackend()
        with self.assertRaises(connections.ConnectionError):
            connections.chat(self.root, rec["id"], [{"role": "user", "content": "hi"}])

    def test_chat_needs_model(self):
        rec = connections.add(self.root, "B", "ollama")                    # ไม่ตั้ง default model
        connections._backend_for = lambda r: _FakeBackend()
        with self.assertRaises(connections.ConnectionError):
            connections.chat(self.root, rec["id"], [{"role": "user", "content": "hi"}])

    def test_backend_error_becomes_connection_error(self):
        rec = connections.add(self.root, "B", "ollama", model="m")

        class _Boom:
            def generate(self, *a, **k):
                raise model_backend.BackendError("down")
        connections._backend_for = lambda r: _Boom()
        with self.assertRaises(connections.ConnectionError):
            connections.chat(self.root, rec["id"], [{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()
