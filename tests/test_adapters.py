"""test_adapters.py — เทส adapter ตระกูลเดียวกัน (Storage / Auth / Notifier)

pattern เดียวกับ test_model_backend: ทดสอบแต่ละ impl + ตัวเลือกจาก config
โดยไม่ต้องมีดิสก์จริงเยอะ/เครือข่ายจริง (ใช้ tmp dir + mock)
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import storage_backend as sb  # noqa: E402
from app import auth_backend as ab  # noqa: E402
from app import notifier as nf  # noqa: E402
from app import config_manager  # noqa: E402
from app import org_store  # noqa: E402


# ---------------- Storage ----------------

class _StorageContract:
    """สัญญาเดียวกันที่ทุก backend ต้องผ่าน — รันซ้ำกับทั้ง local และ memory"""
    def make(self):
        raise NotImplementedError

    def test_write_then_read(self):
        s = self.make()
        s.write_text("a/b.txt", "hello")
        self.assertEqual(s.read_text("a/b.txt"), "hello")

    def test_read_missing_is_none(self):
        self.assertIsNone(self.make().read_text("nope.txt"))

    def test_exists_and_delete(self):
        s = self.make()
        s.write_text("x.txt", "1")
        self.assertTrue(s.exists("x.txt"))
        self.assertTrue(s.delete("x.txt"))
        self.assertFalse(s.exists("x.txt"))
        self.assertFalse(s.delete("x.txt"))  # ลบซ้ำ = False ไม่ throw

    def test_list_keys_prefix(self):
        s = self.make()
        s.write_text("logs/1.txt", "a")
        s.write_text("logs/2.txt", "b")
        s.write_text("other.txt", "c")
        self.assertEqual(s.list_keys("logs/"), ["logs/1.txt", "logs/2.txt"])

    def test_unsafe_key_rejected(self):
        s = self.make()
        for bad in ("../escape", "/etc/passwd", ""):
            with self.assertRaises(sb.StorageError):
                s.write_text(bad, "x")


class LocalStorageTest(_StorageContract, unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def make(self):
        return sb.LocalStorageBackend(Path(self._tmp.name))


class MemoryStorageTest(_StorageContract, unittest.TestCase):
    def make(self):
        return sb.MemoryStorageBackend()


class GetStorageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_is_local(self):
        self.assertIsInstance(sb.get_storage(self.root), sb.LocalStorageBackend)

    def test_memory_selected_from_config(self):
        config_manager.set_key(self.root, "STORAGE_BACKEND", "memory")
        self.assertIsInstance(sb.get_storage(self.root), sb.MemoryStorageBackend)

    def test_local_honors_storage_root(self):
        config_manager.set_key(self.root, "STORAGE_ROOT", str(self.root / "custom"))
        s = sb.get_storage(self.root)
        self.assertEqual(s.root, self.root / "custom")


# ---------------- Auth ----------------

class StaticAuthTest(unittest.TestCase):
    def test_maps_token_to_role(self):
        b = ab.StaticTokenBackend({"tok-admin": "ADMIN"})
        self.assertEqual(b.authenticate("tok-admin")["role"], "ADMIN")

    def test_unknown_token_is_none(self):
        self.assertIsNone(ab.StaticTokenBackend({"a": "USER"}).authenticate("b"))

    def test_invalid_role_dropped(self):
        b = ab.StaticTokenBackend({"t": "SUPERGOD"})
        self.assertIsNone(b.authenticate("t"))


class LocalAuthTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_master_token_is_ceo(self):
        b = ab.LocalAuthBackend(self.root, "secret")
        self.assertEqual(b.authenticate("secret")["role"], "CEO")

    def test_no_token_localhost_is_ceo(self):
        b = ab.LocalAuthBackend(self.root, "secret")
        self.assertEqual(b.authenticate(None, "127.0.0.1")["role"], "CEO")

    def test_no_token_remote_is_none(self):
        b = ab.LocalAuthBackend(self.root, "secret")
        self.assertIsNone(b.authenticate(None, "10.0.0.5"))

    def test_wrong_token_does_not_fall_back_to_local(self):
        # ให้ token มาแต่ผิด = ปฏิเสธ แม้มาจาก localhost (กันเดา token แล้วหลุดเป็น CEO)
        b = ab.LocalAuthBackend(self.root, "secret")
        self.assertIsNone(b.authenticate("wrong", "127.0.0.1"))

    def test_valid_api_key_is_user(self):
        b = ab.LocalAuthBackend(self.root, "secret")
        with mock.patch.object(ab.org_store, "verify_api_key",
                               return_value={"owner": "neung", "tier": "pro", "key_id": "k1"}):
            got = b.authenticate("sk-xxx")
        self.assertEqual(got["role"], "USER")
        self.assertEqual(got["owner"], "neung")


class GetAuthBackendTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_is_local(self):
        self.assertIsInstance(ab.get_auth_backend(self.root, "m"), ab.LocalAuthBackend)

    def test_static_selected_from_config(self):
        config_manager.set_key(self.root, "AUTH_BACKEND", "static")
        config_manager.set_key(self.root, "STATIC_TOKENS", '{"t":"CEO"}')
        b = ab.get_auth_backend(self.root)
        self.assertIsInstance(b, ab.StaticTokenBackend)
        self.assertEqual(b.authenticate("t")["role"], "CEO")

    def test_static_bad_json_is_empty(self):
        config_manager.set_key(self.root, "AUTH_BACKEND", "static")
        config_manager.set_key(self.root, "STATIC_TOKENS", "not-json{")
        b = ab.get_auth_backend(self.root)
        self.assertIsNone(b.authenticate("anything"))


# ---------------- Notifier ----------------

class NotifierAdapterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_null_notifier_records_and_sends_nothing(self):
        n = nf.NullNotifier()
        n.send("JOB_DONE", "เสร็จแล้ว")
        self.assertEqual(len(n.sent), 1)
        self.assertEqual(n.sent[0]["event"], "JOB_DONE")

    def test_multichannel_wraps_notify(self):
        n = nf.MultiChannelNotifier(self.root, channels=("discord",))
        with mock.patch.object(nf, "notify", return_value={"discord": "sent"}) as m:
            self.assertEqual(n.send("E", "hi"), {"discord": "sent"})
        m.assert_called_once()

    def test_default_is_multichannel(self):
        self.assertIsInstance(nf.get_notifier(self.root), nf.MultiChannelNotifier)

    def test_null_selected_from_config(self):
        config_manager.set_key(self.root, "NOTIFIER_BACKEND", "null")
        self.assertIsInstance(nf.get_notifier(self.root), nf.NullNotifier)

    def test_channels_filtered_from_config(self):
        config_manager.set_key(self.root, "NOTIFIER_CHANNELS", "discord, bogus")
        n = nf.get_notifier(self.root)
        self.assertEqual(n.channels, ("discord",))


if __name__ == "__main__":
    unittest.main()
