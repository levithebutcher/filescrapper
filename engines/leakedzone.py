# engines/leakedzone.py
"""
LeakedZone Scraper Engine.
Supports leakedzone.com model archives, video extraction, HLS stream decoding, and search.
"""

import re
import html
import base64
import logging
from urllib.parse import urljoin, quote_plus
from bs4 import BeautifulSoup

from engines.base import (
    BaseEngine,
    UniversalSort,
    UniversalDateResolver,
    _fetch_soup,
    _clean_highres_image_url,
    extract_tags_and_quality,
    format_date_ist,
)

logger = logging.getLogger(__name__)


def is_leakedzone_url(url: str) -> bool:
    """Check if URL belongs to leakedzone.com."""
    if not url or not isinstance(url, str):
        return False
    return "leakedzone.com" in url.lower()


def is_leakedzone_video_url(url: str) -> bool:
    """Check if URL is an individual LeakedZone video page."""
    if not is_leakedzone_url(url):
        return False
    u = url.lower()
    return "/video/" in u


def is_leakedzone_model_url(url: str) -> bool:
    """Check if URL is a LeakedZone model or listing page."""
    if not is_leakedzone_url(url):
        return False
    return not is_leakedzone_video_url(url)


def decode_leakedzone_token(token: str) -> str:
    """
    Crack LeakedZone JWPlayer obfuscation:
    s = s.slice(16); s = s.slice(0, -16); return atob(s.split('').reverse().join(''))
    """
    try:
        if not token or len(token) <= 32:
            return ""
        trimmed = token[16:-16]
        reversed_str = trimmed[::-1]
        decoded = base64.b64decode(reversed_str).decode("utf-8", errors="ignore")
        if decoded.startswith("http"):
            return decoded
        return ""
    except Exception as e:
        logger.debug(f"Error decoding LeakedZone token: {e}")
        return ""


def get_leakedzone_video_details(video_url: str) -> dict:
    """Fetch video details from LeakedZone video page and decode direct HLS .m3u8 stream."""
    soup = _fetch_soup(video_url)
    page_html = str(soup)

    # Title extraction
    h1 = soup.find("h1") or soup.find("span", class_=re.compile(r"title", re.I))
    title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "Untitled Video")
    clean_title, tags = extract_tags_and_quality(title)

    # Model extraction
    model_name = ""
    model_link = soup.find("a", href=re.compile(r"^/[a-zA-Z0-9_-]+$"))
    if model_link and not any(x in model_link["href"] for x in ["/search", "/login", "/register", "/terms"]):
        model_name = model_link.get_text(strip=True)
    if not model_name:
        m = re.search(r"leakedzone\.com/([a-zA-Z0-9_-]+)/video/", video_url, re.I)
        if m:
            model_name = m.group(1).replace("-", " ").title()

    # Thumbnail extraction
    thumbnail = None
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        thumbnail = og_img["content"].strip()

    if not thumbnail:
        poster_m = re.search(r'image:\s*["\']([^"\']+)["\']', page_html)
        if poster_m:
            thumbnail = poster_m.group(1)

    if not thumbnail:
        img_thumb = soup.find("img", class_=re.compile(r"thumb|poster|player", re.I))
        if img_thumb:
            thumbnail = img_thumb.get("src") or img_thumb.get("data-src")

    thumbnail = _clean_highres_image_url(thumbnail) if thumbnail else None

    # Duration & Views extraction
    duration = None
    views = None
    added_date = None

    dur_elem = soup.find(text=re.compile(r"\b\d{1,2}m\s*\d{1,2}s\b|\b\d{1,2}:\d{2}\b"))
    if dur_elem:
        m_dur = re.search(r"\b(\d{1,2}m\s*\d{1,2}s|\d{1,2}:\d{2})\b", str(dur_elem))
        if m_dur:
            duration = m_dur.group(1)

    views_elem = soup.find(text=re.compile(r"\b\d+[\d,.]*\s*(?:K|M|views)\b", re.I))
    if views_elem:
        m_v = re.search(r"([\d,.]+\s*(?:K|M|views)?)", str(views_elem), re.I)
        if m_v:
            views = m_v.group(1).strip()

    # Stream link extraction via cracked JWPlayer token or direct .m3u8
    streaming_link = None
    # 1. Match f("...") pattern
    f_matches = re.findall(r'f\(["\']([A-Za-z0-9+/=]{30,})["\']\)', page_html)
    for tok in f_matches:
        decoded = decode_leakedzone_token(tok)
        if decoded and ".m3u8" in decoded:
            streaming_link = decoded
            break

    # 2. Fallback direct .m3u8 search
    if not streaming_link:
        m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', page_html)
        if m3u8_matches:
            streaming_link = m3u8_matches[0]

    # Date resolution
    dt_ist, date_display = UniversalDateResolver.resolve(
        soup=soup,
        url=video_url,
        fallback_db_url=video_url,
        title=title,
    )
    post_date_raw = dt_ist.isoformat() if dt_ist else None

    return {
        "title": title,
        "clean_title": clean_title,
        "model_name": model_name,
        "tags": tags,
        "duration": duration,
        "views": views,
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_link": streaming_link,
        "streaming_links": [streaming_link] if streaming_link else [],
        "post_url": video_url,
        "date": post_date_raw,
        "date_ist": date_display or "Recently",
        "platform_name": "LeakedZone",
        "site": "leakedzone",
    }


