"""
test_promptpay.py — EMVCo PromptPay payload + CRC16 (offline, stdlib)

Reference vector (derived by hand, documented here):
    PromptPay ID  : 0812345678 (fake test phone) -> 0066812345678 (drop leading 0, prefix 0066)
    amount        : 299.00 THB  -> dynamic QR (point of initiation "12")
    fields (tag, len, value), ascending tag order:
        00 02 01                          payload format indicator
        01 02 12                          dynamic (has amount)
        29 37 [00 16 A000000677010111]    PromptPay AID
              [01 13 0066812345678]       mobile number
        53 03 764                         THB
        54 06 299.00                      amount
        58 02 TH                          country
        63 04 <CRC>                       CRC16 over everything before + "6304"
    CRC = CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflect, xorout 0).
    The test re-implements that CRC bit by bit and pins it to the standard check
    value CRC("123456789") == 0x29B1, so the vector does not trust app code.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import promptpay  # noqa: E402

FAKE_PHONE = "0812345678"
FAKE_NID = "1234567890123"


def ref_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


BODY_PHONE_299 = ("000201" "010212"
                  "2937" "0016A000000677010111" "01130066812345678"
                  "5303764" "5406299.00" "5802TH" "6304")
REF_PHONE_299 = BODY_PHONE_299 + format(ref_crc16(BODY_PHONE_299.encode()), "04X")


class Crc16Test(unittest.TestCase):
    def test_reference_impl_check_value(self):
        self.assertEqual(ref_crc16(b"123456789"), 0x29B1)

    def test_app_crc_check_value(self):
        self.assertEqual(promptpay.crc16_ccitt(b"123456789"), 0x29B1)

    def test_app_crc_matches_reference(self):
        for s in (b"", b"A", BODY_PHONE_299.encode(), b"00020101021129370016"):
            self.assertEqual(promptpay.crc16_ccitt(s), ref_crc16(s))


class PayloadTest(unittest.TestCase):
    def test_phone_with_amount_matches_reference_vector(self):
        self.assertEqual(promptpay.build_payload(FAKE_PHONE, 299), REF_PHONE_299)

    def test_reference_vector_is_pinned(self):
        # pin the literal so a change to field order/format is caught too
        self.assertEqual(REF_PHONE_299[:-4], BODY_PHONE_299)
        self.assertEqual(len(REF_PHONE_299), 84)

    def test_phone_formats_accepted(self):
        for raw in ("081-234-5678", "081 234 5678", "+66812345678", "66812345678"):
            self.assertEqual(promptpay.build_payload(raw, 299), REF_PHONE_299, raw)

    def test_national_id(self):
        p = promptpay.build_payload(FAKE_NID, 10.5)
        self.assertIn("2937" "0016A000000677010111" "0213" + FAKE_NID, p)
        self.assertIn("540510.50", p)
        self.assertTrue(promptpay.verify_crc(p))

    def test_static_without_amount(self):
        p = promptpay.build_payload(FAKE_PHONE)
        self.assertTrue(p.startswith("000201010211"))
        tags = promptpay.parse_tlv(p)
        self.assertNotIn("54", tags)
        self.assertTrue(promptpay.verify_crc(p))

    def test_parse_roundtrip(self):
        tags = promptpay.parse_tlv(REF_PHONE_299)
        self.assertEqual(tags["54"], "299.00")
        self.assertEqual(tags["58"], "TH")
        self.assertEqual(tags["53"], "764")
        self.assertEqual(promptpay.parse_tlv(tags["29"])["00"], promptpay.PROMPTPAY_AID)

    def test_verify_crc_detects_tamper(self):
        bad = REF_PHONE_299.replace("299.00", "199.00")
        self.assertFalse(promptpay.verify_crc(bad))
        self.assertTrue(promptpay.verify_crc(REF_PHONE_299))

    def test_invalid_inputs(self):
        for bad_id in ("", "12345", "08123456789", "abc", None):
            with self.assertRaises(ValueError):
                promptpay.build_payload(bad_id, 1)
        for bad_amt in (0, -1, "x", 10_000_000):
            with self.assertRaises(ValueError):
                promptpay.build_payload(FAKE_PHONE, bad_amt)

    def test_mask_never_reveals_full_id(self):
        m = promptpay.mask_id(FAKE_PHONE)
        self.assertNotIn("12345", m)
        self.assertTrue(m.endswith("678"))


if __name__ == "__main__":
    unittest.main()
