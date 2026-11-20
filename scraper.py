# scraper.py

import re
import io
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, quote_plus
from PIL import Image
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
    if "index.php?/" in url:
        clean = url.split("#")[0].strip()
        parts = clean.split("&")
        clean = parts[0].strip()
    else:
        clean = url.split("?")[0].split("#")[0].strip()
    clean = re.sub(r"/page/\d+/?$", "/", clean)
    if not clean.endswith("/"):
        clean += "/"
    return clean


def _is_posted_today(date_str: str | None, time_text: str | None, full_row_text: str | None = None) -> tuple[bool, bool]:
    """
    Check if a post timestamp, relative text, or row text indicates it was posted today (within last 24-26h).
    Returns: (is_today: bool, is_definitely_older: bool)
    - is_today: Confirmed to be uploaded today / within ~26h across timezones.
    - is_definitely_older: Confirmed older (yesterday or earlier).
    """
    now_utc = datetime.now(timezone.utc)
    today_utc_date = now_utc.date()
    today_utc_str = now_utc.strftime("%Y-%m-%d")

    now_ist = now_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    today_ist_date = now_ist.date()

    tt = str(time_text or "")
    fr = str(full_row_text or "")
    combined = f"{tt} {fr}".lower().strip()

    # 1. ABSOLUTE VETO: If text explicitly says 'yesterday', 'day ago', 'days ago', 'week', etc.
    if any(w in combined for w in ["yesterday", "day ago", "days ago", "week", "month", "year"]):
        return False, True

    # 2. Direct today indicators
    if any(w in combined for w in ["today", "just now", "moment"]):
        return True, False

    # 3. Relative hours/mins/seconds regex (e.g. "2h", "2 hr", "2 hours", "20m", "20 min", "45s")
    if re.search(r"\b\d+\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs)\b(\s*ago)?", combined):
        if not re.search(r"\b\d+\s*(d|day|days|w|wk|weeks|mo|month|months|y|yr|years)\b", combined):
            return True, False

    # Relative days/weeks/years regex (e.g. "2d", "3w")
    if re.search(r"\b\d+\s*(d|day|days|w|wk|weeks|mo|month|months|y|yr|years)\b", combined):
        return False, True

    # 4. Check date_str from <time datetime="..."> or title attribute
    if date_str:
        s = str(date_str).strip()
        if s.startswith(today_utc_str):
            return True, False

        # Attempt ISO 8601 parsing
        try:
            cleaned_iso = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_utc = dt.astimezone(timezone.utc)

            # If UTC date is earlier than today in UTC, it's definitely older
            if dt_utc.date() < today_utc_date:
                return False, True
            elif dt_utc.date() == today_utc_date:
                return True, False
        except Exception:
            pass

    # 5. Check calendar dates in text (e.g. "Nov 20", "20 Nov", "November 20")
    today_days = {str(now_utc.day), f"{now_utc.day:02d}", str(now_ist.day), f"{now_ist.day:02d}"}
    today_months = {now_utc.strftime("%b").lower(), now_utc.strftime("%B").lower()}
    for m in today_months:
        if m in combined:
            for d in today_days:
                if re.search(rf"\b{d}\b", combined):
                    return True, False
            # Mentioned current month but different day -> older
            return False, True

    # If any other month is mentioned (e.g. "Oct 15") -> definitely older
    all_months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    if any(m in combined for m in all_months):
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
      - If True: Option 1 Live Date Cutoff. Filters for topics posted today / within 24h,
        skipping pinned announcements and older topics, without needing database storage.
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
    row_elements = soup.find_all(["li", "div", "article", "tr"], class_=re.compile("ipsDataItem|cForumRow|cTopic", re.I))

    for row in row_elements:
        # Find the topic title link in the row
        title_container = row.find(class_=re.compile(r"ipsDataItem_title|ipsType_break|cForumRow_title", re.I)) or row.find("h4")
        if title_container:
            link_elem = title_container.find("a", href=re.compile(r"/topic/|/topics/topic/|index\.php\?/topic/", re.I))
        else:
            link_elem = None

        if not link_elem:
            link_elem = row.find("a", href=re.compile(r"/topic/|/topics/topic/|index\.php\?/topic/", re.I))

        if not link_elem:
            continue

        full_url = urljoin(forum_url, link_elem["href"].strip())
        clean_url = _clean_topic_url(full_url)
        if clean_url in seen:
            continue

        # Skip pinned / sticky / announcement topics when filtering for today's uploads
        row_classes = " ".join(row.get("class", [])).lower()
        is_pinned = (
            "pinned" in row_classes
            or bool(row.find(class_=re.compile(r"pinned|badge_pinned", re.I)))
            or bool(row.find("span", string=re.compile(r"pinned|featured", re.I)))
        )
        if is_pinned and only_today:
            continue

        # Extract publication timestamp from the topic creation container (NOT last poster!)
        date_str = None
        time_text = None

        main_elem = row.find(class_=re.compile(r"ipsDataItem_main|cForumRow_main", re.I)) or row
        meta_elem = main_elem.find(class_=re.compile(r"ipsDataItem_meta|cForumRow_meta", re.I)) or main_elem

        time_tag = meta_elem.find("time")
        if time_tag:
            date_str = time_tag.get("datetime") or time_tag.get("title")
            time_text = time_tag.get_text(strip=True)

        # Full text of creation container (e.g. "Started by Levi, Yesterday at 9:43 PM")
        row_text = meta_elem.get_text(" ", strip=True)

        # Apply Option 1 Live Date Cutoff when requested via /today
        if only_today:
            is_today, is_older = _is_posted_today(date_str, time_text, full_row_text=row_text)
            if is_older:
                # Stop scanning as soon as we reach yesterday's uploads!
                logger.info(f"Hit date cutoff at older topic: '{link_elem.get_text(strip=True)}' ({row_text}). Stopping scan.")
                break
            if not is_today:
                # Skip unconfirmed
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

    # Fallback: scan all links with /topic/ if specific row elements were not found (only when only_today is False)
    if not topics and not only_today:
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "/topic/" in href or "index.php?/topic/" in href:
                full_url = urljoin(forum_url, href)
                clean_url = _clean_topic_url(full_url)
                if clean_url not in seen:
                    seen.add(clean_url)
                    t_title = a.get_text(strip=True) or "Untitled Post"
                    topics.append({"title": t_title, "url": clean_url, "date": None, "views": None})
                    if len(topics) >= limit:
                        break

    # If this is a category/parent forum that lists subforums, traverse into subforums
    if not topics:
        subforum_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if re.search(r"/forum/\d+|/forums/forum/\d+", href, re.I):
                sf_url = urljoin(forum_url, href)
                clean_sf = sf_url.split("?")[0].split("#")[0].rstrip("/") + "/"
                clean_forum = forum_url.split("?")[0].split("#")[0].rstrip("/") + "/"
                if clean_sf not in subforum_links and clean_sf != clean_forum:
                    subforum_links.append(clean_sf)

        for sf_url in subforum_links[:3]:
            try:
                sub_topics = get_forum_topics(sf_url, sort_by=sort_by, limit=limit - len(topics), only_today=only_today)
                for st in sub_topics:
                    if st["url"] not in seen:
                        seen.add(st["url"])
                        topics.append(st)
                        if len(topics) >= limit:
                            break
                if len(topics) >= limit:
                    break
            except Exception as e:
                logger.debug(f"Could not scrape subforum {sf_url}: {e}")

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

    # Discard blank GIFs, spacer images, avatars, user badges, reaction emojis, site logos
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
        "userphoto",
        "ipsuserphoto",
        "profile",
        "member",
        "emoticons",
        "smile",
        "reaction",
        "react",
        "site_logo",
        "logo.png",
        "logo.jpg",
        "logo.svg",
        "loading.gif",
        "placeholder",
        "svg+xml",
        "attachment-icon",
        "theme_logo",
        "badge",
        "rank",
        "signature",
        "star.png",
        "icon_",
        "favicon",
        "cerrar",
        "close.png",
        "close.gif",
        "btn_close",
        "i.t.net.ar",
        "ad_banner",
        "ad_overlay",
    ]
    if any(b in lower for b in blacklisted):
        return False
    return True


