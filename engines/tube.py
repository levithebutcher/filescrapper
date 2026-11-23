# engines/tube.py
"""
Media Tube Engine.
Specialized for direct-streaming tube sites like MMSVibex (mmsvibex.life)
supporting direct CDN MP4, ZIP photo albums, and actor collections.
"""

import re
import html
import logging
from urllib.parse import urljoin, quote_plus
from bs4 import BeautifulSoup

from engines.base import (
    BaseEngine,
    _fetch_soup,
    _clean_highres_image_url,
    extract_tags_and_quality,
    format_date_ist,
)

logger = logging.getLogger(__name__)


def is_mmsvibex_url(url: str) -> bool:
    """Check if URL belongs to mmsvibex.life."""
    if not url or not isinstance(url, str):
        return False
    return "mmsvibex.life" in url.lower()


def is_mmsvibex_photo_url(url: str) -> bool:
    """Check if URL represents an individual MMSVibex photo album."""
    if not is_mmsvibex_url(url):
        return False
    u = url.lower().split("?")[0].rstrip("/")
    if u in ["https://mmsvibex.life/photos", "http://mmsvibex.life/photos"]:
        return False
    return "/photos/" in u or "/album/" in u


def is_mmsvibex_listing_url(url: str) -> bool:
    """Check if URL represents an MMSVibex listing, archive, or category page."""
    if not is_mmsvibex_url(url):
        return False
    u = url.lower().strip()
    clean_u = u.split("?")[0].rstrip("/")
    if clean_u in ["https://mmsvibex.life", "http://mmsvibex.life", "https://mmsvibex.life/photos", "http://mmsvibex.life/photos"]:
        return True
    return bool(
        re.search(r"[?&]filter=", u, re.I)
        or "/page/" in u
        or "/category/" in u
        or "/tag/" in u
        or "/actors/" in u
        or "/actor/" in u
    )


def is_mmsvibex_video_url(url: str) -> bool:
    """Check if URL represents an individual MMSVibex video page."""
    return is_mmsvibex_url(url) and not is_mmsvibex_photo_url(url) and not is_mmsvibex_listing_url(url)


