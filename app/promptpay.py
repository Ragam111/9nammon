"""
promptpay.py — สร้าง PromptPay QR payload (EMVCo merchant-presented) แบบ offline, stdlib เท่านั้น

ไม่เรียก API ธนาคาร/payment gateway ใด ๆ (ไม่มีค่าธรรมเนียมบุคคลที่สาม):
ระบบแค่สร้างข้อความ payload ให้ลูกค้าสแกนโอนเข้าพร้อมเพย์ของเจ้าของ แล้ว ADMIN ยืนยันเองว่าได้เงิน

Payload (TLV: tag 2 หลัก + ความยาว 2 หลัก + ค่า), เรียง tag จากน้อยไปมาก:
    00 "01"                      payload format indicator
    01 "11" | "12"               11 = static (ไม่มียอด), 12 = dynamic (มียอด)
    29 [00 A000000677010111]     PromptPay AID
       [01 0066xxxxxxxxx]        เบอร์มือถือ (ตัด 0 นำหน้า + 0066) — 13 หลัก
       [02 xxxxxxxxxxxxx]        เลขประจำตัวประชาชน / เลขผู้เสียภาษี 13 หลัก
       [03 xxxxxxxxxxxxxxx]      e-wallet ID 15 หลัก
    53 "764"                     THB
    54 "299.00"                  ยอด (ถ้ามี)
    58 "TH"
    63 CRC16                     CRC-16/CCITT-FALSE ของทุกอย่างก่อนหน้า + "6304", hex ตัวใหญ่ 4 หลัก

Interface:
    build_payload(promptpay_id, amount=None) -> str
    crc16_ccitt(data: bytes) -> int
    verify_crc(payload) -> bool
    parse_tlv(text) -> dict[str, str]
    mask_id(promptpay_id) -> str        # สำหรับแสดง/ log — ไม่โชว์เลขเต็ม
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

PROMPTPAY_AID = "A000000677010111"
MAX_AMOUNT = Decimal("9999999.99")   # tag 54 ยาวได้ไม่เกิน 13 ตัวอักษร; จำกัดไว้ที่ 7 หลัก

_TABLE: list[int] = []


def _build_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        table.append(crc & 0xFFFF)
    return table


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) แบบ table — check value "123456789" = 0x29B1"""
    if not _TABLE:
        _TABLE.extend(_build_table())
    crc = 0xFFFF
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _TABLE[((crc >> 8) ^ byte) & 0xFF]
    return crc


def _tlv(tag: str, value: str) -> str:
    if len(value) > 99:
        raise ValueError(f"ค่า tag {tag} ยาวเกิน 99 ตัวอักษร")
    return f"{tag}{len(value):02d}{value}"


def normalize_target(promptpay_id) -> tuple[str, str]:
    """คืน (sub-tag, ค่า) ของ tag 29 จาก PromptPay ID ที่ผู้ใช้กรอก (มีขีด/ช่องว่าง/+66 ได้)"""
    if not isinstance(promptpay_id, str):
        raise ValueError("PROMPTPAY_ID ต้องเป็นข้อความ")
    digits = re.sub(r"[\s\-]", "", promptpay_id.strip())
    if digits.startswith("+"):
        digits = digits[1:]
    if not digits.isdigit():
        raise ValueError("PROMPTPAY_ID ต้องเป็นตัวเลข (เบอร์มือถือ / เลขประจำตัว 13 หลัก / e-wallet 15 หลัก)")
    if len(digits) == 10 and digits.startswith("0"):
        return "01", "0066" + digits[1:]
    if len(digits) == 11 and digits.startswith("66"):
        return "01", "00" + digits
    if len(digits) == 13:
        return "02", digits
    if len(digits) == 15:
        return "03", digits
    raise ValueError("รูปแบบ PROMPTPAY_ID ไม่ถูกต้อง (เบอร์มือถือ 10 หลัก, เลขประจำตัว 13 หลัก หรือ e-wallet 15 หลัก)")


def format_amount(amount) -> str:
    """ยอดเงินเป็นข้อความ 2 ตำแหน่ง เช่น 299 -> "299.00" (raise ValueError ถ้าไม่ถูกต้อง)"""
    if isinstance(amount, bool):
        raise ValueError("amount ต้องเป็นตัวเลข")
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"amount ต้องเป็นตัวเลข: {amount!r}") from e
    if not value.is_finite():
        raise ValueError(f"amount ต้องเป็นตัวเลขจำกัด: {amount!r}")
    if value <= 0 or value > MAX_AMOUNT:
        raise ValueError(f"amount ต้องอยู่ระหว่าง 0.01 ถึง {MAX_AMOUNT}")
    return f"{value:.2f}"


def build_payload(promptpay_id, amount=None) -> str:
    """สร้าง payload ของ PromptPay QR (ไม่มี network) — amount=None = QR แบบไม่ระบุยอด"""
    sub, target = normalize_target(promptpay_id)
    merchant = _tlv("00", PROMPTPAY_AID) + _tlv(sub, target)
    parts = [_tlv("00", "01"), _tlv("01", "11" if amount is None else "12"),
             _tlv("29", merchant), _tlv("53", "764")]
    if amount is not None:
        parts.append(_tlv("54", format_amount(amount)))
    parts.append(_tlv("58", "TH"))
    body = "".join(parts) + "6304"
    return body + f"{crc16_ccitt(body.encode('ascii')):04X}"


def verify_crc(payload: str) -> bool:
    """ตรวจว่า 4 ตัวท้ายเป็น CRC ที่ถูกต้องของส่วนก่อนหน้า (รวม "6304")"""
    if not isinstance(payload, str) or len(payload) < 8 or payload[-8:-4] != "6304":
        return False
    try:
        return int(payload[-4:], 16) == crc16_ccitt(payload[:-4].encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


def parse_tlv(text: str) -> dict:
    """แยก TLV ชั้นเดียว -> {tag: value} (raise ValueError ถ้าโครงสร้างเสีย)"""
    out, i = {}, 0
    while i < len(text):
        if i + 4 > len(text):
            raise ValueError("TLV ไม่ครบ")
        tag, length = text[i:i + 2], text[i + 2:i + 4]
        if not length.isdigit():
            raise ValueError("ความยาว TLV ไม่ใช่ตัวเลข")
        n = int(length)
        value = text[i + 4:i + 4 + n]
        if len(value) != n:
            raise ValueError("ค่า TLV สั้นกว่าที่ระบุ")
        out[tag] = value
        i += 4 + n
    return out


def mask_id(promptpay_id) -> str:
    """แสดงเฉพาะ 3 ตัวท้าย เช่น ******678 — ใช้ใน UI/log แทนเลขเต็ม"""
    digits = re.sub(r"\D", "", str(promptpay_id or ""))
    if len(digits) <= 3:
        return "***"
    return "*" * (len(digits) - 3) + digits[-3:]