def _clean_highres_image_url(url: str) -> str:
    """
    Convert thumbnail / scaled forum URLs to their full-size original image URLs.
    Prevents downloading cropped squarish thumbnails generated by forums and image hosts.
    """
    if not url or not isinstance(url, str):
        return url

    cleaned = url.strip()

    # 1. Invision Community .thumb. removal (e.g. poster.thumb.jpg.12345.jpg -> poster.jpg)
    cleaned = re.sub(r'\.thumb\.(jpg|jpeg|png|webp)(\.[a-f0-9]+)?$', r'.\1', cleaned, flags=re.I)
    cleaned = re.sub(r'\.thumb\.', '.', cleaned, flags=re.I)

    # 2. PixHost: replace thumbnail server (tXX) and path (/thumbs/) with full image (imgXX and /images/)
    if "pixhost.to/thumbs/" in cleaned:
        cleaned = cleaned.replace("/thumbs/", "/images/")
        cleaned = re.sub(r'https?://t(\d+)\.pixhost\.to', r'https://img\1.pixhost.to', cleaned)

    # 3. ImgBox: replace thumbs with images, _t with _o (original full-size)
    if "imgbox.com" in cleaned and "thumbs" in cleaned:
        cleaned = cleaned.replace("thumbs", "images").replace("_t.", "_o.")

    # 4. PostImg: replace thumbnail paths if present
    if "postimg.cc" in cleaned and "/t/" in cleaned:
        cleaned = cleaned.replace("/t/", "/")

    return cleaned