def get_mmsvibex_video_details(video_url: str) -> dict:
    """Fetch video details from MMSVibex video page including direct CDN MP4, attached photo albums, and actor collection."""
    soup = _fetch_soup(video_url)

    h1 = soup.find("h1") or soup.find("span", class_="title")
    title = h1.get_text(strip=True) if h1 else "Untitled Video"
    clean_title, tags = extract_tags_and_quality(title)

    thumbnail = None
    v_tag = soup.find("video")
    if v_tag and v_tag.get("poster"):
        thumbnail = v_tag["poster"].strip()
    if not thumbnail:
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            thumbnail = og["content"].strip()
    if not thumbnail:
        img_thumb = soup.find("img", class_=re.compile(r"video-main-thumb|attachment-post-thumbnail", re.I))
        if img_thumb:
            thumbnail = img_thumb.get("src") or img_thumb.get("data-src")

    thumbnail = _clean_highres_image_url(thumbnail) if thumbnail else None

    duration = None
    dur_elem = soup.find("span", class_=re.compile(r"duration", re.I))
    if dur_elem:
        duration = dur_elem.get_text(strip=True)

    streaming_links = []
    seen = set()

    main_v = soup.find("video", id="wpst-video") or soup.find("video")
    if main_v:
        for s_tag in main_v.find_all("source"):
            src = s_tag.get("src", "").strip()
            if src and ".mp4" in src.lower() and "trailer" not in src.lower():
                if src not in seen:
                    seen.add(src)
                    streaming_links.append(src)
        if not streaming_links and main_v.get("src"):
            vsrc = main_v["src"].strip()
            if vsrc and ".mp4" in vsrc.lower() and "trailer" not in vsrc.lower():
                if vsrc not in seen:
                    seen.add(vsrc)
                    streaming_links.append(vsrc)

    if not streaming_links:
        content_container = soup.find("div", id=re.compile(r"video-player|wpst-video", re.I)) or soup.find("article")
        if content_container:
            for m in re.finditer(r'https?://[^\s"\'<>]+\.mp4(?:\?[^\s"\'<>]*)?', str(content_container)):
                mp4_url = m.group(0)
                if "trailer" not in mp4_url.lower() and mp4_url not in seen:
                    seen.add(mp4_url)
                    streaming_links.append(mp4_url)

    attached_photo_albums = []
    seen_albums = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full_href = urljoin(video_url, href)
        if "/photos/" in full_href and full_href.rstrip("/") != "https://mmsvibex.life/photos":
            if full_href not in seen_albums:
                seen_albums.add(full_href)
                album_text = a.get_text(strip=True)
                if not album_text or album_text.lower() == "photos":
                    album_text = "Photo Album"
                clean_album_text = re.sub(r"^Photos from this (?:video and )?album", "", album_text, flags=re.I).strip()
                if not clean_album_text:
                    clean_album_text = "Photo Album"
                attached_photo_albums.append({
                    "title": clean_album_text,
                    "url": full_href,
                })

    collection_url = None
    collection_name = None
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        if "/actor/" in href or "view full album" in text.lower():
            collection_url = urljoin(video_url, href)
            collection_name = text if text and "view" not in text.lower() else "All Parts Collection"
            break

    post_date_raw = None
    pub_meta = (
        soup.find("meta", property="article:published_time")
        or soup.find("meta", property="uploadDate")
        or soup.find("meta", itemprop="uploadDate")
        or soup.find("meta", itemprop="datePublished")
    )
    if pub_meta and pub_meta.get("content"):
        post_date_raw = pub_meta["content"].strip()

    if not post_date_raw:
        time_elem = soup.find("time")
        if time_elem:
            post_date_raw = time_elem.get("datetime") or time_elem.get("title")

    if not post_date_raw:
        for s in soup.find_all("script", type="application/ld+json"):
            if s.string and "datePublished" in s.string:
                m_date = re.search(r'"datePublished":\s*"([^"]+)"', s.string)
                if m_date:
                    post_date_raw = m_date.group(1)
                    break

    post_date_ist = format_date_ist(post_date_raw) if post_date_raw else None

    return {
        "title": title,
        "clean_title": clean_title,
        "tags": tags,
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_links": streaming_links,
        "attached_photo_albums": attached_photo_albums,
        "attached_album_url": attached_photo_albums[0]["url"] if attached_photo_albums else None,
        "collection_url": collection_url,
        "collection_name": collection_name,
        "duration": duration,
        "post_url": video_url,
        "date": post_date_raw,
        "date_ist": post_date_ist,
        "site": "mmsvibex",
    }


def get_mmsvibex_actor_videos(actor_url: str) -> list[dict]:
    """Fetch all video parts from an MMSVibex actor/collection page."""
    soup = _fetch_soup(actor_url)
    items = []
    seen = set()
    for block in soup.find_all(["article", "div"], class_=re.compile(r"thumb-block|video-preview-item|item", re.I)):
        a = block.find("a", href=True)
        if not a:
            continue
        href = urljoin(actor_url, a["href"].strip())
        if href in seen or not href.startswith("http"):
            continue

        title_elem = block.find(class_=re.compile(r"title|entry-header", re.I)) or a
        title = title_elem.get_text(strip=True) if title_elem else a.get("title", "")
        if not title:
            title = "Untitled Part"

        dur_elem = block.find("span", class_=re.compile(r"duration", re.I))
        duration = dur_elem.get_text(strip=True) if dur_elem else None

        img = block.find("img")
        thumb = img.get("src") or img.get("data-src") if img else None
        thumb = _clean_highres_image_url(thumb) if thumb else None

        seen.add(href)
        items.append({
            "title": title,
            "url": href,
            "duration": duration,
            "thumbnail": thumb,
        })
    return items


