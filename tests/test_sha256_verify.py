"""test_sha256_verify.py — installer_gui.verify_sha256 + check_free_disk

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

    def test_returns_lowercase_hex(self):
        payload = b"hello"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.bin"
            path.write_bytes(payload)
            result = installer_gui.verify_sha256(path, digest)
            self.assertEqual(result, result.lower())

    def test_uppercase_expected_accepted(self):
        payload = b"upper test"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.bin"
            path.write_bytes(payload)
            result = installer_gui.verify_sha256(path, digest.upper())
            self.assertEqual(result, digest)

    def test_checksummismatch_is_runtime_error(self):
        self.assertTrue(issubclass(installer_gui.ChecksumMismatch, RuntimeError))

    def test_empty_file_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.bin"
            path.write_bytes(b"")
            wrong = "a" * 64
            with self.assertRaises(installer_gui.ChecksumMismatch):
                installer_gui.verify_sha256(path, wrong)

    def test_large_file_multichunk(self):
        payload = b"x" * (1024 * 1024)  # 1 MB > default chunk
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.bin"
            path.write_bytes(payload)
            result = installer_gui.verify_sha256(path, digest)
            self.assertEqual(result, digest)


class CheckFreeDiskTest(unittest.TestCase):
    def test_sufficient_space_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, free, msg = installer_gui.check_free_disk(tmp, min_bytes=1)
            self.assertTrue(ok)
            self.assertGreater(free, 0)
            self.assertEqual(msg, "")

    def test_excessive_min_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, _, msg = installer_gui.check_free_disk(tmp, min_bytes=10 * 1024 ** 4)
            self.assertFalse(ok)
            self.assertGreater(len(msg), 0)

    def test_returns_tuple_of_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = installer_gui.check_free_disk(tmp, min_bytes=1)
            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 3)


if __name__ == "__main__":
    unittest.main()