def _extract_all_image_candidates(soup: BeautifulSoup, post_url: str) -> list[str]:
    """
    Extract all valid image URLs from a forum topic.
    Strictly focuses on the first post's commentContent (the actual post body created by author)
    and completely excludes author avatars, user badges, signatures, reactions, and forum chrome.
    Prioritizes full-resolution uncropped posters over forum-generated thumbnails.
    """
    candidates = []
    seen = set()

    def add_candidate(url: str):
        if not url or not isinstance(url, str):
            return
        cleaned = _clean_highres_image_url(url)
        full = urljoin(post_url, cleaned)
        if _is_valid_thumbnail_url(full) and full not in seen:
            seen.add(full)
            candidates.append(full)

    # 1. Target specifically the FIRST post on the page (the topic starter's post)
    main_post = soup.find(["article", "div"], class_=re.compile(r"\bcPost\b", re.I))
    if not main_post:
        main_post = soup

    # 2. Extract strictly from data-role="commentContent" (the actual post body)
    post_body = main_post.find("div", attrs={"data-role": "commentContent"})
    if not post_body:
        post_body = main_post.find("div", class_=re.compile(r"commentContent|ipsType_richText", re.I))
    if not post_body:
        post_body = main_post

    # 2A. PRIORITY 1: Invision Community embedded images (class ipsImage) and attachment links
    for img in post_body.find_all("img", class_=re.compile(r"ipsImage", re.I)):
        # Parent <a> is almost always the FULL UNCROPPED original poster!
        parent = img.parent
        if parent and parent.name == "a" and parent.get("href"):
            add_candidate(parent["href"].strip())

        src = (
            img.get("data-highres")
            or img.get("data-src")
            or img.get("data-original")
            or img.get("data-lazy-src")
            or img.get("data-image")
            or img.get("src")
        )
        if src:
            add_candidate(src)

    # 2B. PRIORITY 2: Attachment links
    for a in post_body.find_all("a", class_=re.compile(r"ipsAttachLink", re.I)):
        if a.get("href"):
            add_candidate(a["href"])

    # 2C. PRIORITY 3: Popular forum image hosting direct & viewer links in <a>
    for a in post_body.find_all("a", href=True):
        href = a["href"].strip()
        lower_href = href.lower().split("?")[0]
        if any(lower_href.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]):
            add_candidate(href)
        elif any(ih in lower_href for ih in ["postimg", "pixhost", "imgbox", "imagebam", "ibb.co", "turboimagehost", "imx.to", "picbaron"]):
            add_candidate(href)

    # 2D. PRIORITY 4: General <img> tags within post body
    for img in post_body.find_all("img"):
        parent = img.parent
        if parent and parent.name == "a" and parent.get("href"):
            add_candidate(parent["href"].strip())
        src = (
            img.get("data-highres")
            or img.get("data-src")
            or img.get("data-original")
            or img.get("data-lazy-src")
            or img.get("data-image")
            or img.get("src")
        )
        if src:
            add_candidate(src)

    # 3. Fallback: if absolutely NO images inside post body, check OpenGraph
    if not candidates:
        for meta_name in [("property", "og:image"), ("name", "og:image"), ("name", "twitter:image")]:
            tag = soup.find("meta", attrs={meta_name[0]: meta_name[1]})
            if tag and tag.get("content"):
                add_candidate(tag["content"])

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