def get_leakedzone_model_videos(
    model_or_url: str,
    sort: str = "newest",
    page: int = 1,
    limit: int = 25,
) -> list[dict]:
    """
    Fetch video listing for a LeakedZone model.
    sort can be: 'newest' (latest), 'views' (most viewed), 'longest' (longest duration)
    """
    if model_or_url.startswith("http"):
        base_url = model_or_url.split("?")[0].rstrip("/")
    else:
        slug = model_or_url.strip().strip("/").lower()
        base_url = f"https://leakedzone.com/{slug}"

    params = []
    if sort == "views":
        params.append("sort=views")
    elif sort == "longest":
        params.append("sort=longest")
    elif sort == "newest":
        params.append("sort=latest")

    if page > 1:
        params.append(f"page={page}")

    query_str = ("?" + "&".join(params)) if params else ""
    target_url = f"{base_url}{query_str}"

    soup = _fetch_soup(target_url)
    items = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/video/" in href:
            full_url = urljoin("https://leakedzone.com", href)
            if full_url in seen:
                continue
            seen.add(full_url)

            # Find title
            title = a.get("title") or a.get_text(strip=True)
            if not title:
                parent = a.find_parent(["div", "article", "li"])
                if parent:
                    t_el = parent.find(["h2", "h3", "h4", "span", "p"])
                    if t_el:
                        title = t_el.get_text(strip=True)
            if not title:
                title = "LeakedZone Video"

            # Thumbnail
            thumb = None
            img = a.find("img")
            if img:
                thumb = img.get("data-src") or img.get("src")
            if thumb:
                thumb = urljoin("https://leakedzone.com", thumb)

            # Duration
            duration = None
            parent = a.find_parent(["div", "article", "li"])
            if parent:
                dur_el = parent.find(class_=re.compile(r"duration|time", re.I))
                if dur_el:
                    duration = dur_el.get_text(strip=True)

            items.append({
                "title": title,
                "url": full_url,
                "thumbnail": thumb,
                "duration": duration,
                "date": None,
                "date_ist": None,
            })
            if len(items) >= limit:
                break

    return items


def search_leakedzone(query: str, page: int = 1, limit: int = 25) -> list[dict]:
    """Search videos on LeakedZone."""
    encoded_q = quote_plus(query.strip())
    search_url = f"https://leakedzone.com/search?q={encoded_q}"
    if page > 1:
        search_url += f"&page={page}"
    return get_leakedzone_model_videos(search_url, page=1, limit=limit)


class LeakedZoneEngine(BaseEngine):
    """LeakedZone Scraper Engine."""
    name: str = "LeakedZone"
    domains: list[str] = ["leakedzone.com"]
    supported_sorts: dict[UniversalSort, str] = {
        UniversalSort.NEWEST: "newest",
        UniversalSort.MOST_VIEWED: "views",
        UniversalSort.LONGEST: "longest",
    }

    def is_listing_url(self, url: str) -> bool:
        return is_leakedzone_model_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_leakedzone_video_url(url)

    def get_details(self, url: str) -> dict:
        return get_leakedzone_video_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        sort = kwargs.get("sort", "newest")
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 25)
        return get_leakedzone_model_videos(url, sort=sort, page=page, limit=limit)

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        page = kwargs.get("page", 1)
        return search_leakedzone(query, page=page, limit=limit)