def get_mmsvibex_photo_details(photo_url: str) -> dict:
    """Fetch photo album details from MMSVibex including direct ZIP download link."""
    soup = _fetch_soup(photo_url)

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else "Untitled Album"
    clean_title, tags = extract_tags_and_quality(title)

    zip_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if ".zip" in href.lower() or "/downloads/" in href.lower():
            zip_url = urljoin(photo_url, href)
            break

    if not zip_url:
        m = re.search(r'https?://[^\s"\'<>]+\.zip', str(soup))
        if m:
            zip_url = m.group(0)

    thumbnail = None
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        thumbnail = og["content"].strip()
    if not thumbnail:
        gallery_img = soup.find("img", class_=re.compile(r"attachment-|gallery|wp-post-image", re.I))
        if gallery_img:
            thumbnail = gallery_img.get("src") or gallery_img.get("data-src")

    thumbnail = _clean_highres_image_url(thumbnail) if thumbnail else None
    streaming_links = [zip_url] if zip_url else []

    post_date_raw = None
    pub_meta = (
        soup.find("meta", property="article:published_time")
        or soup.find("meta", property="uploadDate")
        or soup.find("meta", itemprop="uploadDate")
    )
    if pub_meta and pub_meta.get("content"):
        post_date_raw = pub_meta["content"].strip()
    if not post_date_raw:
        time_elem = soup.find("time")
        if time_elem:
            post_date_raw = time_elem.get("datetime") or time_elem.get("title")

    post_date_ist = format_date_ist(post_date_raw) if post_date_raw else None

    return {
        "title": f"📸 {title} (Photo Album)",
        "clean_title": clean_title,
        "tags": list(set(tags + ["Photos", "Album"])),
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_links": streaming_links,
        "post_url": photo_url,
        "date": post_date_raw,
        "date_ist": post_date_ist,
        "site": "mmsvibex",
    }


def get_mmsvibex_listing_items(listing_url: str, page: int = 1, limit: int = 25) -> list[dict]:
    """Fetch items from an MMSVibex listing or category page with pagination."""
    clean_base = listing_url.split("?")[0].split("#")[0].rstrip("/")
    query = ""
    if "?" in listing_url:
        query = listing_url.split("?")[1].split("#")[0]
    elif "/photos" not in clean_base and not clean_base.endswith("/photos"):
        query = "filter=latest"

    if page == 1:
        target_url = f"{clean_base}/?{query}" if query else f"{clean_base}/"
    else:
        target_url = f"{clean_base}/page/{page}/?{query}" if query else f"{clean_base}/page/{page}/"

    soup = _fetch_soup(target_url)
    items = []
    seen = set()

    for block in soup.find_all(["article", "div"], class_=re.compile(r"thumb-block|video-preview-item|item", re.I)):
        a = block.find("a", href=True)
        if not a:
            continue
        href = urljoin(target_url, a["href"].strip())
        if href in seen or not href.startswith("http"):
            continue

        img = block.find("img")
        thumb = img.get("src") or img.get("data-src") if img else None
        thumb = _clean_highres_image_url(thumb) if thumb else None

        title_elem = block.find(class_=re.compile(r"title|entry-header", re.I)) or a
        title = title_elem.get_text(strip=True) if title_elem else a.get("title", "")
        if not title:
            title = "Untitled"

        dur_elem = block.find("span", class_=re.compile(r"duration", re.I))
        duration = dur_elem.get_text(strip=True) if dur_elem else None

        seen.add(href)
        items.append({
            "title": title,
            "url": href,
            "thumbnail": thumb,
            "duration": duration,
        })
        if len(items) >= limit:
            break

    return items


def search_mmsvibex(query: str, limit: int = 10) -> list[dict]:
    """Search MMSVibex videos matching the given query."""
    clean_q = query.strip()
    if not clean_q:
        return []
    search_url = f"https://mmsvibex.life/?s={quote_plus(clean_q)}"
    return get_mmsvibex_listing_items(search_url, page=1, limit=limit)


class MediaTubeEngine(BaseEngine):
    """Media Tube Engine (MMSVibex, etc.)."""
    name: str = "MediaTube"
    domains: list[str] = ["mmsvibex.life"]

    def is_listing_url(self, url: str) -> bool:
        return is_mmsvibex_listing_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_mmsvibex_video_url(url) or is_mmsvibex_photo_url(url)

    def get_details(self, url: str) -> dict:
        if is_mmsvibex_photo_url(url):
            return get_mmsvibex_photo_details(url)
        return get_mmsvibex_video_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        return get_mmsvibex_listing_items(url, **kwargs)

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        return search_mmsvibex(query, limit=limit)
