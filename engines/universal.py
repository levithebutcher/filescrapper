# engines/universal.py
"""
Universal Fallback Engine.
Handles unknown, unregistered, or arbitrary third-party web pages pasted by users.
Extracts OpenGraph metadata, HTML5 video sources, streaming embed iframes, and file downloads.
"""

import re
import html
import logging
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from config import MAX_TITLE_LENGTH
from engines.base import (
    BaseEngine,
    UniversalSort,
    UniversalDateResolver,
    _fetch_soup,
    _extract_all_image_candidates,
    _is_streaming_link,
    _extract_streaming_links_from_html,
    extract_tags_and_quality,
)

logger = logging.getLogger(__name__)


def is_valid_http_url(url: str) -> bool:
    """Check if URL is a syntactically valid HTTP/HTTPS address."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def get_universal_post_details(url: str) -> dict:
    """
    Best-effort scraper for arbitrary third-party pages:
    Extracts title, thumbnail, publication date, and streaming links.
    """
    soup = _fetch_soup(url)

    # 1. Extract Title
    title = None
    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()

    if not title:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            title = h1.get_text(strip=True)

    if not title and soup.title and soup.title.get_text(strip=True):
        title = soup.title.get_text(strip=True)

    if title:
        title = re.sub(r"\s*[-|•]\s*[\w\.\s]+$", "", title).strip()
        if len(title) > MAX_TITLE_LENGTH:
            title = title[:MAX_TITLE_LENGTH].rstrip() + "..."
    else:
        title = "Discovered Media Post"

    clean_title, tags = extract_tags_and_quality(title)

    # 2. Extract Thumbnail
    thumbnail_candidates = _extract_all_image_candidates(soup, url)
    thumbnail = thumbnail_candidates[0] if thumbnail_candidates else None

    # 3. Extract Streaming / Download Links
    streaming_links = _extract_streaming_links_from_html(soup, url)
    seen = set(streaming_links)

    # Direct <video> and <source> tags
    for v in soup.find_all(["video", "source"], src=True):
        src = v["src"].strip()
        full = urljoin(url, src)
        if full not in seen and _is_streaming_link(full):
            seen.add(full)
            streaming_links.append(full)

    # 4. Resolve Date & Time
    dt_ist, post_date_ist = UniversalDateResolver.resolve(
        soup=soup,
        url=url,
        fallback_db_url=url,
        title=title,
    )
    post_date_raw = dt_ist.isoformat() if dt_ist else None

    domain = urlparse(url).netloc.lower().replace("www.", "")
    platform_name = domain.capitalize() if domain else "Web Video"

    return {
        "title": title,
        "clean_title": clean_title,
        "tags": tags,
        "thumbnail": thumbnail,
        "thumbnail_candidates": thumbnail_candidates,
        "streaming_links": streaming_links,
        "post_url": url,
        "date": post_date_raw,
        "date_ist": post_date_ist,
        "platform_name": platform_name,
        "site": f"web_{domain}",
    }


class UniversalFallbackEngine(BaseEngine):
    """Fallback engine for handling arbitrary third-party URLs."""
    name: str = "UniversalFallback"
    domains: list[str] = []
    supported_sorts: dict[UniversalSort, str] = {
        UniversalSort.NEWEST: "date",
    }

    def is_supported_url(self, url: str) -> bool:
        return is_valid_http_url(url)

    def is_listing_url(self, url: str) -> bool:
        return False

    def is_detail_url(self, url: str) -> bool:
        return is_valid_http_url(url)

    def get_details(self, url: str) -> dict:
        return get_universal_post_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        return []

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        return []
