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


if __name__ == "__main__":
    unittest.main()
