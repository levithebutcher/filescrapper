# scraper.py

import re
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, quote_plus
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from config import (
    STREAMING_DOMAINS,
    BASE_URL,
    MAX_TITLE_LENGTH,
    MAX_POSTS_PER_FORUM,
    REQUEST_TIMEOUT,
    PROXIES,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Connection": "keep-alive",
}

def _create_session() -> requests.Session:
    """Create and configure a robust requests Session with retries and connection pooling."""
    session = requests.Session()
    session.headers.update(HEADERS)
    if PROXIES:
        session.proxies.update(PROXIES)

    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_session = _create_session()


def _is_streaming_link(url: str) -> bool:
    """Check if URL belongs to any supported streaming domain."""
    if not url or not isinstance(url, str):
        return False
    try:
        domain = urlparse(url).netloc.lower()
        if not domain:
            domain = url.split("/")[0].lower()
        return any(sd in domain for sd in STREAMING_DOMAINS)
    except Exception:
        return False


def get_host_display_name(url: str) -> str:
    """Get clean emoji-badge display name for a streaming provider."""
    try:
        domain = urlparse(url).netloc.lower()
        if "vidara" in domain:
            return "⚡ Vidara"
        elif "streamtape" in domain:
            return "🎬 Streamtape"
        elif "streamfiles" in domain:
            return "📥 Streamfiles"
        elif "dood" in domain:
            return "🎥 Doodstream"
        elif "streamwish" in domain:
            return "✨ Streamwish"
        elif "lplaygo" in domain:
            return "▶️ Lplaygo"
        elif "filelions" in domain:
            return "🦁 Filelions"
        elif "dropload" in domain:
            return "📦 Dropload"
        elif "mixdrop" in domain:
            return "💧 Mixdrop"
        elif "streamruby" in domain:
            return "💎 Streamruby"
        else:
            clean = domain.replace("www.", "").split(".")[0].capitalize()
            return f"🎬 {clean}"
    except Exception:
        return "🎬 Watch Video"


def get_host_key(url: str) -> str:
    """Extract standard key for a streaming provider (e.g. vidara, streamtape)."""
    try:
        domain = urlparse(url).netloc.lower()
        if "vidara" in domain:
            return "vidara"
        elif "streamtape" in domain:
            return "streamtape"
        elif "streamfiles" in domain:
            return "streamfiles"
        elif "dood" in domain:
            return "doodstream"
        elif "streamwish" in domain:
            return "streamwish"
        elif "lplaygo" in domain:
            return "lplaygo"
        elif "filelions" in domain:
            return "filelions"
        elif "dropload" in domain:
            return "dropload"
        elif "mixdrop" in domain:
            return "mixdrop"
        elif "streamruby" in domain:
            return "streamruby"
        else:
            return domain.replace("www.", "").split(".")[0]
    except Exception:
        return "other"


def filter_links_by_preference(links: list[str], preferred_host: str = "vidara") -> tuple[str, list[str], bool]:
    """
    Filter streaming links according to user preference with smart fallback.
    Returns: (display_name, filtered_links, is_fallback)
    - If preferred_host == 'all': returns all links.
    - If preferred_host exists in links: returns only those links.
    - If preferred_host NOT in links: falls back to the first available provider so user never misses the video.
    """
    if not links:
        return "None", [], False

    pref = preferred_host.lower().strip() if preferred_host else "vidara"
    if pref == "all":
        return "All Providers", links, False

    # Group links by host key
    grouped: dict[str, list[str]] = {}
    host_display_map: dict[str, str] = {}

    for link in links:
        h_key = get_host_key(link)
        if h_key not in grouped:
            grouped[h_key] = []
            host_display_map[h_key] = get_host_display_name(link)
        if link not in grouped[h_key]:
            grouped[h_key].append(link)

    # 1. Match preferred host
    if pref in grouped:
        return host_display_map[pref], grouped[pref], False

    # 2. Smart Fallback: take the first available provider
    first_key = next(iter(grouped))
    return host_display_map[first_key], grouped[first_key], True


