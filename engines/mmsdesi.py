# engines/mmsdesi.py
"""
MMSDesi Scraper Engine.
Specialized for mmsdesi.me Next.js video portal.
Extracts direct CDN MP4 streams, attached photo albums, and supports 4 primary categories:
Trending, Desi New, Desi Old, Tango Strip.
"""

import re
import html
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

MMSDESI_CATEGORIES = {
    "trending": {"name": "Trending", "path": "/trending", "icon": "🔥"},
    "desi-new": {"name": "Desi New", "path": "/desi-new", "icon": "⚡"},
    "desi-old": {"name": "Desi Old", "path": "/desi-old-videos", "icon": "📦"},
    "tango-strip": {"name": "Tango Strip", "path": "/tango-strip", "icon": "💃"},
}


def is_mmsdesi_url(url: str) -> bool:
    """Check if URL belongs to mmsdesi.me."""
    if not url or not isinstance(url, str):
        return False
    return "mmsdesi.me" in url.lower()


def is_mmsdesi_video_url(url: str) -> bool:
    """Check if URL represents an individual video on MMSDesi."""
    if not is_mmsdesi_url(url):
        return False
    u = url.lower().split("?")[0].rstrip("/")
    if any(u.endswith(cat["path"]) for cat in MMSDESI_CATEGORIES.values()):
        return False
    if u in ["https://www.mmsdesi.me", "https://mmsdesi.me", "http://www.mmsdesi.me", "http://mmsdesi.me"]:
        return False
    return "/watch/" in u or "/video/" in u or bool(re.search(r"mmsdesi\.me/[^/]+/[^/]+", u))


def is_mmsdesi_listing_url(url: str) -> bool:
    """Check if URL represents an MMSDesi category or search archive."""
    if not is_mmsdesi_url(url):
        return False
    return not is_mmsdesi_video_url(url)


def get_mmsdesi_video_details(video_url: str) -> dict:
    """Fetch video details from MMSDesi, extracting direct CDN MP4 and attached photo album."""
    soup = _fetch_soup(video_url)
    page_html = str(soup)

    # Title extraction
    h1 = soup.find("h1") or soup.find("span", class_=re.compile(r"title|headline", re.I))
    title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "Untitled Video")
    clean_title, tags = extract_tags_and_quality(title)

    # Category extraction
    category = "Desi New"
    for cat_key, cat_info in MMSDESI_CATEGORIES.items():
        if cat_info["path"] in video_url or cat_key in video_url.lower():
            category = cat_info["name"]
            break
    cat_elem = soup.find("a", href=re.compile(r"/category/|/desi-|/trending|/tango-"))
    if cat_elem:
        c_text = cat_elem.get_text(strip=True)
        if c_text and len(c_text) < 30:
            category = c_text

    # Duration extraction
    duration = None
    dur_elem = soup.find(class_=re.compile(r"duration|time", re.I))
    if dur_elem:
        duration = dur_elem.get_text(strip=True)
    if not duration:
        m_dur = re.search(r"\b(\d{1,2}m\s*\d{1,2}s|\d{1,2}:\d{2})\b", page_html)
        if m_dur:
            duration = m_dur.group(1)

    # Views extraction
    views = None
    views_elem = soup.find(class_=re.compile(r"views", re.I))
    if views_elem:
        m_v = re.search(r"([\d,.]+\s*(?:K|M|views)?)", views_elem.get_text(strip=True), re.I)
        if m_v:
            views = m_v.group(1).strip()

    # Direct CDN MP4 video extraction
    streaming_link = None
    mp4_matches = re.findall(r"https?://[^\s\"'<>]+\.mp4[^\s\"'<>]*", page_html)
    for m4 in mp4_matches:
        cleaned_m4 = re.sub(r"[\\]+$", "", m4).strip()
        if "cdn.mmsdesi.me" in cleaned_m4 or "mmsdesi.me" in cleaned_m4:
            streaming_link = cleaned_m4
            break
    if not streaming_link and mp4_matches:
        streaming_link = re.sub(r"[\\]+$", "", mp4_matches[0]).strip()

    # Attached Photo Album extraction (direct CDN images)
    attached_photos = []
    seen_photos = set()
    img_matches = re.findall(r"https?://[^\s\"'<>]+\.(?:jpg|jpeg|webp|png)[^\s\"'<>]*", page_html)
    for img_url in img_matches:
        cleaned_img = re.sub(r"[\\]+$", "", img_url).strip()
        if ("photos/" in cleaned_img or "gallery" in cleaned_img) and "cdn.mmsdesi.me" in cleaned_img:
            if cleaned_img not in seen_photos:
                seen_photos.add(cleaned_img)
                attached_photos.append(cleaned_img)

    # If none found by regex, inspect <img> tags in main content
    if not attached_photos:
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src and any(ext in src.lower() for ext in [".jpg", ".jpeg", ".webp"]):
                if not any(x in src for x in ["logo", "icon", "avatar", "og-image"]):
                    full_src = urljoin(video_url, src)
                    if full_src not in seen_photos and "cdn.mmsdesi.me/photos/" in full_src:
                        seen_photos.add(full_src)
                        attached_photos.append(full_src)

    # Thumbnail extraction
    thumbnail = None
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        thumbnail = og_img["content"].strip()
    if not thumbnail and attached_photos:
        thumbnail = attached_photos[0]

    thumbnail = _clean_highres_image_url(thumbnail) if thumbnail else None

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
        "category": category,
        "category_name": category,
        "duration": duration,
        "views": views,
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_link": streaming_link,
        "streaming_links": [streaming_link] if streaming_link else [],
        "attached_photos": attached_photos[:10],  # limit to top 10 photos
        "attached_videos": [],  # MMSDesi does not have attached video parts
        "post_url": video_url,
        "date": post_date_raw,
        "date_ist": date_display or "Today",
        "platform_name": "MMSDesi",
        "site": "mmsdesi",
    }


