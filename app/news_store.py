"""
news_store.py — RSS feed fetcher พร้อม 15-min in-memory cache (stdlib only)

get_news(feeds)  → {"articles": [...], "count": int, "feeds": int,
                     "errors": [...], "cached_until": int}
_fetch_feed(url) → list[dict]  — monkeypatch ได้ในเทส
"""

import threading
import time
import xml.etree.ElementTree as ET
from urllib.request import urlopen

_NS_ATOM = "http://www.w3.org/2005/Atom"

DEFAULT_FEEDS: list[str] = [
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://techcrunch.com/feed/",
]

_cache: dict[str, tuple[float, list]] = {}   # url → (timestamp, articles)
_lock = threading.Lock()
_TTL = 900   # 15 นาที


def _fetch_feed(url: str, timeout: int = 10) -> list[dict]:
    """ดึง 1 RSS/Atom URL → list of article dict (สูงสุด 20 รายการ)"""
    try:
        with urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        items = root.findall(".//item") or root.findall(f".//{{{_NS_ATOM}}}entry")
        articles: list[dict] = []
        for item in items[:20]:
            def _text(tag: str, atom_tag: str | None = None) -> str:
                el = item.find(tag)
                if el is None and atom_tag:
                    el = item.find(f"{{{_NS_ATOM}}}{atom_tag}")
                return (el.text or "").strip() if el is not None else ""

            title = _text("title", "title")
            link_el = item.find("link") or item.find(f"{{{_NS_ATOM}}}link")
            if link_el is not None:
                link = link_el.get("href") or (link_el.text or "").strip()
            else:
                link = ""
            pub_date = _text("pubDate") or _text("published", "published")

            if title:
                articles.append({"title": title, "link": link,
                                  "pubDate": pub_date, "source": url})
        return articles
    except Exception:
        return []


def get_news(feeds: list[str] | None = None) -> dict:
    """คืน snapshot ข่าว — ดึงจาก cache ถ้ายังไม่หมดอายุ"""
    if feeds is None:
        feeds = DEFAULT_FEEDS
    now = time.time()
    all_articles: list[dict] = []
    errors: list[str] = []
    with _lock:
        for url in feeds:
            cached = _cache.get(url)
            if cached and (now - cached[0]) < _TTL:
                all_articles.extend(cached[1])
            else:
                articles = _fetch_feed(url)
                _cache[url] = (now, articles)
                if articles:
                    all_articles.extend(articles)
                else:
                    errors.append(url)
    return {
        "articles": all_articles,
        "count": len(all_articles),
        "feeds": len(feeds),
        "errors": errors,
        "cached_until": int(now + _TTL),
    }