def extract_tags_and_quality(title: str) -> tuple[str, list[str]]:
    """Extract quality and tags from topic title (e.g. 1080p, 4K, HD, Exclusive)."""
    tags = []
    # Match patterns inside [brackets] or (parentheses) or standalone words
    tag_pattern = re.compile(r"\[([^\]]+)\]|\(([^\)]+)\)", re.IGNORECASE)
    for m in tag_pattern.finditer(title):
        match_text = (m.group(1) or m.group(2)).strip()
        if len(match_text) <= 20 and not match_text.startswith("http"):
            tags.append(match_text)

    # Standalone quality terms
    quality_matches = re.findall(r"\b(1080p|720p|480p|2160p|4k|fhd|uhd|hd)\b", title, re.IGNORECASE)
    for q in quality_matches:
        q_upper = q.upper()
        if q_upper not in [t.upper() for t in tags]:
            tags.append(q_upper)

    return title, tags


def _fetch_soup(url: str) -> BeautifulSoup:
    """Safely fetch URL and return parsed BeautifulSoup object."""
    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout while fetching {url}: {e}")
        raise RuntimeError(f"Connection timeout ({REQUEST_TIMEOUT}s exceeded)") from e
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error while fetching {url}: {e}")
        raise RuntimeError("Website connection failed. Network or ISP block possible.") from e
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "Unknown"
        reason = e.response.reason if e.response is not None else str(e)
        logger.error(f"HTTP error for {url}: {status_code} - {reason}")
        raise RuntimeError(f"HTTP Error {status_code}: {reason}") from e
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        raise RuntimeError(f"Error fetching page: {str(e)}") from e


def _clean_topic_url(url: str) -> str:
    """Sanitize topic URL by removing query strings, fragments, and pagination."""
    clean = url.split("?")[0].split("#")[0].strip()
    clean = re.sub(r"/page/\d+/?$", "/", clean)
    if not clean.endswith("/"):
        clean += "/"
    return clean


def _is_posted_today(date_str: str | None, time_text: str | None) -> tuple[bool, bool]:
    """
    Check if a post timestamp or relative text indicates it was posted today.
    Returns: (is_today: bool, is_definitely_older: bool)
    - is_today: Confirmed to be uploaded today.
    - is_definitely_older: Confirmed older (yesterday or earlier).
      Triggers an immediate break in the category loop (Option 1: Live Date Cutoff).
    """
    now_utc = datetime.now(timezone.utc)
    today_utc_date = now_utc.date()
    today_utc_str = now_utc.strftime("%Y-%m-%d")

    # Local & IST fallback (UTC+5:30) for users / Indian forum hosting
    now_ist = now_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    today_ist_date = now_ist.date()
    today_ist_str = now_ist.strftime("%Y-%m-%d")

    valid_today_dates = {today_utc_str, today_ist_str}

    # 1. Inspect date_str from <time datetime="..."> or title attribute
    if date_str:
        s = str(date_str).strip()
        # Direct date prefix check (e.g. "2026-11-20T...")
        if any(s.startswith(td) for td in valid_today_dates):
            return True, False

        # Attempt ISO 8601 parsing
        try:
            cleaned_iso = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned_iso)
            dt_date = dt.astimezone(timezone.utc).date()
            if dt_date == today_utc_date or dt_date == today_ist_date:
                return True, False
            elif dt_date < today_utc_date and dt_date < today_ist_date:
                return False, True
        except Exception:
            pass

    # 2. Inspect relative time text (e.g. "3 hours ago", "Today at 12:45", "Yesterday at 18:20")
    if time_text:
        t = str(time_text).lower().strip()
        # Check today patterns
        if any(w in t for w in ["today", "hour", "hr", "min", "sec", "just now", "moment"]):
            return True, False
        # Check older patterns
        if any(w in t for w in ["yesterday", "day ago", "days ago", "week", "month", "year"]):
            return False, True
        # Check month abbreviations (e.g. "18 nov", "nov 18")
        months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
        if any(m in t for m in months) and not any(td in t for td in valid_today_dates):
            return False, True

    return False, False


