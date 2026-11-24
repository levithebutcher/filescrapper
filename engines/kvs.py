# engines/kvs.py
"""
KVS (Kernel Video Sharing) Scraper Engine.
Specialized for tube platforms built on KVS CMS:
- X-Video Tube (x-video.tube)
- HornySapiens (hornysapiens.com)
- ViralXXXPorn (viralxxxporn.com)
Extracts direct CDN MP4 streams, quality tags, models, duration, and handles sorting & search.
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


def is_kvs_url(url: str) -> bool:
    """Check if URL belongs to any supported KVS tube site."""
    if not url or not isinstance(url, str):
        return False
    u = url.lower()
    return any(d in u for d in ["x-video.tube", "hornysapiens.com", "viralxxxporn.com"])


def is_kvs_video_url(url: str) -> bool:
    """Check if URL is an individual video page on KVS sites."""
    if not is_kvs_url(url):
        return False
    u = url.lower()
    return "/video/" in u or "/videos/" in u


def is_kvs_listing_url(url: str) -> bool:
    """Check if URL is a tag, model, category, or search listing page."""
    if not is_kvs_url(url):
        return False
    return not is_kvs_video_url(url)


def clean_kvs_video_url(raw_url: str) -> str:
    """Clean obfuscated function wrapper from KVS flashvars video URL."""
    if not raw_url:
        return ""
    # Strip function/0/ or function/X/ prefix commonly found in KVS
    cleaned = re.sub(r"^function/\d+/", "", raw_url.strip())
    # Strip trailing slashes after mp4 if present
    cleaned = re.sub(r"(\.mp4)/+$", r"\1", cleaned)
    return cleaned


def get_kvs_video_details(video_url: str) -> dict:
    """Fetch video details from KVS video page and extract direct MP4 stream."""
    soup = _fetch_soup(video_url)
    page_html = str(soup)

    u_low = video_url.lower()
    if "x-video.tube" in u_low:
        site_key = "xvideotube"
        platform_name = "X-Video Tube"
    elif "viralxxxporn" in u_low:
        site_key = "viralxxxporn"
        platform_name = "ViralXXXPorn"
    else:
        site_key = "hornysapiens"
        platform_name = "HornySapiens"

    # Title extraction
    h1 = soup.find("h1") or soup.find("span", class_=re.compile(r"headline|title", re.I))
    title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "Untitled Video")
    clean_title, tags = extract_tags_and_quality(title)

    # Model / Actor or Tag extraction
    model_name = ""
    model_link = soup.find("a", href=re.compile(r"/models/|/tags/"))
    if model_link:
        model_name = model_link.get_text(strip=True)
    if not model_name:
        m_mod = re.search(r"/(?:models|tags)/([^/]+)/", video_url)
        if m_mod:
            model_name = m_mod.group(1).replace("-", " ").title()

    # Duration extraction
    duration = None
    dur_elem = soup.find(class_=re.compile(r"duration|time", re.I))
    if dur_elem:
        duration = dur_elem.get_text(strip=True)
    if not duration:
        m_dur = re.search(r"duration:\s*['\"]([^'\"]+)['\"]", page_html)
        if m_dur:
            duration = m_dur.group(1)
        else:
            m_sec = re.search(r"video_duration:\s*['\"]?(\d+)['\"]?", page_html)
            if m_sec:
                secs = int(m_sec.group(1))
                duration = f"{secs // 60:02d}m {secs % 60:02d}s"

    # Quality extraction
    quality = "1080p Full HD" if "1080p" in page_html or "1080" in title else ("720p HD" if "720" in page_html else None)

    # Views extraction
    views = None
    views_elem = soup.find(class_=re.compile(r"views", re.I))
    if views_elem:
        m_v = re.search(r"([\d,.]+\s*(?:K|M|views)?)", views_elem.get_text(strip=True), re.I)
        if m_v:
            views = m_v.group(1).strip()

    # Direct MP4 extraction from flashvars / script / video tag
    streaming_link = None
    # 1. Look for video_url in flashvars
    v_matches = re.findall(r"video_url:\s*['\"]([^'\"]+)['\"]", page_html)
    for vm in v_matches:
        cand = clean_kvs_video_url(vm)
        if cand.startswith("http") and ".mp4" in cand:
            streaming_link = cand
            break

    # 2. Look for video_alt_url in flashvars
    if not streaming_link:
        v_alt = re.findall(r"video_alt_url:\s*['\"]([^'\"]+)['\"]", page_html)
        for vm in v_alt:
            cand = clean_kvs_video_url(vm)
            if cand.startswith("http") and ".mp4" in cand:
                streaming_link = cand
                break

    # 3. Look for video or source tag
    if not streaming_link:
        for src_tag in soup.find_all(["video", "source"], src=True):
            cand = src_tag["src"].strip()
            if ".mp4" in cand:
                streaming_link = cand
                break

    # 4. Fallback: regex search for CDN mp4
    if not streaming_link:
        mp4_matches = re.findall(r"https?://[^\s\"'<>]+\.mp4[^\s\"'<>]*", page_html)
        for m4 in mp4_matches:
            if not any(x in m4 for x in ["preview", "trailer", "banner"]):
                streaming_link = m4
                break

    # Thumbnail extraction
    thumbnail = None
    preview_match = re.search(r"preview_url:\s*['\"]([^'\"]+)['\"]", page_html)
    if preview_match:
        thumbnail = preview_match.group(1).strip()
    if not thumbnail:
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            thumbnail = og_img["content"].strip()
    if not thumbnail:
        v_tag = soup.find("video")
        if v_tag and v_tag.get("poster"):
            thumbnail = v_tag["poster"].strip()

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
        "model_name": model_name,
        "quality": quality,
        "duration": duration,
        "views": views,
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_link": streaming_link,
        "streaming_links": [streaming_link] if streaming_link else [],
        "post_url": video_url,
        "date": post_date_raw,
        "date_ist": date_display or "Recently",
        "platform_name": platform_name,
        "site": site_key,
    }


def get_kvs_listing_items(
    listing_url: str,
    sort: str = "latest",
    page: int = 1,
    limit: int = 25,
) -> list[dict]:
    """Fetch video items from KVS listing page (tag, model, search)."""
    base_url = listing_url.split("?")[0].rstrip("/")
    u_low = base_url.lower()

    params = []
    if "x-video.tube" in u_low:
        if sort == "longest":
            params.append("by=duration")
        else:
            params.append("by=post_date")
    else:  # Hornysapiens / ViralXXXPorn
        if sort == "views":
            params.append("sort_by=video_viewed")
        elif sort == "longest":
            params.append("sort_by=duration")
        else:
            params.append("sort_by=post_date")

    if page > 1:
        if "x-video.tube" in u_low:
            base_url = f"{base_url}/{page}"
        else:
            params.append(f"from={page:02d}")

    query_str = ("?" + "&".join(params)) if params else ""
    target_url = f"{base_url}/{query_str}"

    soup = _fetch_soup(target_url)
    items = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/video/" in href or "/videos/" in href:
            full_url = urljoin(target_url, href)
            if full_url in seen or full_url.endswith("/videos/"):
                continue
            seen.add(full_url)

            # Title
            title = a.get("title") or a.get_text(strip=True)
            if not title:
                parent = a.find_parent(["div", "article", "li"])
                if parent:
                    t_el = parent.find(["strong", "span", "h3", "h4"])
                    if t_el:
                        title = t_el.get_text(strip=True)
            if not title or title.lower() in ("video", "watch"):
                continue

            # Thumbnail
            thumb = None
            img = a.find("img")
            if img:
                thumb = img.get("data-src") or img.get("data-original") or img.get("src")
            if thumb:
                thumb = urljoin(target_url, thumb)

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


def search_kvs(site_key: str, query: str, page: int = 1, limit: int = 25) -> list[dict]:
    """Search videos on KVS site."""
    encoded_q = quote_plus(query.strip())
    if site_key == "xvideotube":
        search_url = f"https://x-video.tube/search/{encoded_q}/"
    elif site_key == "viralxxxporn":
        search_url = f"https://viralxxxporn.com/search/{encoded_q}/"
    else:
        search_url = f"https://hornysapiens.com/search/{encoded_q}/"
    return get_kvs_listing_items(search_url, page=page, limit=limit)


class KvsEngine(BaseEngine):
    """Unified KVS Tube Engine."""
    name: str = "KVSTube"
    domains: list[str] = ["x-video.tube", "hornysapiens.com", "viralxxxporn.com"]
    supported_sorts: dict[UniversalSort, str] = {
        UniversalSort.NEWEST: "latest",
        UniversalSort.MOST_VIEWED: "views",
        UniversalSort.LONGEST: "longest",
    }

    def is_listing_url(self, url: str) -> bool:
        return is_kvs_listing_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_kvs_video_url(url)

    def get_details(self, url: str) -> dict:
        return get_kvs_video_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        sort = kwargs.get("sort", "latest")
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 25)
        return get_kvs_listing_items(url, sort=sort, page=page, limit=limit)

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        site_key = kwargs.get("site_key", "hornysapiens")
        page = kwargs.get("page", 1)
        return search_kvs(site_key, query, page=page, limit=limit)
