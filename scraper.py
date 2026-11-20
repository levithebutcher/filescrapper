# scraper.py

import re
import logging
from urllib.parse import urljoin, urlparse
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

    # Configure retries for transient errors
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
    """Check karein ki URL kisi streaming domain ka hai ya nahi."""
    if not url or not isinstance(url, str):
        return False
    try:
        domain = urlparse(url).netloc.lower()
        if not domain:
            # Maybe schema is missing
            domain = url.split("/")[0].lower()
        return any(sd in domain for sd in STREAMING_DOMAINS)
    except Exception:
        return False


def _fetch_soup(url: str) -> BeautifulSoup:
    """
    URL se HTML fetch karke BeautifulSoup parse karein.
    Network errors aur timeouts ko safely handle karta hai.
    """
    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout while fetching {url}: {e}")
        raise RuntimeError(f"Connection timeout (Server ne {REQUEST_TIMEOUT}s mein respond nahi kiya)") from e
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error while fetching {url}: {e}")
        raise RuntimeError("Website se connect nahi ho saka. ISP block ya internet issue ho sakta hai.") from e
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "Unknown"
        reason = e.response.reason if e.response is not None else str(e)
        logger.error(f"HTTP error for {url}: {status_code} - {reason}")
        raise RuntimeError(f"HTTP Error {status_code}: {reason}") from e
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        raise RuntimeError(f"Page fetch karne mein error: {str(e)}") from e


def _clean_topic_url(url: str) -> str:
    """
    Topic URL ko sanitize karein: query params, fragments aur pagination (/page/2/) hatayein.
    """
    clean = url.split("?")[0].split("#")[0].strip()
    # Remove pagination pattern e.g. /page/2/
    clean = re.sub(r"/page/\d+/?$", "/", clean)
    if not clean.endswith("/"):
        clean += "/"
    return clean


def get_post_links_from_forum(forum_url: str) -> list[str]:
    """
    Category/forum page se topic posts ke links nikaalein.
    Duplication aur unwanted pagination links ko filter karta hai.
    """
    soup = _fetch_soup(forum_url)
    discovered = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full_url = urljoin(forum_url, href)

        # Sirf /topic/ wale links
        if "/topic/" in full_url:
            clean_url = _clean_topic_url(full_url)
            if clean_url not in seen:
                seen.add(clean_url)
                discovered.append(clean_url)

                # Limit max posts per forum fetch to avoid flooding
                if len(discovered) >= MAX_POSTS_PER_FORUM:
                    logger.info(f"Reached MAX_POSTS_PER_FORUM limit ({MAX_POSTS_PER_FORUM})")
                    break

    return discovered


def _extract_streaming_links_from_html(soup: BeautifulSoup, post_url: str) -> list[str]:
    """
    Post ke HTML se saare possible streaming links nikaalein:
    - <a href="...">
    - <iframe src="...">
    - <embed src="...">
    - <source src="...">
    - Plain text URLs in body/comments
    """
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

    # 1. <a> tags
    for a in soup.find_all("a", href=True):
        add_link(a["href"])

    # 2. <iframe>, <embed>, <source> tags (embedded video players)
    for tag in soup.find_all(["iframe", "embed", "source"], src=True):
        add_link(tag["src"])

    # 3. Regex search in post content / entire text for unlinked URLs
    url_pattern = re.compile(r'https?://[^\s<>"\'{}|\\^`]+', re.IGNORECASE)
    for match in url_pattern.finditer(str(soup)):
        raw = match.group(0)
        if _is_streaming_link(raw):
            add_link(raw)

    return links


def _extract_thumbnail(soup: BeautifulSoup, post_url: str) -> str | None:
    """
    Post se best thumbnail image extract karein:
    - OpenGraph (og:image)
    - Twitter Image
    - First post content image
    """
    # 1. OpenGraph
    og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if og_img and og_img.get("content"):
        content = og_img["content"].strip()
        if content.startswith("http"):
            return content

    # 2. Twitter Card Image
    tw_img = soup.find("meta", attrs={"name": "twitter:image"})
    if tw_img and tw_img.get("content"):
        content = tw_img["content"].strip()
        if content.startswith("http"):
            return content

    # 3. Search post content body for first relevant image
    content_container = (
        soup.find("div", class_="cPost_contentWrap")
        or soup.find("div", attrs={"data-role": "commentContent"})
        or soup.find("article")
        or soup
    )

    for img in content_container.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-original")
            or img.get("data-url")
            or img.get("data-lazy-src")
        )
        if not src:
            continue
        src = src.strip()
        lower_src = src.lower()
        if any(ign in lower_src for ign in ["avatar", "emoticons", "badge", "icon", "logo", "smile"]):
            continue

        full_img_url = urljoin(post_url, src)
        if full_img_url.startswith("http"):
            return full_img_url

    return None


def get_post_details(post_url: str) -> dict:
    """
    Ek post ka title, thumbnail, aur streaming links nikaalein.
    Return: dict {title, thumbnail, streaming_links, post_url}
    """
    soup = _fetch_soup(post_url)

    # ---- Title Extraction ----
    title = None
    h1 = soup.find("h1", class_=re.compile("ipsType_pageTitle|entry-title", re.I)) or soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    elif soup.title and soup.title.get_text(strip=True):
        title = soup.title.get_text(strip=True)

    # Clean title
    if title:
        title = re.sub(r"^(Topic:\s*|Post:\s*)", "", title, flags=re.I).strip()
        if len(title) > MAX_TITLE_LENGTH:
            title = title[:MAX_TITLE_LENGTH].rstrip() + "..."
    else:
        title = "Untitled Post"

    # ---- Thumbnail Extraction ----
    thumbnail = _extract_thumbnail(soup, post_url)

    # ---- Streaming Links Extraction ----
    streaming_links = _extract_streaming_links_from_html(soup, post_url)

    return {
        "title": title,
        "thumbnail": thumbnail,
        "streaming_links": streaming_links,
        "post_url": post_url,
    }


def is_forum_url(url: str) -> bool:
    """Check karein ki URL forum/category page ka hai ya post ka."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    return "/forum/" in u or "/forums/" in u or "/forum-" in u or u.rstrip("/").endswith("index.php")


def is_topic_url(url: str) -> bool:
    """Check karein ki URL post (/topic/) ka hai."""
    if not url or not isinstance(url, str):
        return False
    return "/topic/" in url.strip().lower()