def get_forum_topics(
    forum_url: str,
    sort_by: str = "start_date",
    limit: int = 25,
    only_today: bool = False,
) -> list[dict]:
    """
    Fetch structured topics from a forum category with date-sorting and metadata.
    sort_by options:
      - 'start_date': Sort by topic creation/upload date (Newest uploads first)
      - 'views': Sort by popularity/views
      - 'updated': Sort by last activity
    only_today:
      - If True: Option 1 Live Date Cutoff. Scans topics in descending chronological order
        and immediately stops scanning as soon as a post from yesterday or earlier is encountered.
        Returns only today's fresh posts without needing any database storage.
      - If False: Scrapes up to `limit` posts across the full page (default: 25).
    """
    separator = "&" if "?" in forum_url else "?"
    if sort_by == "start_date":
        target_url = f"{forum_url}{separator}sortby=forums_topics.start_date&sortdirection=desc"
    elif sort_by == "views":
        target_url = f"{forum_url}{separator}sortby=views&sortdirection=desc"
    else:
        target_url = forum_url

    soup = _fetch_soup(target_url)
    topics = []
    seen = set()

    # Search for topic row elements (IPS Community rows)
    row_elements = soup.find_all("li", class_=re.compile("ipsDataItem|cForumRow", re.I))
    if not row_elements:
        row_elements = soup.find_all("div", class_=re.compile("ipsDataItem|cForumRow", re.I))

    for row in row_elements:
        link_elem = row.find("a", href=re.compile(r"/topic/\d+", re.I))
        if not link_elem:
            continue

        full_url = urljoin(forum_url, link_elem["href"].strip())
        clean_url = _clean_topic_url(full_url)
        if clean_url in seen:
            continue

        # Extract publication timestamp from <time datetime="..."> and relative text
        date_str = None
        time_text = None
        time_tag = row.find("time")
        if time_tag:
            date_str = time_tag.get("datetime") or time_tag.get("title")
            time_text = time_tag.get_text(strip=True)

        # Apply Option 1 Live Date Cutoff when requested via /today
        if only_today:
            is_today, is_older = _is_posted_today(date_str, time_text)
            if is_older:
                # Chronological descending order means all subsequent topics are also older.
                logger.info(f"Live date cutoff: Topic '{clean_url}' is older ({date_str or time_text}). Stopping scan.")
                break
            if not is_today:
                # If cannot verify as today, skip this topic
                continue

        seen.add(clean_url)
        title = link_elem.get_text(strip=True) or "Untitled Post"

        # Extract views count
        views_str = None
        views_elem = row.find("span", class_=re.compile("ipsType_light|cForumRow_views", re.I))
        if views_elem:
            views_str = views_elem.get_text(strip=True)

        topics.append({
            "title": title,
            "url": clean_url,
            "date": date_str,
            "views": views_str,
        })

        if len(topics) >= limit:
            break

    # Fallback if specific row elements were not found
    if not topics and not only_today:
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "/topic/" in href:
                full_url = urljoin(forum_url, href)
                clean_url = _clean_topic_url(full_url)
                if clean_url not in seen:
                    seen.add(clean_url)
                    t_title = a.get_text(strip=True) or "Untitled Post"
                    topics.append({"title": t_title, "url": clean_url, "date": None, "views": None})
                    if len(topics) >= limit:
                        break

    return topics


def search_forum(query: str, limit: int = 5) -> list[dict]:
    """
    Search the forum by keyword and return top matching topics.
    """
    search_url = f"{BASE_URL}/search/?q={quote_plus(query.strip())}&type=forums_topic"
    soup = _fetch_soup(search_url)

    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(search_url, href)
        if "/topic/" in full:
            clean = _clean_topic_url(full)
            if clean not in seen:
                seen.add(clean)
                title = a.get_text(strip=True)
                if title and len(title) > 3 and not title.lower().startswith("page"):
                    results.append({"title": title, "url": clean})
                    if len(results) >= limit:
                        break

    return results


def get_post_links_from_forum(forum_url: str) -> list[str]:
    """Legacy helper: Extract list of post URLs from a forum page."""
    topics = get_forum_topics(forum_url, sort_by="start_date", limit=MAX_POSTS_PER_FORUM)
    return [t["url"] for t in topics]


def _extract_streaming_links_from_html(soup: BeautifulSoup, post_url: str) -> list[str]:
    """Extract streaming video links from <a>, <iframe>, <embed>, <source>, and raw text."""
    links = []
    seen = set()

    def add_link(raw_link: str):
        if not raw_link or not isinstance(raw_link, str):
            return
        cleaned = raw_link.strip().rstrip(".,;\"'()[]{}<>")
        full = urljoin(post_url, cleaned)
        if _is_streaming_link(full) and full not in seen:
            seen.add(full)
            links.append(full)

    for a in soup.find_all("a", href=True):
        add_link(a["href"])

    for tag in soup.find_all(["iframe", "embed", "source"], src=True):
        add_link(tag["src"])

    url_pattern = re.compile(r'https?://[^\s<>"\'{}|\\^`]+', re.IGNORECASE)
    for match in url_pattern.finditer(str(soup)):
        raw = match.group(0)
        if _is_streaming_link(raw):
            add_link(raw)

    return links


