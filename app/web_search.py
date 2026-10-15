"""
web_search.py — /websearch on|off: ค้นหาเว็บจริงผ่าน Brave Search API (free tier)
แล้วแปะผลลัพธ์เข้า context ก่อนส่งให้โมเดล เพราะ Ollama local ไม่ได้ต่อเน็ตเอง

Key: BRAVE_SEARCH_API_KEY อ่านผ่าน config_manager (config.json > env var) —
ห้าม hardcode ตาม Rule ข้อ 8

Interface ที่ local_coder.py เรียกใช้ตรงๆ:
    search_web(query, project_root=...) -> list[dict]   (raise RuntimeError ถ้าไม่มี key/ล้มเหลว)
    format_results_for_context(results) -> str
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from config_manager import get_key  # noqa: E402

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 5


def search_web(query: str, project_root: Path) -> list:
    """ค้นหาจริงผ่าน Brave Search API — คืน list ของ dict {"title", "url", "snippet"}
    raise RuntimeError ถ้าไม่มี key หรือเรียก API ไม่สำเร็จ (ให้ caller fallback เอง
    ตาม Rule ข้อ 18: ห้ามทำให้โปรแกรมค้าง/ปฏิเสธตอบเพียงเพราะค้นหาไม่ได้)"""
    api_key = get_key(project_root, "BRAVE_SEARCH_API_KEY")
    if not api_key:
        raise RuntimeError("ไม่พบ BRAVE_SEARCH_API_KEY — ตั้งผ่าน /config set หรือ env var ก่อนใช้ /websearch on")

    params = urllib.parse.urlencode({"q": query, "count": MAX_RESULTS})
    req = urllib.request.Request(
        f"{BRAVE_SEARCH_URL}?{params}",
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise RuntimeError(f"เรียก Brave Search API ไม่สำเร็จ: {e}") from e

    try:
        data = json.loads(raw)
        items = data.get("web", {}).get("results", [])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ตอบกลับจาก Brave Search ผิดรูปแบบ: {e}") from e

    results = []
    for item in items[:MAX_RESULTS]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
        })
    return results


def format_results_for_context(results: list) -> str:
    """แปลง list ผลลัพธ์เป็น text block ใส่เข้า context ให้โมเดลอ่านก่อนตอบ"""
    if not results:
        return "ผลการค้นหาเว็บ: ไม่พบผลลัพธ์"
    lines = ["ผลการค้นหาเว็บ (ใช้ประกอบการตอบ ถ้าเกี่ยวข้อง):"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']} — {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)
