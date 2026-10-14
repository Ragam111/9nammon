"""
tavily_search.py — /websearch ผ่าน Tavily Search API (ตัวเลือกที่ 2 นอกเหนือ Brave)

Endpoint: POST https://api.tavily.com/search
Auth: header "Authorization: Bearer <key>" (ไม่ใช้ pip package tavily-python
เพื่อคงหลัก Rule ข้อ 13 — stdlib เท่านั้น ยิง REST ตรงผ่าน urllib)

Key: TAVILY_API_KEY อ่านผ่าน config_manager (config.json > env var) — ห้าม hardcode

Interface เหมือน web_search.py ทุกจุด (ให้สลับ provider กันได้โดย local_coder.py
ไม่ต้องรู้รายละเอียดข้างในของแต่ละ provider):
    search_web(query, project_root=...) -> list[dict]   (raise RuntimeError ถ้าไม่มี key/ล้มเหลว)
    format_results_for_context(results) -> str
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

from config_manager import get_key  # noqa: E402

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_RESULTS = 5


def search_web(query: str, project_root: Path) -> list:
    """ค้นหาจริงผ่าน Tavily Search API — คืน list ของ dict {"title", "url", "snippet"}
    raise RuntimeError ถ้าไม่มี key หรือเรียก API ไม่สำเร็จ (ให้ caller fallback เอง
    ตาม Rule ข้อ 18 เช่นเดียวกับ web_search.py)"""
    api_key = get_key(project_root, "TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("ไม่พบ TAVILY_API_KEY — ตั้งผ่าน /config set หรือ env var ก่อนใช้ /websearch on")

    payload = json.dumps({"query": query, "max_results": MAX_RESULTS}).encode("utf-8")
    req = urllib.request.Request(
        TAVILY_SEARCH_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise RuntimeError(f"เรียก Tavily Search API ไม่สำเร็จ: {e}") from e

    try:
        data = json.loads(raw)
        items = data.get("results", [])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ตอบกลับจาก Tavily Search ผิดรูปแบบ: {e}") from e

    results = []
    for item in items[:MAX_RESULTS]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        })
    return results


def format_results_for_context(results: list) -> str:
    """แปลง list ผลลัพธ์เป็น text block ใส่เข้า context — รูปแบบเดียวกับ web_search.py
    เพื่อให้ local_coder.py ใช้ฟังก์ชันนี้แทนกันได้ไม่ว่าจะเลือก provider ไหน"""
    if not results:
        return "ผลการค้นหาเว็บ (Tavily): ไม่พบผลลัพธ์"
    lines = ["ผลการค้นหาเว็บ (Tavily, ใช้ประกอบการตอบ ถ้าเกี่ยวข้อง):"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']} — {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)
