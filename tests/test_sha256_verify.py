"""test_sha256_verify.py — installer_gui.verify_sha256

ตรวจไฟล์ที่ดาวน์โหลดแล้ว: hash ตรงเก็บไฟล์ไว้, ไม่ตรงลบไฟล์แล้วโยน ChecksumMismatch.
ไม่แตะเน็ต.
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import installer_gui  # noqa: E402


class VerifySha256Test(unittest.TestCase):
    def test_match_returns_digest_and_keeps_file(self):
        payload = b"lca-artifact" * 50  # ใหญ่กว่า chunk ที่ส่งเข้าไป เพื่อบังคับให้อ่านหลายรอบ
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.bin"
            path.write_bytes(payload)
            got = installer_gui.verify_sha256(path, expected.upper(), chunk_size=16)
            self.assertEqual(got, expected)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), payload)

    def test_mismatch_raises_and_removes_file(self):
        payload = b"good-bytes"
        actual = hashlib.sha256(payload).hexdigest()
        wrong = hashlib.sha256(b"other-bytes").hexdigest()
        self.assertNotEqual(actual, wrong)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial.bin"
            path.write_bytes(payload)
            with self.assertRaises(installer_gui.ChecksumMismatch) as cm:
                installer_gui.verify_sha256(path, wrong)
            self.assertFalse(path.exists())
            message = str(cm.exception)
            self.assertIn(wrong, message)
            self.assertIn(actual, message)
            self.assertIn("ลบไฟล์", message)


class VerifySha256ExtraTest(unittest.TestCase):
    def test_checksummismatch_is_exception(self):
        self.assertTrue(issubclass(installer_gui.ChecksumMismatch, Exception))

    def test_verify_returns_lowercase_hex(self):
        payload = b"test-data"
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.bin"
            path.write_bytes(payload)
            result = installer_gui.verify_sha256(path, expected)
        self.assertEqual(result, result.lower())
        self.assertEqual(len(result), 64)

    def test_empty_file_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.bin"
            path.write_bytes(b"")
            wrong = hashlib.sha256(b"not-empty").hexdigest()
            with self.assertRaises(installer_gui.ChecksumMismatch):
                installer_gui.verify_sha256(path, wrong)

    def test_single_byte_file_matches(self):
        payload = b"\x42"
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.bin"
            path.write_bytes(payload)
            result = installer_gui.verify_sha256(path, expected)
        self.assertEqual(result, expected)

    def test_default_chunk_size_works(self):
        payload = b"chunk-default-test"
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.bin"
            path.write_bytes(payload)
            result = installer_gui.verify_sha256(path, expected)
        self.assertEqual(result, expected)

    def test_checksummismatch_has_message(self):
        payload = b"data"
        wrong = hashlib.sha256(b"other").hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.bin"
            path.write_bytes(payload)
            with self.assertRaises(installer_gui.ChecksumMismatch) as cm:
                installer_gui.verify_sha256(path, wrong)
        self.assertGreater(len(str(cm.exception)), 0)


if __name__ == "__main__":
    unittest.main()