def get_mmsdesi_category_videos(
    category_key_or_url: str,
    page: int = 1,
    limit: int = 25,
) -> list[dict]:
    """Fetch video items from MMSDesi category or search page."""
    if category_key_or_url.startswith("http"):
        base_url = category_key_or_url.split("?")[0].rstrip("/")
    else:
        cat_info = MMSDESI_CATEGORIES.get(category_key_or_url.lower().strip())
        path = cat_info["path"] if cat_info else f"/{category_key_or_url.strip('/')}"
        base_url = f"https://www.mmsdesi.me{path}"

    target_url = base_url
    if page > 1:
        target_url = f"{base_url}?page={page}"

    soup = _fetch_soup(target_url)
    items = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/watch/" in href or "/video/" in href:
            full_url = urljoin("https://www.mmsdesi.me", href)
            if full_url in seen:
                continue
            seen.add(full_url)

            # Title
            title = a.get("title") or a.get_text(strip=True)
            parent = a.find_parent(["div", "article", "li"])
            if parent:
                t_el = parent.find(["h2", "h3", "h4", "p", "span"])
                if t_el and len(t_el.get_text(strip=True)) > len(title):
                    title = t_el.get_text(strip=True)
            if not title or title.lower() in ("video", "watch"):
                continue

            # Thumbnail
            thumb = None
            img = a.find("img")
            if img:
                thumb = img.get("src") or img.get("data-src")
            if thumb and not thumb.startswith("http"):
                thumb = urljoin("https://www.mmsdesi.me", thumb)

            # Duration
            duration = None
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


def search_mmsdesi(query: str, page: int = 1, limit: int = 25) -> list[dict]:
    """Search videos on MMSDesi."""
    encoded_q = quote_plus(query.strip())
    search_url = f"https://www.mmsdesi.me/search?q={encoded_q}"
    return get_mmsdesi_category_videos(search_url, page=page, limit=limit)


class MmsDesiEngine(BaseEngine):
    """MMSDesi Scraper Engine."""
    name: str = "MMSDesi"
    domains: list[str] = ["mmsdesi.me", "www.mmsdesi.me"]
    supported_sorts: dict[UniversalSort, str] = {
        UniversalSort.NEWEST: "latest",
    }

    def is_listing_url(self, url: str) -> bool:
        return is_mmsdesi_listing_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_mmsdesi_video_url(url)

    def get_details(self, url: str) -> dict:
        return get_mmsdesi_video_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 25)
        return get_mmsdesi_category_videos(url, page=page, limit=limit)

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        page = kwargs.get("page", 1)
        return search_mmsdesi(query, page=page, limit=limit)