def is_valid_thumbnail_image(data: bytes, min_width: int = 180, min_height: int = 180) -> bool:
    """
    Verify with Pillow that downloaded data is a valid image with resolution
    suitable for a movie poster or screenshot (rejects tiny avatars, icons, badges).
    """
    if not data or len(data) < 512:
        return False
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            # Posters and screenshots are substantially larger than user avatars (usually 50x50 to 100x100)
            if w < min_width and h < min_height:
                logger.info(f"Rejected candidate image ({w}x{h} px): below minimum thumbnail dimensions.")
                return False
            return True
    except Exception as e:
        logger.debug(f"Pillow could not parse image dimensions: {e}")
        return True  # If Pillow fails for rare format, fallback to magic bytes check


def optimize_image_for_telegram(data: bytes) -> bytes:
    """
    Ensure the image displays fully in Telegram chat bubbles without getting cropped or squarified.
    If an image is excessively tall (height / width > 1.7), add slight dark side-padding
    to achieve a standard ~2:3 portrait ratio so Telegram displays the full poster without cropping.
    """
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            w, h = im.size

            # If aspect ratio is excessively tall (e.g. > 1.7), Telegram mobile/desktop crops top & bottom.
            # Pad sides with a sleek dark matte background to make it ~2:3 (width = height * 2 // 3).
            if h / w > 1.7:
                target_w = int(h * 0.67)
                pad_left = (target_w - w) // 2
                new_im = Image.new("RGB", (target_w, h), (18, 18, 18))
                new_im.paste(im, (pad_left, 0))
                out_buf = io.BytesIO()
                new_im.save(out_buf, format="JPEG", quality=92)
                return out_buf.getvalue()

            return data
    except Exception as e:
        logger.debug(f"Image optimization note: {e}")
        return data


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

        # Check common image host classes / IDs (imagetwist, imagehaha, postimg, pixhost)
        main_img = (
            soup.find("img", class_=re.compile(r"\b(pic|img|centred|main-image|main_image)\b", re.I))
            or soup.find("img", id=re.compile(r"^(main-image|image|show_image|img_obj|pic)$", re.I))
        )
        if main_img and main_img.get("src"):
            src = main_img["src"].strip()
            if _is_valid_thumbnail_url(src):
                return urljoin(viewer_url, src)

        # Check any img tag with direct image extension, strictly filtering blacklisted items
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
    Verifies image magic bytes AND image dimensions with Pillow to ensure
    tiny avatars / icons are filtered out and Telegram never throws Image_process_failed.
    If image_url is an HTML viewer page, automatically resolves and downloads the real image.
    Optimizes aspect ratio to prevent Telegram squarish cropping.
    """
    if not image_url or not isinstance(image_url, str):
        return None
    try:
        resp = _session.get(image_url, timeout=12)
        if resp.status_code != 200 or not resp.content:
            return None

        # 1. Direct image check via magic bytes and Pillow dimension verification
        if is_valid_image_bytes(resp.content):
            if is_valid_thumbnail_image(resp.content):
                return optimize_image_for_telegram(resp.content)
            else:
                logger.info(f"Skipping candidate {image_url}: failed dimension verification (likely avatar/icon).")
                return None

        # 2. If response is HTML, it might be an image host viewer page (postimg, pixhost, etc.)
        content_type = resp.headers.get("Content-Type", "").lower()
        if "text/html" in content_type or resp.content[:1] == b"<":
            direct_img_url = _resolve_image_viewer_url(image_url, resp.text)
            if direct_img_url and direct_img_url != image_url:
                direct_resp = _session.get(direct_img_url, timeout=12)
                if direct_resp.status_code == 200 and is_valid_image_bytes(direct_resp.content):
                    if is_valid_thumbnail_image(direct_resp.content):
                        return optimize_image_for_telegram(direct_resp.content)

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


def is_topic_url(url: str) -> bool:
    """Check if URL represents an individual topic/post."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    return "/topic/" in u or "/topics/topic/" in u or "/topic-" in u or "index.php?/topic/" in u


def is_forum_url(url: str) -> bool:
    """Check if URL represents a forum category page, category listing, or forum index."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    if is_topic_url(u):
        return False
    return (
        "/forum/" in u
        or "/forums/" in u
        or "/forum-" in u
        or "/category/" in u
        or "/categories/" in u
        or u.rstrip("/").endswith("index.php")
        or u.rstrip("/") == BASE_URL.lower()
        or u.rstrip("/") == "https://dropmms.com"
        or u.rstrip("/") == "http://dropmms.com"
    )
