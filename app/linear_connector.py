"""
linear_connector.py — เชื่อม Linear API (อ่านอย่างเดียว)

ตาม Rule ข้อ 8: ห้าม hardcode API key — อ่านจาก environment variable
LINEAR_API_KEY เท่านั้น

ตาม Rule ข้อ 16: ฟีเจอร์เขียนสถานะกลับ (update_issue_status) พักไว้ก่อน —
ฟังก์ชันนี้มีไว้แต่ปฏิเสธทำงานถ้าไม่ได้ confirm=True ชัดเจน ยังไม่ผูกเข้า
คำสั่งไหนใน local_coder.py ห้ามแก้ไข/ขยายจนกว่าผู้ใช้จะขอกลับมาทำต่อ
"""

import json
import os
import urllib.error
import urllib.request

LINEAR_API_URL = "https://api.linear.app/graphql"

MY_ISSUES_QUERY = """
query {
  viewer {
    assignedIssues(filter: { state: { type: { neq: "completed" } } }) {
      nodes {
        identifier
        title
        url
        state { name }
      }
    }
  }
}
"""


def _get_api_key() -> str:
    key = os.environ.get("LINEAR_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ไม่พบ LINEAR_API_KEY — ตั้ง environment variable ก่อนใช้ /linear sync "
            "(ห้าม hardcode key ลงไฟล์ตาม Rule ข้อ 8)"
        )
    return key


def fetch_my_issues() -> list:
    """ดึง issue ที่ assign ให้ผู้ใช้ (ยังไม่ completed) จาก Linear — อ่านอย่างเดียว
    คืน list ของ dict: {"identifier", "title", "url", "state": {"name"}}
    raise RuntimeError ถ้าไม่มี key หรือเรียก API ไม่สำเร็จ"""
    api_key = _get_api_key()
    payload = json.dumps({"query": MY_ISSUES_QUERY}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_API_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise RuntimeError(f"เรียก Linear API ไม่สำเร็จ: {e}") from e

    try:
        data = json.loads(raw)
        if "errors" in data:
            raise RuntimeError(f"Linear API คืน error: {data['errors']}")
        return data["data"]["viewer"]["assignedIssues"]["nodes"]
    except (json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"ตอบกลับจาก Linear API ผิดรูปแบบ: {e}") from e


def update_issue_status(issue_id: str, new_state_id: str, confirm: bool = False) -> bool:
    """⏸️ พักไว้ตาม Rule ข้อ 16 — ฟังก์ชันนี้ยังไม่ผูกเข้า UI ยืนยันใดๆ
    ปฏิเสธทำงานเสมอถ้าไม่ได้ confirm=True อย่างชัดเจนจากผู้เรียก (กันการเขียนสถานะ
    กลับ Linear โดยไม่ตั้งใจ) — ห้ามแก้ไข/ขยายฟังก์ชันนี้จนกว่าผู้ใช้จะขอกลับมาทำต่อ"""
    if not confirm:
        raise RuntimeError(
            "ฟีเจอร์อัปเดตสถานะ Linear ยังพักไว้ (Rule ข้อ 16) — "
            "ต้องเรียกด้วย confirm=True เท่านั้น และต้องผ่านการยืนยันจากผู้ใช้ก่อนเสมอ"
        )
    raise NotImplementedError("ยังไม่ implement — พักไว้ตาม Rule ข้อ 16")