def _is_valid_thumbnail_url(url: str) -> bool:
    """Validate if an image URL is an actual video thumbnail and not a white/blank spacer or site logo."""
    if not url or not isinstance(url, str):
        return False
    lower = url.lower().strip()
    if not lower.startswith("http://") and not lower.startswith("https://"):
        return False

    # Discard blank GIFs, spacer images, transparent SVGs, default site logos
    blacklisted = [
        "blank.gif",
        "blank.png",
        "spacer.gif",
        "spacer.png",
        "transparent",
        "1x1",
        "pixel.gif",
        "default_og",
        "default_avatar",
        "avatar",
        "emoticons",
        "smile",
        "site_logo",
        "logo.png",
        "logo.jpg",
        "logo.svg",
        "loading.gif",
        "placeholder",
        "svg+xml",
        "attachment-icon",
        "theme_logo",
    ]
    if any(b in lower for b in blacklisted):
        return False
    return True


def _extract_all_image_candidates(soup: BeautifulSoup, post_url: str) -> list[str]:
    """
    Extract all valid image URLs from a forum topic.
    Scans post content, image tags, image hosts, attachment links, and metadata.
    Returns ordered list of candidates with direct poster/screenshots prioritized first.
    """
    candidates = []
    seen = set()

    def add_candidate(url: str):
        if not url or not isinstance(url, str):
            return
        full = urljoin(post_url, url.strip())
        if _is_valid_thumbnail_url(full) and full not in seen:
            seen.add(full)
            candidates.append(full)

    # 1. Search in all post content bodies (handles multiple posts / comments)
    content_areas = soup.find_all(
        ["div", "article", "section"],
        class_=re.compile(r"cPost_contentWrap|commentContent|ipsType_richText|ipsType_normal|cPost", re.I)
    )
    if not content_areas:
        content_areas = [soup]

    for area in content_areas:
        # 1A. PRIORITY 1: Check all <img> tags inside post content (where posters & screenshots are embedded)
        for img in area.find_all("img"):
            src = (
                img.get("data-src")
                or img.get("data-original")
                or img.get("data-lazy-src")
                or img.get("data-url")
                or img.get("data-highres")
                or img.get("data-image")
                or img.get("src")
            )
            if src:
                add_candidate(src)

        # 1B. PRIORITY 2: Check <a> links that explicitly end with image file extensions
        for a in area.find_all("a", href=True):
            href = a["href"].strip()
            lower_href = href.lower().split("?")[0]
            if any(lower_href.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]):
                add_candidate(href)

        # 1C. PRIORITY 3: Check popular image host viewer links in <a> (postimg, pixhost, imgbox, etc.)
        for a in area.find_all("a", href=True):
            href = a["href"].strip()
            lower_href = href.lower().split("?")[0]
            if any(ih in lower_href for ih in ["pixhost", "postimg", "imgbox", "imagebam", "ibb.co", "picbaron", "turboimagehost", "imx.to"]):
                add_candidate(href)

    # 2. OpenGraph / Twitter meta images
    for meta_name in [("property", "og:image"), ("name", "og:image"), ("name", "twitter:image")]:
        tag = soup.find("meta", attrs={meta_name[0]: meta_name[1]})
        if tag and tag.get("content"):
            add_candidate(tag["content"])

    # 3. Regex fallback over page HTML for direct image URLs (.jpg, .png, .webp)
    img_regex = re.compile(r'https?://[^\s<>"\'{}|\\^`]+?\.(?:jpg|jpeg|png|webp)', re.IGNORECASE)
    for m in img_regex.finditer(str(soup)):
        raw_url = m.group(0)
        add_candidate(raw_url)

    return candidates


def _extract_thumbnail(soup: BeautifulSoup, post_url: str) -> str | None:
    """Extract best thumbnail candidate URL."""
    candidates = _extract_all_image_candidates(soup, post_url)
    return candidates[0] if candidates else None


def is_valid_image_bytes(data: bytes) -> bool:
    """
    Strictly verify that data contains valid image magic bytes.
    Rejects HTML documents, error pages, and corrupted data.
    """
    if not data or len(data) < 512:
        return False
    # Strictly reject HTML / XML / text
    prefix = data[:32].strip()
    if prefix.startswith(b"<") or b"<!doc" in prefix.lower() or b"<html" in prefix.lower():
        return False
    # JPEG magic bytes: FF D8 FF
    if data[:3] == b"\xff\xd8\xff":
        return True
    # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    # WebP: starts with 'RIFF' and bytes 8..12 are 'WEBP'
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return True
    # GIF: GIF87a or GIF89a
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    # BMP: BM
    if data[:2] == b"BM":
        return True
    return False


