"""
news_store.py — RSS feed fetcher พร้อม 15-min in-memory cache (stdlib only)

get_news(feeds)  → {"articles": [...], "count": int, "feeds": int,
                     "errors": [...], "cached_until": int}
_fetch_feed(url) → list[dict]  — monkeypatch ได้ในเทส
"""

import ipaddress
import socket
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

_NS_ATOM = "http://www.w3.org/2005/Atom"

# Allowlist: clients pick a feed by key only (?feed=bbci) — never by URL (SSRF guard)
DEFAULT_FEEDS: dict[str, str] = {
    "bbci": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "techcrunch": "https://techcrunch.com/feed/",
}


class UnknownFeed(ValueError):
    """Raised when a feed key is not in DEFAULT_FEEDS."""


def resolve_feeds(keys: list[str] | None) -> list[str]:
    """Map feed keys to allowlisted URLs. None/empty -> all defaults; unknown -> UnknownFeed."""
    if not keys:
        return list(DEFAULT_FEEDS.values())
    urls: list[str] = []
    for key in keys:
        url = DEFAULT_FEEDS.get(str(key).strip().lower())
        if url is None:
            raise UnknownFeed(f"unknown feed: choose one of {sorted(DEFAULT_FEEDS)}")
        if url not in urls:
            urls.append(url)
    return urls


def _host_is_public(host: str | None) -> bool:
    """True only if every address the host resolves to is a public unicast IP."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


def _url_allowed(url: str) -> bool:
    """http(s) to a public host only (no file://, loopback, LAN, link-local)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and _host_is_public(parsed.hostname)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to public http(s) hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _url_allowed(newurl):
            raise urllib.error.URLError(f"redirect blocked: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# no FileHandler/FTPHandler: only http(s) can ever be opened
_OPENER = urllib.request.OpenerDirector()
for _h in (urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(), _SafeRedirect(),
           urllib.request.HTTPErrorProcessor(), urllib.request.HTTPDefaultErrorHandler()):
    _OPENER.add_handler(_h)


def urlopen(url: str, timeout: int = 10):
    """Open url through the guarded opener (tests may patch this name)."""
    return _OPENER.open(url, timeout=timeout)

_cache: dict[str, tuple[float, list]] = {}   # url → (timestamp, articles)
_lock = threading.Lock()
_TTL = 900   # 15 นาที


def _fetch_feed(url: str, timeout: int = 10) -> list[dict]:
    """ดึง 1 RSS/Atom URL → list of article dict (สูงสุด 20 รายการ)"""
    # callers pass allowlisted URLs only; redirects are host-checked by _SafeRedirect
    if urlparse(str(url)).scheme not in ("http", "https"):
        return []
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
        feeds = list(DEFAULT_FEEDS.values())
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
