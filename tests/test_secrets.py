"""test_secrets.py — API keys at rest.

DPAPI is mocked on Linux (CI). The non-Windows path is the 0600 file,
because keyring is not declared in requirements.txt.
"""

import ctypes
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config_manager  # noqa: E402
from app import config_versions  # noqa: E402
from app import connections  # noqa: E402
from app import model_backend  # noqa: E402
from app import secrets  # noqa: E402

SENTINEL = "sk-PLAINTEXT-SENTINEL"


def _reverse_protect(data: bytes) -> bytes:
    return b"\x00dpapi" + data[::-1]


def _reverse_unprotect(data: bytes) -> bytes:
    if not data.startswith(b"\x00dpapi"):
        raise OSError("bad blob")
    return data[len(b"\x00dpapi"):][::-1]


@contextmanager
def mocked_dpapi():
    """Make protect/unprotect succeed without Windows."""
    with mock.patch.object(secrets, "using_dpapi", return_value=True), \
            mock.patch.object(secrets, "_win_protect", side_effect=_reverse_protect), \
            mock.patch.object(secrets, "_win_unprotect", side_effect=_reverse_unprotect):
        yield


class DpapiCallTest(unittest.TestCase):
    def test_flags_are_current_user_not_local_machine(self):
        class _Fake:
            def __init__(self):
                self.flags = []
                self._bufs = []
                self.freed = []

            def protect(self, p_in, desc, entropy, reserved, prompt, flags, p_out):
                self.flags.append(flags)
                src = ctypes.string_at(p_in.contents.pbData, p_in.contents.cbData)
                out = b"WDPAPI" + src
                buf = (ctypes.c_byte * len(out)).from_buffer_copy(out)
                self._bufs.append(buf)
                p_out.contents.cbData = len(out)
                p_out.contents.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
                return 1

            def unprotect(self, p_in, desc, entropy, reserved, prompt, flags, p_out):
                self.flags.append(flags)
                src = ctypes.string_at(p_in.contents.pbData, p_in.contents.cbData)
                if not src.startswith(b"WDPAPI"):
                    return 0
                out = src[len(b"WDPAPI"):]
                buf = (ctypes.c_byte * len(out)).from_buffer_copy(out)
                self._bufs.append(buf)
                p_out.contents.cbData = len(out)
                p_out.contents.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
                return 1

            def local_free(self, ptr):
                self.freed.append(ptr)
                return None

        fake = _Fake()
        blob = secrets.dpapi_protect(b"sk-secret", fake.protect, fake.local_free)
        self.assertEqual(fake.flags[0], secrets.CRYPTPROTECT_UI_FORBIDDEN)
        self.assertEqual(fake.flags[0] & secrets.CRYPTPROTECT_LOCAL_MACHINE, 0)
        self.assertNotEqual(blob, b"sk-secret")
        plain = secrets.dpapi_unprotect(blob, fake.unprotect, fake.local_free)
        self.assertEqual(plain, b"sk-secret")
        self.assertEqual(fake.flags[1], secrets.CRYPTPROTECT_UI_FORBIDDEN)
        self.assertEqual(len(fake.freed), 2)

    def test_protect_off_windows_raises_and_does_not_echo_secret(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(secrets.SecretError):
                secrets.protect(b"sk-do-not-log")
        self.assertNotIn("sk-do-not-log", buf.getvalue())


class FileFallbackTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        secrets._file_fallback_warned = False

    def tearDown(self):
        self._tmp.cleanup()

    def test_keyring_is_not_a_dependency(self):
        self.assertFalse(secrets.keyring_is_dependency())

    def test_0600_file_warning_and_no_secret_in_stdout(self):
        fake_keyring = mock.Mock()
        buf = io.StringIO()
        with mock.patch.dict(sys.modules, {"keyring": fake_keyring}), redirect_stdout(buf):
            secrets.store(self.root, "config:OPENAI_API_KEY", SENTINEL)
            self.assertEqual(secrets.reveal(self.root, "config:OPENAI_API_KEY"), SENTINEL)
        fake_keyring.set_password.assert_not_called()
        text = buf.getvalue()
        self.assertIn("0600", text)
        self.assertNotIn(SENTINEL, text)
        stored = self.root / "secrets.bin"
        mode = os.stat(stored).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        # documented fallback: the secret is in the 0600 file, not in the warning
        self.assertIn(SENTINEL, stored.read_text(encoding="utf-8"))

    def test_keyring_used_only_when_declared(self):
        fake = mock.Mock()
        fake.get_password.return_value = SENTINEL
        buf = io.StringIO()
        with mock.patch.object(secrets, "keyring_is_dependency", return_value=True), \
                mock.patch.object(secrets, "_import_keyring", return_value=fake), \
                redirect_stdout(buf):
            secrets.store(self.root, "config:OPENAI_API_KEY", SENTINEL)
            self.assertEqual(secrets.reveal(self.root, "config:OPENAI_API_KEY"), SENTINEL)
        fake.set_password.assert_called_once_with(
            secrets.KEYRING_SERVICE, "config:OPENAI_API_KEY", SENTINEL)
        raw = (self.root / "secrets.bin").read_text(encoding="utf-8")
        self.assertNotIn(SENTINEL, raw)
        self.assertNotIn(SENTINEL, buf.getvalue())

    def test_keyring_failure_falls_back_without_losing_the_value(self):
        fake = mock.Mock()
        fake.set_password.side_effect = RuntimeError("no-backend")
        buf = io.StringIO()
        with mock.patch.object(secrets, "keyring_is_dependency", return_value=True), \
                mock.patch.object(secrets, "_import_keyring", return_value=fake), \
                redirect_stdout(buf):
            secrets.store(self.root, "config:OPENAI_API_KEY", SENTINEL)
            self.assertEqual(secrets.reveal(self.root, "config:OPENAI_API_KEY"), SENTINEL)
        self.assertIn(SENTINEL, (self.root / "secrets.bin").read_text(encoding="utf-8"))
        self.assertNotIn(SENTINEL, buf.getvalue())


class DpapiMigrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        secrets._file_fallback_warned = False

    def tearDown(self):
        self._tmp.cleanup()

    def test_plaintext_config_is_sealed_on_read_and_still_returned(self):
        (self.root / "config.json").write_text(json.dumps({
            "OPENAI_API_KEY": SENTINEL,
            "MODEL_BACKEND": "ollama",
        }), encoding="utf-8")
        buf = io.StringIO()
        with mocked_dpapi(), redirect_stdout(buf):
            self.assertEqual(config_manager.get_key(self.root, "OPENAI_API_KEY"), SENTINEL)
            self.assertEqual(config_manager.get_key(self.root, "MODEL_BACKEND"), "ollama")
            self.assertEqual(config_manager.get_key(self.root, "OPENAI_API_KEY"), SENTINEL)
        disk = (self.root / "config.json").read_text(encoding="utf-8")
        blob = (self.root / "secrets.bin").read_text(encoding="utf-8")
        self.assertNotIn(SENTINEL, disk)
        self.assertNotIn(SENTINEL, blob)
        self.assertIn("ollama", disk)
        self.assertIn(secrets.REF_KEY, disk)
        self.assertIn('"alg": "dpapi"', blob)
        self.assertNotIn(SENTINEL, buf.getvalue())

    def test_failed_protect_keeps_plaintext(self):
        (self.root / "config.json").write_text(
            json.dumps({"OPENAI_API_KEY": SENTINEL}), encoding="utf-8")
        with mock.patch.object(secrets, "using_dpapi", return_value=True), \
                mock.patch.object(secrets, "_win_protect", side_effect=OSError("boom")):
            self.assertEqual(config_manager.get_key(self.root, "OPENAI_API_KEY"), SENTINEL)
        self.assertIn(SENTINEL, (self.root / "config.json").read_text(encoding="utf-8"))

    def test_failed_unprotect_does_not_delete_the_blob(self):
        with mocked_dpapi():
            config_manager.set_key(self.root, "OPENAI_API_KEY", SENTINEL)
            before = (self.root / "secrets.bin").read_text(encoding="utf-8")
        with mock.patch.object(secrets, "using_dpapi", return_value=True), \
                mock.patch.object(secrets, "_win_unprotect", side_effect=OSError("nope")):
            self.assertIsNone(config_manager.get_key(self.root, "OPENAI_API_KEY"))
        self.assertEqual((self.root / "secrets.bin").read_text(encoding="utf-8"), before)
        with mocked_dpapi():
            self.assertEqual(config_manager.get_key(self.root, "OPENAI_API_KEY"), SENTINEL)

    def test_corrupt_store_is_not_overwritten(self):
        original = b"{not-json"
        (self.root / "secrets.bin").write_bytes(original)
        (self.root / "config.json").write_text(
            json.dumps({"TAVILY_API_KEY": SENTINEL}), encoding="utf-8")
        self.assertEqual(config_manager.get_key(self.root, "TAVILY_API_KEY"), SENTINEL)
        self.assertEqual((self.root / "secrets.bin").read_bytes(), original)
        self.assertIn(SENTINEL, (self.root / "config.json").read_text(encoding="utf-8"))

    def test_backend_receives_plaintext_not_the_ref(self):
        with mocked_dpapi():
            model_backend.set_backend_settings(self.root, {
                "MODEL_BACKEND": "openai",
                "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
                "OPENAI_API_KEY": SENTINEL,
            })
            backend = model_backend.get_backend(self.root)
        self.assertEqual(backend.api_key, SENTINEL)
        self.assertNotIn(SENTINEL, (self.root / "config.json").read_text(encoding="utf-8"))

    def test_connection_plaintext_migrates_and_raw_get_returns_it(self):
        doc = {"schema_version": 1, "records": [{
            "id": "con-legacy",
            "name": "Legacy",
            "kind": "ollama",
            "base_url": "",
            "model": "m",
            "api_key": SENTINEL,
            "enabled": True,
        }]}
        (self.root / "connections.json").write_text(json.dumps(doc), encoding="utf-8")
        with mocked_dpapi():
            raw = connections.get(self.root, "con-legacy", raw=True)
            listed = connections.list_connections(self.root)
        self.assertEqual(raw["api_key"], SENTINEL)
        self.assertNotIn("api_key", listed[0])
        self.assertTrue(listed[0]["api_key_set"])
        disk = (self.root / "connections.json").read_text(encoding="utf-8")
        blob = (self.root / "secrets.bin").read_text(encoding="utf-8")
        self.assertNotIn(SENTINEL, disk)
        self.assertNotIn(SENTINEL, blob)

    def test_snapshot_strips_secret_and_rollback_restores_it(self):
        with mocked_dpapi():
            config_manager.set_key(self.root, "OPENAI_API_KEY", "sk-old-value")
            config_manager.set_key(self.root, "MODEL_BACKEND", "ollama")
            meta = config_versions.snapshot(self.root, label="good")
            config_manager.set_key(self.root, "OPENAI_API_KEY", "sk-new-value")
            self.assertEqual(config_manager.get_key(self.root, "OPENAI_API_KEY"), "sk-new-value")
            config_versions.rollback(self.root, meta["id"])
            self.assertEqual(config_manager.get_key(self.root, "OPENAI_API_KEY"), "sk-old-value")
            self.assertEqual(config_manager.get_key(self.root, "MODEL_BACKEND"), "ollama")
        versions = (self.root / "config_versions.json").read_text(encoding="utf-8")
        config = (self.root / "config.json").read_text(encoding="utf-8")
        blob = (self.root / "secrets.bin").read_text(encoding="utf-8")
        for secret in ("sk-old-value", "sk-new-value"):
            self.assertNotIn(secret, versions)
            self.assertNotIn(secret, config)
            self.assertNotIn(secret, blob)

    def test_legacy_snapshot_plaintext_is_kept_for_each_version(self):
        versions = [
            {"id": "v1", "ts": 1, "label": "", "config": {"OPENAI_API_KEY": "sk-one"}},
            {"id": "v2", "ts": 2, "label": "", "config": {"OPENAI_API_KEY": "sk-two"}},
        ]
        (self.root / "config_versions.json").write_text(
            json.dumps(versions), encoding="utf-8")
        with mocked_dpapi():
            config_versions.list_versions(self.root)
            self.assertEqual(secrets.reveal(self.root, "snapshot:v1:OPENAI_API_KEY"), "sk-one")
            self.assertEqual(secrets.reveal(self.root, "snapshot:v2:OPENAI_API_KEY"), "sk-two")
            config_versions.rollback(self.root, "v1")
            self.assertEqual(config_manager.get_key(self.root, "OPENAI_API_KEY"), "sk-one")
            config_versions.rollback(self.root, "v2")
            self.assertEqual(config_manager.get_key(self.root, "OPENAI_API_KEY"), "sk-two")
        text = (self.root / "config_versions.json").read_text(encoding="utf-8")
        self.assertNotIn("sk-one", text)
        self.assertNotIn("sk-two", text)

    def test_non_secret_is_not_moved(self):
        config_manager.set_key(self.root, "MODEL_BACKEND", "ollama")
        disk = (self.root / "config.json").read_text(encoding="utf-8")
        self.assertIn("ollama", disk)
        self.assertFalse((self.root / "secrets.bin").exists())


class SecretNameTest(unittest.TestCase):
    def test_credential_names(self):
        self.assertTrue(secrets.is_secret_name("OPENAI_API_KEY"))
        self.assertTrue(secrets.is_secret_name("API_KEY"))
        self.assertTrue(secrets.is_secret_name("HUB_TOKEN"))
        self.assertTrue(secrets.is_secret_name("CLUSTER_FORWARD_TOKEN"))
        self.assertTrue(secrets.is_secret_name("STATIC_TOKENS"))
        self.assertTrue(secrets.is_secret_name("SMTP_PASS"))
        self.assertTrue(secrets.is_secret_name("DISCORD_WEBHOOK_URL"))
        self.assertFalse(secrets.is_secret_name("MODEL_BACKEND"))
        self.assertFalse(secrets.is_secret_name("CLUSTER_FORWARD_ENABLED"))
        self.assertFalse(secrets.is_secret_name("SMTP_HOST"))
        self.assertFalse(secrets.is_secret_name("NEW_KEY"))


if __name__ == "__main__":
    unittest.main()