def _resolve_image_viewer_url(viewer_url: str, html_text: str) -> str | None:
    """
    Extract direct image URL from an image host viewer webpage (postimg, pixhost, etc.).
    """
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        # Check OpenGraph / Twitter meta image
        for meta_attr in [("property", "og:image"), ("name", "og:image"), ("name", "twitter:image")]:
            tag = soup.find("meta", attrs={meta_attr[0]: meta_attr[1]})
            if tag and tag.get("content"):
                c = tag["content"].strip()
                if _is_valid_thumbnail_url(c) and any(c.lower().split("?")[0].endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    return urljoin(viewer_url, c)

        # Check common image host IDs
        for img_id in ["main-image", "image", "show_image", "img_obj"]:
            img_tag = soup.find("img", id=img_id)
            if img_tag and img_tag.get("src"):
                return urljoin(viewer_url, img_tag["src"].strip())

        # Check any img tag with direct image extension
        for img in soup.find_all("img", src=True):
            src = img["src"].strip()
            if any(src.lower().split("?")[0].endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if _is_valid_thumbnail_url(src):
                    return urljoin(viewer_url, src)
    except Exception:
        pass
    return None


def download_image_bytes(image_url: str) -> bytes | None:
    """
    Download image into memory using the bot's configured requests session.
    Verifies image magic bytes to ensure Telegram never throws Image_process_failed.
    If image_url is an HTML viewer page, automatically resolves and downloads the real image.
    """
    if not image_url or not isinstance(image_url, str):
        return None
    try:
        resp = _session.get(image_url, timeout=12)
        if resp.status_code != 200 or not resp.content:
            return None

        # 1. Direct image check via magic bytes
        if is_valid_image_bytes(resp.content):
            return resp.content

        # 2. If response is HTML, it might be an image host viewer page (postimg, pixhost, etc.)
        content_type = resp.headers.get("Content-Type", "").lower()
        if "text/html" in content_type or resp.content[:1] == b"<":
            direct_img_url = _resolve_image_viewer_url(image_url, resp.text)
            if direct_img_url and direct_img_url != image_url:
                direct_resp = _session.get(direct_img_url, timeout=12)
                if direct_resp.status_code == 200 and is_valid_image_bytes(direct_resp.content):
                    return direct_resp.content

    except Exception as e:
        logger.warning(f"Could not download thumbnail bytes from {image_url}: {e}")
    return None


def get_post_details(post_url: str) -> dict:
    """Fetch post details: title, tags, thumbnail, and streaming links."""
    soup = _fetch_soup(post_url)

    # Title Extraction
    title = None
    h1 = soup.find("h1", class_=re.compile("ipsType_pageTitle|entry-title", re.I)) or soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    elif soup.title and soup.title.get_text(strip=True):
        title = soup.title.get_text(strip=True)

    if title:
        title = re.sub(r"^(Topic:\s*|Post:\s*)", "", title, flags=re.I).strip()
        if len(title) > MAX_TITLE_LENGTH:
            title = title[:MAX_TITLE_LENGTH].rstrip() + "..."
    else:
        title = "Untitled Post"

    clean_title, tags = extract_tags_and_quality(title)
    thumbnail_candidates = _extract_all_image_candidates(soup, post_url)
    thumbnail = thumbnail_candidates[0] if thumbnail_candidates else None
    streaming_links = _extract_streaming_links_from_html(soup, post_url)

    return {
        "title": title,
        "clean_title": clean_title,
        "tags": tags,
        "thumbnail": thumbnail,
        "thumbnail_candidates": thumbnail_candidates,
        "streaming_links": streaming_links,
        "post_url": post_url,
    }


def is_forum_url(url: str) -> bool:
    """Check if URL represents a forum category page."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    return "/forum/" in u or "/forums/" in u or "/forum-" in u or u.rstrip("/").endswith("index.php")


def is_topic_url(url: str) -> bool:
    """Check if URL represents an individual topic/post."""
    if not url or not isinstance(url, str):
        return False
    return "/topic/" in url.strip().lower()
