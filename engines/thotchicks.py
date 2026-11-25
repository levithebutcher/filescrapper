# engines/thotchicks.py
"""
ThotChicks Scraper Engine.
Supports thotchicks.com actor galleries, video pages, embed decryption, sorting, and search.
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


def is_thotchicks_url(url: str) -> bool:
    """Check if URL belongs to thotchicks.com."""
    if not url or not isinstance(url, str):
        return False
    return "thotchicks.com" in url.lower()


def is_thotchicks_actor_url(url: str) -> bool:
    """Check if URL is an actor archive or category/search listing."""
    if not is_thotchicks_url(url):
        return False
    u = url.lower()
    return "/actor/" in u or "/actors/" in u or "?s=" in u or "/category/" in u or "/tag/" in u


def is_thotchicks_video_url(url: str) -> bool:
    """Check if URL is an individual video page on thotchicks.com."""
    if not is_thotchicks_url(url):
        return False
    return not is_thotchicks_actor_url(url)


def get_thotchicks_video_details(video_url: str) -> dict:
    """Fetch video details from ThotChicks post, extracting embedded player and metadata."""
    soup = _fetch_soup(video_url)
    page_html = str(soup)

    # Title extraction
    h1 = soup.find("h1") or soup.find("h1", class_=re.compile(r"title|entry-title", re.I))
    title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "Untitled Video")
    clean_title, tags = extract_tags_and_quality(title)

    # Actor extraction
    actor_name = ""
    actor_link = soup.find("a", href=re.compile(r"/actor/[^/]+"))
    if actor_link:
        actor_name = actor_link.get_text(strip=True)

    # Duration extraction
    duration = None
    dur_elem = soup.find(class_=re.compile(r"duration|time", re.I))
    if dur_elem:
        duration = dur_elem.get_text(strip=True)
    if not duration:
        m_dur = re.search(r"\b(\d{1,2}m\s*\d{1,2}s|\d{1,2}:\d{2})\b", page_html)
        if m_dur:
            duration = m_dur.group(1)

    # Thumbnail extraction
    thumbnail = None
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        thumbnail = og_img["content"].strip()

    if not thumbnail:
        v_tag = soup.find("video")
        if v_tag and v_tag.get("poster"):
            thumbnail = v_tag["poster"].strip()

    if not thumbnail:
        img_thumb = soup.find("img", class_=re.compile(r"thumb|poster|attachment", re.I))
        if img_thumb:
            thumbnail = img_thumb.get("src") or img_thumb.get("data-src")

    thumbnail = _clean_highres_image_url(thumbnail) if thumbnail else None

    # Embed / Stream extraction
    streaming_link = None
    # 1. Look for thotplay iframe
    iframes = soup.find_all("iframe", src=True)
    for ifr in iframes:
        src = ifr["src"].strip()
        if "thotplay.com" in src:
            streaming_link = src if src.startswith("http") else f"https:{src}"
            break

    # 2. Look for any embedded video or .m3u8 source
    if not streaming_link:
        m3u8_matches = re.findall(r"https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*", page_html)
        if m3u8_matches:
            streaming_link = m3u8_matches[0]

    # 3. Look for other player iframes
    if not streaming_link:
        for ifr in iframes:
            src = ifr["src"].strip()
            if not any(x in src for x in ["ads", "banner", "doubleclick"]):
                streaming_link = src if src.startswith("http") else f"https:{src}"
                break

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
        "actor_name": actor_name,
        "model_name": actor_name,
        "tags": tags,
        "duration": duration,
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_link": streaming_link,
        "streaming_links": [streaming_link] if streaming_link else [],
        "post_url": video_url,
        "date": post_date_raw,
        "date_ist": date_display or "Recently",
        "platform_name": "ThotChicks",
        "site": "thotchicks",
    }


def get_thotchicks_listing_items(
    listing_url: str,
    sort: str = "newest",
    page: int = 1,
    limit: int = 25,
) -> list[dict]:
    """Fetch video items from ThotChicks actor, category, or search archive."""
    base_url = listing_url.split("?")[0].rstrip("/")

    params = []
    if sort == "views":
        params.append("filter=most-viewed")
    elif sort == "longest":
        params.append("filter=longest")
    elif sort == "newest":
        params.append("filter=latest")

    if page > 1:
        base_url = f"{base_url}/page/{page}"

    query_str = ("?" + "&".join(params)) if params else ""
    target_url = f"{base_url}/{query_str}"

    soup = _fetch_soup(target_url)
    items = []
    seen = set()

    articles = soup.find_all("article")
    if not articles:
        articles = soup.find_all("div", class_=re.compile(r"item|post|video", re.I))

    for art in articles:
        link = art.find("a", href=True)
        if not link:
            continue
        href = link["href"].strip()
        if not href.startswith("http"):
            href = urljoin("https://thotchicks.com", href)

        if href in seen or "/actor/" in href or "/category/" in href or href == "https://thotchicks.com/":
            continue
        seen.add(href)

        # Title
        title = link.get("title") or link.get_text(strip=True)
        h_el = art.find(["h2", "h3", "h4", "span", "p"])
        if h_el and len(h_el.get_text(strip=True)) > len(title):
            title = h_el.get_text(strip=True)
        if not title:
            title = "ThotChicks Video"

        # Thumbnail
        thumb = None
        img = art.find("img")
        if img:
            thumb = img.get("data-src") or img.get("src")
        if thumb and not thumb.startswith("http"):
            thumb = urljoin("https://thotchicks.com", thumb)

        # Duration
        duration = None
        dur_el = art.find(class_=re.compile(r"duration|time", re.I))
        if dur_el:
            duration = dur_el.get_text(strip=True)

        items.append({
            "title": title,
            "url": href,
            "thumbnail": thumb,
            "duration": duration,
            "date": None,
            "date_ist": None,
        })
        if len(items) >= limit:
            break

    return items


def search_thotchicks(query: str, page: int = 1, limit: int = 25) -> list[dict]:
    """Search videos on ThotChicks."""
    encoded_q = quote_plus(query.strip())
    search_url = f"https://thotchicks.com/?s={encoded_q}"
    return get_thotchicks_listing_items(search_url, page=page, limit=limit)


def search_thotchicks_actors(query: str, limit: int = 10) -> list[dict]:
    """Search actors on ThotChicks (LiveCam style)."""
    clean_q = query.strip()
    if not clean_q:
        return []

    actors = []
    seen = set()

    # 1. Candidate direct slug
    cand_slug = re.sub(r"[^a-zA-Z0-9_-]", "", clean_q.lower().replace(" ", "-"))
    cand_url = f"https://thotchicks.com/actor/{cand_slug}/"
    soup = _fetch_soup(cand_url)
    if soup and soup.title and "404" not in soup.title.get_text() and "not found" not in soup.title.get_text().lower():
        name = clean_q.title()
        if soup.title:
            t_raw = soup.title.get_text(strip=True)
            if "OnlyFans" in t_raw:
                name = t_raw.split("OnlyFans")[0].strip(" –-")
        seen.add(cand_slug)
        actors.append({
            "name": name,
            "url": cand_url,
            "slug": cand_slug,
        })

    # 2. Search query page extraction for actor links
    query_tokens = [w.lower() for w in re.findall(r"\w+", clean_q) if len(w) > 1]
    if len(actors) < limit:
        search_url = f"https://thotchicks.com/?s={quote_plus(clean_q)}"
        s_soup = _fetch_soup(search_url)
        if s_soup:
            for a in s_soup.find_all("a", href=True):
                href = a["href"].strip()
                if "/actor/" in href:
                    full_url = urljoin("https://thotchicks.com", href).split("?")[0].rstrip("/") + "/"
                    if full_url.endswith("/actors/"):
                        continue
                    slug = full_url.rstrip("/").split("/")[-1]
                    if not slug or slug in seen:
                        continue
                    name = a.get_text(strip=True) or slug.replace("-", " ").title()
                    if query_tokens and not any(t in slug.lower() or t in name.lower() for t in query_tokens):
                        continue
                    seen.add(slug)
                    actors.append({
                        "name": name,
                        "url": full_url,
                        "slug": slug,
                    })
                    if len(actors) >= limit:
                        break

    return actors


class ThotChicksEngine(BaseEngine):
    """ThotChicks Scraper Engine."""
    name: str = "ThotChicks"
    domains: list[str] = ["thotchicks.com"]
    supported_sorts: dict[UniversalSort, str] = {
        UniversalSort.NEWEST: "newest",
        UniversalSort.MOST_VIEWED: "views",
        UniversalSort.LONGEST: "longest",
    }

    def is_listing_url(self, url: str) -> bool:
        return is_thotchicks_actor_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_thotchicks_video_url(url)

    def get_details(self, url: str) -> dict:
        return get_thotchicks_video_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        sort = kwargs.get("sort", "newest")
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 25)
        return get_thotchicks_listing_items(url, sort=sort, page=page, limit=limit)

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        page = kwargs.get("page", 1)
        return search_thotchicks(query, page=page, limit=limit)
