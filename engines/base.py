# engines/base.py
"""
Base Engine and shared networking, date parsing, provider priority,
image handling, and slicing utilities.
"""

import re
import io
import html
import logging
from enum import Enum
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, quote, quote_plus
from PIL import Image
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# Cloudflare anti-bot bypass libraries
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    try:
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "curl_cffi>=0.7.0"])
        from curl_cffi import requests as cffi_requests
        HAS_CURL_CFFI = True
    except Exception:
        cffi_requests = None
        HAS_CURL_CFFI = False

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    cloudscraper = None
    HAS_CLOUDSCRAPER = False

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


# Streaming Provider Mirrors & Exclusions
STREAMTAPE_MIRRORS = (
    "streamtape",
    "strtape",
    "strcloud",
    "strtpe",
    "streamta.pe",
    "tapecontent",
    "shavetape",
    "scloud.online",
)

LPLAYGO_MIRRORS = (
    "lplaygo",
    "iplaygo",
    "luluvido",
    "luluvise",
    "lulustream",
    "luluvdo",
    "playgo.",
    "lplay.to",
)

DOOD_MIRRORS = (
    "doodstream",
    "dood.",
    "ds2play",
    "do0od",
    "d000d",
    "d0o0d",
)

STREAMWISH_MIRRORS = (
    "streamwish",
    "wishembed",
    "wishfast",
    "flaswish",
    "swhoi",
    "sfastwish",
    "embedwish",
)

FILELIONS_MIRRORS = (
    "filelions",
    "lionembed",
)

ABSTREAM_MIRRORS = (
    "abstream",
    "abysscdn",
)

MIXDROP_MIRRORS = (
    "mixdrop",
    "mdzsmutpcvykb",
)

EXCLUDED_STREAMING_DOMAINS = (
    "frdl.io",
    "a-ads.com",
    "tsyndicate.com",
    "doubleclick",
    "exoclick",
    "juicyads",
)


def _is_streaming_link(url: str) -> bool:
    """Check if URL belongs to any supported streaming domain or direct video/archive link."""
    if not url or not isinstance(url, str):
        return False
    try:
        domain = urlparse(url).netloc.lower()
        if not domain:
            domain = url.split("/")[0].lower()
        if any(ign in domain for ign in EXCLUDED_STREAMING_DOMAINS):
            return False
        u_low = url.lower().split("?")[0].strip()
        if u_low.endswith(".mp4") or u_low.endswith(".zip"):
            return True
        if "/downloads/" in u_low and ".zip" in u_low:
            return True
        if "/processed/" in u_low and ".mp4" in u_low:
            return True
        return any(sd in domain for sd in STREAMING_DOMAINS)
    except Exception:
        return False


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


# Provider Priority Order (Highest -> Lowest)
PROVIDER_PRIORITY = [
    "streamtape",
    "vidara",
    "streamfiles",
    "iplaygo",
    "lplaygo",
    "abstream",
    "uqload",
    "streamcash",
    "direct_mp4",
    "direct_zip",
    "doodstream",
    "streamwish",
    "filelions",
    "dropload",
    "mixdrop",
    "streamruby",
    "cloudfam",
]


def get_host_display_name(url: str) -> str:
    """Get clean emoji-badge display name for a streaming provider."""
    try:
        u_low = url.lower()
        clean_path = u_low.split("?")[0]
        domain = urlparse(url).netloc.lower()
        if "mmsvibex" in domain or clean_path.endswith(".mp4") or "/processed/" in u_low:
            return "⚡ Direct MP4"
        elif clean_path.endswith(".zip") or "/downloads/" in u_low:
            return "📦 Download ZIP"
        elif any(m in domain for m in STREAMTAPE_MIRRORS):
            return "🎬 Streamtape"
        elif "vidara" in domain:
            return "⚡ Vidara"
        elif "streamfile" in domain:
            return "📥 Streamfiles"
        elif any(m in domain for m in LPLAYGO_MIRRORS):
            return "▶️ iPlayGo"
        elif any(m in domain for m in ABSTREAM_MIRRORS):
            return "📺 ABStream"
        elif "uqload" in domain:
            return "⚡ Uqload"
        elif "streamcash" in domain:
            return "💰 Streamcash"
        elif any(m in domain for m in DOOD_MIRRORS):
            return "🎥 Doodstream"
        elif any(m in domain for m in STREAMWISH_MIRRORS):
            return "✨ Streamwish"
        elif any(m in domain for m in FILELIONS_MIRRORS):
            return "🦁 Filelions"
        elif "dropload" in domain:
            return "📦 Dropload"
        elif any(m in domain for m in MIXDROP_MIRRORS):
            return "💧 Mixdrop"
        elif "streamruby" in domain:
            return "💎 Streamruby"
        elif "cloudfam" in domain:
            return "☁️ Cloudfam"
        else:
            clean = domain.replace("www.", "").split(".")[0].capitalize()
            return f"🎬 {clean}"
    except Exception:
        return "🎬 Watch Video"


def get_host_key(url: str) -> str:
    """Extract standard key for a streaming provider (e.g. streamtape, vidara)."""
    try:
        u_low = url.lower()
        clean_path = u_low.split("?")[0]
        domain = urlparse(url).netloc.lower()
        if "mmsvibex" in domain or clean_path.endswith(".mp4") or "/processed/" in u_low:
            return "direct_mp4"
        elif clean_path.endswith(".zip") or "/downloads/" in u_low:
            return "direct_zip"
        elif any(m in domain for m in STREAMTAPE_MIRRORS):
            return "streamtape"
        elif "vidara" in domain:
            return "vidara"
        elif "streamfile" in domain:
            return "streamfiles"
        elif any(m in domain for m in LPLAYGO_MIRRORS):
            return "iplaygo"
        elif any(m in domain for m in ABSTREAM_MIRRORS):
            return "abstream"
        elif "uqload" in domain:
            return "uqload"
        elif "streamcash" in domain:
            return "streamcash"
        elif any(m in domain for m in DOOD_MIRRORS):
            return "doodstream"
        elif any(m in domain for m in STREAMWISH_MIRRORS):
            return "streamwish"
        elif any(m in domain for m in FILELIONS_MIRRORS):
            return "filelions"
        elif "dropload" in domain:
            return "dropload"
        elif any(m in domain for m in MIXDROP_MIRRORS):
            return "mixdrop"
        elif "streamruby" in domain:
            return "streamruby"
        elif "cloudfam" in domain:
            return "cloudfam"
        else:
            return domain.replace("www.", "").split(".")[0]
    except Exception:
        return "other"


def filter_links_by_preference(links: list[str], preferred_host: str = "streamtape") -> tuple[str, list[str], bool]:
    """
    Filter streaming links according to user preference with smart fallback following PROVIDER_PRIORITY.
    Returns: (display_name, filtered_links, is_fallback)
    - If preferred_host == 'all': returns all links.
    - If preferred_host exists in links: returns only those links.
    - If preferred_host NOT in links: falls back to the highest available provider in PROVIDER_PRIORITY.
    """
    if not links:
        return "None", [], False

    pref = preferred_host.lower().strip() if preferred_host else "streamtape"
    if pref == "lplaygo":
        pref = "iplaygo"

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

    # 2. Smart Fallback: iterate over PROVIDER_PRIORITY to pick the next highest available host
    for priority_host in PROVIDER_PRIORITY:
        p_key = "iplaygo" if priority_host == "lplaygo" else priority_host
        if p_key in grouped:
            return host_display_map[p_key], grouped[p_key], True

    # 3. If none match PROVIDER_PRIORITY, take the first available provider
    first_key = next(iter(grouped))
    return host_display_map[first_key], grouped[first_key], True


def extract_tags_and_quality(title: str) -> tuple[str, list[str]]:
    """Extract quality and tags from topic title (e.g. 1080p, 4K, HD, Exclusive)."""
    tags = []
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


_cffi_session = None


def get_cffi_session():
    """Get or create persistent curl_cffi Session with cookies preserved across requests."""
    global _cffi_session, HAS_CURL_CFFI, cffi_requests
    if _cffi_session is not None:
        return _cffi_session

    if not HAS_CURL_CFFI:
        try:
            from curl_cffi import requests as cffi_req
            cffi_requests = cffi_req
            HAS_CURL_CFFI = True
        except ImportError:
            try:
                import subprocess
                import sys
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "curl_cffi>=0.7.0"])
                from curl_cffi import requests as cffi_req
                cffi_requests = cffi_req
                HAS_CURL_CFFI = True
            except Exception as e:
                logger.warning(f"Could not initialize curl_cffi: {e}")
                return None

    if HAS_CURL_CFFI and cffi_requests is not None:
        try:
            _cffi_session = cffi_requests.Session(impersonate="chrome120")
            if PROXIES:
                _cffi_session.proxies.update(PROXIES)
            return _cffi_session
        except Exception as e:
            logger.debug(f"Failed to create cffi Session: {e}")
            return None
    return None


def _fetch_url(url: str, timeout: int = REQUEST_TIMEOUT):
    """
    Intelligent multi-tier HTTP fetcher:
    - Bypasses Cloudflare anti-bot 403 using persistent curl_cffi Session.
    - Falls back to cloudscraper if curl_cffi is unavailable or fails.
    - Uses robust requests.Session for standard sites with connection pooling.
    """
    is_cf_target = any(d in url.lower() for d in ["livecamrips.to", "leakedzone.com", "omaal63.net", "desijugar.me", "gulabihub.com"])

    domain_match = re.search(r"https?://[^/]+", url)
    fetch_headers = dict(HEADERS)
    if domain_match:
        fetch_headers["Referer"] = domain_match.group(0) + "/"

    if is_cf_target:
        session = get_cffi_session()
        if session:
            for browser in ["chrome120", "chrome124", "safari17_0", "edge101"]:
                try:
                    resp = session.get(url, headers=fetch_headers, impersonate=browser, timeout=timeout)
                    if resp.status_code < 400:
                        return resp
                    logger.debug(f"curl_cffi ({browser}) returned status {resp.status_code} for {url}")
                except Exception as e:
                    logger.debug(f"curl_cffi ({browser}) note for {url}: {e}")

        if HAS_CLOUDSCRAPER:
            try:
                scraper = cloudscraper.create_scraper()
                resp = scraper.get(
                    url,
                    timeout=timeout,
                    headers=fetch_headers,
                    proxies=PROXIES if PROXIES else None,
                )
                if resp.status_code < 400:
                    return resp
            except Exception as e:
                logger.debug(f"cloudscraper fetch note for {url}: {e}")

    resp = _session.get(url, headers=fetch_headers, timeout=timeout)
    if resp.status_code == 403:
        session = get_cffi_session()
        if session:
            for browser in ["chrome120", "chrome124"]:
                try:
                    cffi_resp = session.get(url, headers=fetch_headers, impersonate=browser, timeout=timeout)
                    if cffi_resp.status_code < 400:
                        return cffi_resp
                except Exception:
                    pass
        if HAS_CLOUDSCRAPER:
            try:
                scraper = cloudscraper.create_scraper()
                cs_resp = scraper.get(
                    url,
                    timeout=timeout,
                    headers=fetch_headers,
                    proxies=PROXIES if PROXIES else None,
                )
                if cs_resp.status_code < 400:
                    return cs_resp
            except Exception:
                pass

    resp.raise_for_status()
    return resp


def _fetch_soup(url: str) -> BeautifulSoup:
    """Safely fetch URL and return parsed BeautifulSoup object."""
    import sys
    scraper_mod = sys.modules.get("scraper")
    if scraper_mod is not None:
        mock_fn = getattr(scraper_mod, "_fetch_soup", None)
        if mock_fn is not None and mock_fn is not _fetch_soup:
            return mock_fn(url)

    try:
        resp = _fetch_url(url, timeout=REQUEST_TIMEOUT)
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
        if status_code == 404:
            logger.debug(f"HTTP 404 for {url}: {reason}")
        else:
            logger.error(f"HTTP error for {url}: {status_code} - {reason}")
        raise RuntimeError(f"HTTP Error {status_code}: {reason}") from e
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        raise RuntimeError(f"Error fetching page: {str(e)}") from e


IST_TZ = timezone(timedelta(hours=5, minutes=30))


class UniversalSort(str, Enum):
    """Standardized sorting types supported across video and forum engines."""
    NEWEST = "newest"
    MOST_VIEWED = "most_viewed"
    POPULAR = "popular"
    OLDEST = "oldest"
    LONGEST = "longest"


SORT_DISPLAY_NAMES = {
    UniversalSort.NEWEST: "🆕 Newest",
    UniversalSort.MOST_VIEWED: "🔥 Most Viewed",
    UniversalSort.POPULAR: "❤️ Popular",
    UniversalSort.OLDEST: "⏳ Oldest",
    UniversalSort.LONGEST: "⏱️ Longest",
}


def parse_relative_to_ist(text: str | None) -> datetime | None:
    """Parse relative time phrases like '2 hours ago', 'Yesterday at 9:30 PM', '15 mins ago' into IST datetime."""
    if not text:
        return None
    s = str(text).strip().lower()
    now_ist = datetime.now(timezone.utc).astimezone(IST_TZ)

    if any(k in s for k in ["just now", "moments ago", "a moment ago", "seconds ago"]):
        return now_ist

    m = re.search(r"\b(\d+)\s*(?:m|min|mins|minute|minutes)\s*ago\b", s)
    if m:
        return now_ist - timedelta(minutes=int(m.group(1)))

    m = re.search(r"\b(\d+)\s*(?:h|hr|hrs|hour|hours)\s*ago\b", s)
    if m:
        return now_ist - timedelta(hours=int(m.group(1)))

    if "yesterday" in s:
        m_time = re.search(r"(\d{1,2}):(\d{2})(?:\s*([ap]m))?", s)
        base = now_ist - timedelta(days=1)
        if m_time:
            hr = int(m_time.group(1))
            mn = int(m_time.group(2))
            meridiem = m_time.group(3)
            if meridiem:
                if meridiem == "pm" and hr < 12:
                    hr += 12
                elif meridiem == "am" and hr == 12:
                    hr = 0
            return base.replace(hour=hr, minute=mn, second=0, microsecond=0)
        return base.replace(hour=12, minute=0, second=0, microsecond=0)

    if "today" in s:
        m_time = re.search(r"(\d{1,2}):(\d{2})(?:\s*([ap]m))?", s)
        if m_time:
            hr = int(m_time.group(1))
            mn = int(m_time.group(2))
            meridiem = m_time.group(3)
            if meridiem:
                if meridiem == "pm" and hr < 12:
                    hr += 12
                elif meridiem == "am" and hr == 12:
                    hr = 0
            return now_ist.replace(hour=hr, minute=mn, second=0, microsecond=0)
        return now_ist

    m = re.search(r"\b(\d+)\s*(?:d|day|days)\s*ago\b", s)
    if m:
        return now_ist - timedelta(days=int(m.group(1)))

    m = re.search(r"\b(\d+)\s*(?:w|wk|weeks)\s*ago\b", s)
    if m:
        return now_ist - timedelta(weeks=int(m.group(1)))

    m = re.search(r"\b(\d+)\s*(?:mo|month|months)\s*ago\b", s)
    if m:
        return now_ist - timedelta(days=int(m.group(1)) * 30)

    m = re.search(r"\b(\d+)\s*(?:y|yr|years)\s*ago\b", s)
    if m:
        return now_ist - timedelta(days=int(m.group(1)) * 365)

    return None


def parse_to_ist(date_str: str | None) -> datetime | None:
    """Parse ISO UTC timestamp (or string) and convert to Indian Standard Time (IST, UTC+05:30)."""
    if not date_str:
        return None
    s = str(date_str).strip()
    try:
        cleaned_iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST_TZ)
    except Exception:
        pass

    for fmt in (
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %I:%M%p",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %I:%M %p",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d %b %Y %I:%M %p",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%B %d, %Y, %I:%M %p",
        "%B %d, %Y %I:%M %p",
        "%B %d, %Y at %I:%M %p",
        "%b %d, %Y, %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%b %d, %Y at %I:%M %p",
        "%d %b %Y, %I:%M %p",
        "%d %B %Y, %I:%M %p",
        "%d %b %Y at %I:%M %p",
        "%m/%d/%Y at %I:%M %p",
        "%d/%m/%Y at %I:%M %p",
        "%m/%d/%Y, %I:%M %p",
        "%d/%m/%Y, %I:%M %p",
        "%Y-%m-%d %I:%M %p",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(IST_TZ)
        except Exception:
            continue

    # Fallback to relative text
    return parse_relative_to_ist(s)


def extract_date_from_url(url: str | None) -> datetime | None:
    """Extract date from URL path pattern like /2026/11/22/post-name/."""
    if not url:
        return None
    m = re.search(r"/(202\d)/(\d{1,2})/(\d{1,2})/", url)
    if m:
        try:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)
            return dt.astimezone(IST_TZ)
        except Exception:
            pass
    return None


def format_date_ist(date_input: datetime | str | None, include_time: bool = True) -> str | None:
    """Format timestamp into standardized human-readable IST string: '20 Nov 2026, 11:50 AM IST'."""
    if not date_input:
        return None
    if isinstance(date_input, datetime):
        dt_ist = date_input.astimezone(IST_TZ) if date_input.tzinfo else date_input.replace(tzinfo=IST_TZ)
    else:
        dt_ist = parse_to_ist(date_input)
    if not dt_ist:
        return None
    if include_time:
        return dt_ist.strftime("%d %b %Y, %I:%M %p IST")
    return dt_ist.strftime("%d %b %Y IST")


class UniversalDateResolver:
    """
    Robust multi-tier date and timestamp resolver for all web scraper engines.
    Tiers:
    1. Authoritative machine tags (<meta article:published_time>, JSON-LD, <time datetime="...">).
    2. URL path regex (/YYYY/MM/DD/).
    3. Author-specific relative text parsed to IST.
    4. Database first-seen fallback for timeless tube platforms (e.g. MMSVibex).
    """

    @staticmethod
    def resolve(
        soup: BeautifulSoup | None = None,
        url: str | None = None,
        raw_date: str | None = None,
        time_text: str | None = None,
        fallback_db_url: str | None = None,
        title: str = "",
    ) -> tuple[datetime | None, str | None]:
        """Resolve post date into (datetime_ist, formatted_string_ist)."""
        # Tier 1: Direct raw date string
        if raw_date:
            dt = parse_to_ist(raw_date)
            if dt:
                return dt, format_date_ist(dt)

        # Tier 1b: Check soup metadata & first post content
        if soup:
            # Check meta tags
            for prop in ("article:published_time", "og:published_time", "publication_date", "datePublished", "uploadDate"):
                meta = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
                if meta and meta.get("content"):
                    dt = parse_to_ist(meta["content"])
                    if dt:
                        return dt, format_date_ist(dt)

            # JSON-LD
            for s in soup.find_all("script", type="application/ld+json"):
                text = s.string or s.get_text()
                if text and ("datePublished" in text or "uploadDate" in text):
                    m_date = re.search(r'"(?:datePublished|uploadDate)"\s*:\s*"([^"]+)"', text)
                    if m_date:
                        dt = parse_to_ist(m_date.group(1))
                        if dt:
                            return dt, format_date_ist(dt)

            # Look for <time> tags - prioritize the first post container if present
            first_post = soup.select_one(".cPost, .ipsComment, [data-role='comment'], article.post, .entry-content")
            search_scope = first_post if first_post else soup

            for t_elem in search_scope.find_all("time"):
                for attr in ("datetime", "title"):
                    val = t_elem.get(attr)
                    if val:
                        dt = parse_to_ist(val)
                        if dt:
                            return dt, format_date_ist(dt)
                txt = t_elem.get_text(strip=True)
                if txt:
                    dt = parse_to_ist(txt)
                    if dt:
                        return dt, format_date_ist(dt)

            # Fallback across entire soup if not found in first_post
            if search_scope is not soup:
                for t_elem in soup.find_all("time"):
                    for attr in ("datetime", "title"):
                        val = t_elem.get(attr)
                        if val:
                            dt = parse_to_ist(val)
                            if dt:
                                return dt, format_date_ist(dt)
                    txt = t_elem.get_text(strip=True)
                    if txt:
                        dt = parse_to_ist(txt)
                        if dt:
                            return dt, format_date_ist(dt)

        # Tier 2: URL regex
        if url:
            dt = extract_date_from_url(url)
            if dt:
                return dt, format_date_ist(dt, include_time=False)

        # Tier 3: Relative time text
        if time_text:
            dt = parse_to_ist(time_text)
            if dt:
                return dt, format_date_ist(dt)

        # Tier 4: Database first-seen fallback for timeless tube sites
        if fallback_db_url:
            try:
                import db
                seen_dt = db.get_or_record_first_seen(fallback_db_url, title=title)
                if seen_dt:
                    dt_ist = seen_dt.astimezone(IST_TZ)
                    return dt_ist, f"Discovered: {dt_ist.strftime('%d %b %Y')} (Recent)"
            except Exception:
                pass

        return None, None


def check_date_filter_match(
    date_str: str | None,
    time_text: str | None,
    date_filter: str = "today",
    full_row_text: str | None = None,
) -> tuple[bool, bool]:
    """
    Check if a post timestamp matches the requested date filter in Indian Standard Time (IST).
    Returns (is_match: bool, is_older: bool).

    Priority:
    1. Explicit 'yesterday' or multi-day relative text rejects 'today' immediately.
    2. Authoritative machine ISO from <time datetime="..."> or valid date_str converted to IST.
    3. Fall back to relative text and calendar regex only when machine ISO timestamp is absent.
    """
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST_TZ)
    today_ist = now_ist.date()
    yesterday_ist = today_ist - timedelta(days=1)

    tt = str(time_text or "").strip().lower()
    fr = str(full_row_text or "").strip().lower()
    combined_text = f"{tt} {fr}".strip()

    # Rule 1: Explicit relative date text saying 'yesterday' or days/weeks/months ago rejects 'today'
    if date_filter == "today":
        if re.search(r"\byesterday\b", combined_text):
            return False, True
        if re.search(r"\b\d+\s*(?:d|day|days|w|wk|weeks|mo|month|months|y|yr|years)\b", combined_text):
            return False, True

    elif date_filter in ["yesterday", "2days"]:
        m_day = re.search(r"\b(\d+)\s*(?:d|day|days)\b", combined_text)
        if m_day and int(m_day.group(1)) >= 2:
            return False, True
        if re.search(r"\b\d+\s*(?:w|wk|weeks|mo|month|months|y|yr|years)\b", combined_text):
            return False, True

    # Rule 2: Authoritative machine ISO from <time datetime="..."> takes priority!
    dt_ist = parse_to_ist(date_str)
    if dt_ist:
        post_date = dt_ist.date()
        if date_filter == "today":
            if post_date == today_ist:
                return True, False
            elif post_date < today_ist:
                return False, True
            else:
                return True, False
        elif date_filter in ["yesterday", "2days"]:
            if post_date >= yesterday_ist:
                return True, False
            else:
                return False, True

    # Rule 3: If machine ISO is absent, check relative text & author context
    if date_filter == "today":
        if any(w in combined_text for w in ["today", "just now", "moment"]):
            return True, False

        m_hr = re.search(r"\b(\d+)\s*(?:h|hr|hrs|hour|hours)\b", combined_text)
        if m_hr:
            hrs = int(m_hr.group(1))
            hrs_today = now_ist.hour + (now_ist.minute / 60.0) + 0.5
            if hrs <= hrs_today:
                return True, False
            else:
                return False, True

        if re.search(r"\b\d+\s*(?:m|min|mins|minute|minutes|s|sec|secs)\b", combined_text):
            return True, False

    elif date_filter in ["yesterday", "2days"]:
        if any(w in combined_text for w in ["yesterday", "today", "just now", "moment"]):
            return True, False
        if re.search(r"\b\d+\s*(?:m|min|mins|minute|minutes|s|sec|secs)\b", combined_text):
            return True, False
        m_hr = re.search(r"\b(\d+)\s*(?:h|hr|hrs|hour|hours)\b", combined_text)
        if m_hr:
            hrs = int(m_hr.group(1))
            if hrs <= 48:
                return True, False
            else:
                return False, True

    # Rule 4: Explicit calendar dates in relative text
    if date_filter == "today" and combined_text:
        today_days = {str(now_ist.day), f"{now_ist.day:02d}", str(now_utc.day), f"{now_utc.day:02d}"}
        today_months = {
            now_ist.strftime("%b").lower(), now_ist.strftime("%B").lower(),
            now_utc.strftime("%b").lower(), now_utc.strftime("%B").lower()
        }
        for m in today_months:
            if m in combined_text:
                for d in today_days:
                    if re.search(rf"\b{d}\b", combined_text):
                        return True, False
                return False, True
        all_months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
        if any(m in combined_text for m in all_months):
            return False, True

    return False, False


def _is_posted_today(date_str: str | None, time_text: str | None, full_row_text: str | None = None) -> tuple[bool, bool]:
    """Check if post was made today."""
    return check_date_filter_match(date_str, time_text, date_filter="today", full_row_text=full_row_text)


def resolve_cloudfam_url(url: str, timeout: int = 15) -> str | None:
    """Resolve a cloudfam.io download page to its direct pre-signed S3 download URL."""
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        session.headers["Referer"] = "https://dropmms.com/"

        resp = session.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")

        next_a = soup.find("a", href=lambda h: h and "redirection" in h)
        if not next_a:
            return None
        red0_url = urljoin(str(resp.url), next_a["href"])
        resp2 = session.get(red0_url, timeout=timeout, allow_redirects=True)
        if resp2.status_code != 200:
            return None
        soup2 = BeautifulSoup(resp2.text, "html.parser")

        btn_free = soup2.find(id="cf-btn-free")
        if not btn_free or not btn_free.get("href"):
            return None
        red1_url = urljoin(str(resp2.url), btn_free["href"])
        resp3 = session.get(red1_url, timeout=timeout, allow_redirects=True)
        if resp3.status_code != 200:
            return None
        soup3 = BeautifulSoup(resp3.text, "html.parser")

        btn_upsell = soup3.find(id="free-btn")
        if not btn_upsell or not btn_upsell.get("href"):
            return None
        upsell_url = urljoin(str(resp3.url), btn_upsell["href"])
        resp4 = session.get(upsell_url, timeout=timeout, allow_redirects=True)
        if resp4.status_code != 200:
            return None
        soup4 = BeautifulSoup(resp4.text, "html.parser")

        btn_continue = soup4.find(id="free-continue")
        if not btn_continue or not btn_continue.get("href"):
            return None
        step2_url = urljoin(str(resp4.url), btn_continue["href"])
        resp5 = session.get(step2_url, timeout=timeout, allow_redirects=True)
        if resp5.status_code != 200:
            return None
        soup5 = BeautifulSoup(resp5.text, "html.parser")

        btn_dl = soup5.find(id="cf-dl-btn")
        if not btn_dl or not btn_dl.get("href"):
            return None
        dl_handler_url = urljoin(str(resp5.url), btn_dl["href"])
        resp_final = session.get(dl_handler_url, timeout=timeout, allow_redirects=True)
        if resp_final.status_code == 200:
            return str(resp_final.url)
        return None
    except Exception as e:
        logger.warning(f"Error resolving cloudfam URL {url}: {e}")
        return None


def _is_valid_thumbnail_url(url: str) -> bool:
    """Validate if an image URL is an actual video thumbnail."""
    if not url or not isinstance(url, str):
        return False
    lower = url.lower().strip()
    if not lower.startswith("http://") and not lower.startswith("https://"):
        return False

    blacklisted = [
        "blank.gif", "blank.png", "spacer.gif", "spacer.png", "transparent",
        "1x1", "pixel.gif", "default_og", "default_avatar", "avatar",
        "/storage/models/", "storage/models",
        "userphoto", "ipsuserphoto", "profile", "member", "emoticons",
        "smile", "reaction", "react", "site_logo", "logo.png", "logo.jpg",
        "logo.svg", "loading.gif", "placeholder", "svg+xml", "attachment-icon",
        "theme_logo", "badge", "rank", "signature", "star.png", "icon_",
        "favicon", "cerrar", "close.png", "close.gif", "btn_close",
        "i.t.net.ar", "ad_banner", "ad_overlay",
    ]
    if any(b in lower for b in blacklisted):
        return False
    return True


def _clean_highres_image_url(url: str) -> str:
    """Convert thumbnail / scaled forum URLs to their full-size original image URLs."""
    if not url or not isinstance(url, str):
        return url

    cleaned = url.strip()
    cleaned = re.sub(r'\.thumb\.(jpg|jpeg|png|webp)(\.[a-f0-9]+)?$', r'.\1', cleaned, flags=re.I)
    cleaned = re.sub(r'\.thumb\.', '.', cleaned, flags=re.I)

    if "pixhost.to/thumbs/" in cleaned:
        cleaned = cleaned.replace("/thumbs/", "/images/")
        cleaned = re.sub(r'https?://t(\d+)\.pixhost\.to', r'https://img\1.pixhost.to', cleaned)

    if "imgbox.com" in cleaned and "thumbs" in cleaned:
        cleaned = cleaned.replace("thumbs", "images").replace("_t.", "_o.")

    if "postimg.cc" in cleaned and "/t/" in cleaned:
        cleaned = cleaned.replace("/t/", "/")

    if "leakedzone.com" in cleaned:
        cleaned = re.sub(r'(_300)(\.webp)$', r'\2', cleaned, flags=re.I)

    cleaned = re.sub(r'-\d+x\d+\.(jpg|jpeg|png|webp)', r'.\1', cleaned, flags=re.I)
    return cleaned


def _extract_all_image_candidates(soup: BeautifulSoup, post_url: str) -> list[str]:
    """Extract all valid image URLs from a post body."""
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

    main_post = soup.find(["article", "div"], class_=re.compile(r"\bcPost\b", re.I))
    if not main_post:
        main_post = soup

    post_body = main_post.find("div", attrs={"data-role": "commentContent"})
    if not post_body:
        post_body = main_post.find("div", class_=re.compile(r"commentContent|ipsType_richText", re.I))
    if not post_body:
        post_body = main_post

    for img in post_body.find_all("img", class_=re.compile(r"ipsImage", re.I)):
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

    for a in post_body.find_all("a", class_=re.compile(r"ipsAttachLink", re.I)):
        if a.get("href"):
            add_candidate(a["href"])

    for a in post_body.find_all("a", href=True):
        href = a["href"].strip()
        lower_href = href.lower().split("?")[0]
        if any(lower_href.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]):
            add_candidate(href)
        elif any(ih in lower_href for ih in ["postimg", "pixhost", "imgbox", "imagebam", "ibb.co", "turboimagehost", "imx.to", "picbaron"]):
            add_candidate(href)

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
    """Strictly verify that data contains valid image magic bytes."""
    if not data or len(data) < 512:
        return False
    prefix = data[:32].strip()
    if prefix.startswith(b"<") or b"<!doc" in prefix.lower() or b"<html" in prefix.lower():
        return False
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:2] == b"BM":
        return True
    return False


def is_valid_thumbnail_image(data: bytes, min_width: int = 180, min_height: int = 180) -> bool:
    """Verify with Pillow that downloaded data is a valid image with adequate resolution."""
    if not data or len(data) < 512:
        return False
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if w < min_width and h < min_height:
                logger.info(f"Rejected candidate image ({w}x{h} px): below minimum thumbnail dimensions.")
                return False
            return True
    except Exception as e:
        logger.debug(f"Pillow could not parse image dimensions: {e}")
        return True


def optimize_image_for_telegram(data: bytes) -> bytes:
    """Ensure the image displays fully in Telegram chat bubbles without getting cropped."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            w, h = im.size
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
    """Extract direct image URL from an image host viewer webpage."""
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        for meta_attr in [("property", "og:image"), ("name", "og:image"), ("name", "twitter:image")]:
            tag = soup.find("meta", attrs={meta_attr[0]: meta_attr[1]})
            if tag and tag.get("content"):
                c = tag["content"].strip()
                if _is_valid_thumbnail_url(c) and any(c.lower().split("?")[0].endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    return urljoin(viewer_url, c)

        main_img = (
            soup.find("img", class_=re.compile(r"\b(pic|img|centred|main-image|main_image)\b", re.I))
            or soup.find("img", id=re.compile(r"^(main-image|image|show_image|img_obj|pic)$", re.I))
        )
        if main_img and main_img.get("src"):
            src = main_img["src"].strip()
            if _is_valid_thumbnail_url(src):
                return urljoin(viewer_url, src)

        for img in soup.find_all("img", src=True):
            src = img["src"].strip()
            if any(src.lower().split("?")[0].endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if _is_valid_thumbnail_url(src):
                    return urljoin(viewer_url, src)
    except Exception:
        pass
    return None


def download_image_bytes(image_url: str) -> bytes | None:
    """Download image into memory using intelligent multi-tier fetcher."""
    if not image_url or not isinstance(image_url, str):
        return None
    try:
        resp = _fetch_url(image_url, timeout=12)
        if resp.status_code != 200 or not resp.content:
            return None

        if is_valid_image_bytes(resp.content):
            if is_valid_thumbnail_image(resp.content):
                return optimize_image_for_telegram(resp.content)
            else:
                logger.info(f"Skipping candidate {image_url}: failed dimension verification (likely avatar/icon).")
                return None

        content_type = resp.headers.get("Content-Type", "").lower()
        if "text/html" in content_type or resp.content[:1] == b"<":
            direct_img_url = _resolve_image_viewer_url(image_url, resp.text)
            if direct_img_url and direct_img_url != image_url:
                direct_resp = _fetch_url(direct_img_url, timeout=12)
                if direct_resp.status_code == 200 and is_valid_image_bytes(direct_resp.content):
                    if is_valid_thumbnail_image(direct_resp.content):
                        return optimize_image_for_telegram(direct_resp.content)

    except Exception as e:
        logger.warning(f"Could not download thumbnail bytes from {image_url}: {e}")
    return None


def parse_slicing_args(args: list[str]) -> tuple[str | None, int | None, int | None, bool]:
    """Parse target URL and user slice parameters from command arguments."""
    if not args:
        return None, None, None, False

    target_url = None
    remaining = []

    for arg in args:
        a = arg.strip()
        if re.match(r"^https?://", a, re.I) or any(
            d in a.lower()
            for d in [
                "dropmms.com",
                "mmstown.com",
                "mmsvibex.life",
                "gulabihub.com",
                "omaal63.net",
                "desijugar.me",
                "livecamrips.to",
            ]
        ):
            target_url = a
        else:
            remaining.append(a)

    text = " ".join(remaining).strip().lower()
    if not text:
        return target_url, None, None, False

    m_last = re.search(r"last\s*(\d+)", text)
    if m_last:
        count = int(m_last.group(1))
        return target_url, None, count, True

    m_range = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)", text)
    if m_range:
        start_i = int(m_range.group(1))
        end_i = int(m_range.group(2))
        return target_url, start_i, end_i, False

    m_count = re.search(r"(?:count\s*)?(\d+)", text)
    if m_count:
        count = int(m_count.group(1))
        return target_url, 1, count, False

    return target_url, None, None, False


def apply_slice(items: list, start_idx: int | None = None, end_idx: int | None = None, is_last_n: bool = False) -> list:
    """Apply 1-based slicing, range, or last-N filtering to a list of items."""
    if not items:
        return []
    if is_last_n and end_idx is not None and end_idx > 0:
        return items[-end_idx:]
    if start_idx is not None and end_idx is not None:
        s = max(0, start_idx - 1)
        e = max(s, end_idx)
        return items[s:e]
    if end_idx is not None and end_idx > 0:
        return items[:end_idx]
    return items


def parse_model_range_input(text: str) -> tuple[int | None, int | None, int | None]:
    """Parse user range input for scraping (e.g. '5', '1-5', 'page 2')."""
    t = text.strip().lower()

    m_page = re.match(r"^(?:page\s*|p\s*)(\d+)$", t)
    if m_page:
        p = int(m_page.group(1))
        return (None, None, p) if p > 0 else (None, None, None)

    m_range = re.match(r"^(\d+)\s*(?:-|to|:|\.\.)\s*(\d+)$", t)
    if m_range:
        s, e = int(m_range.group(1)), int(m_range.group(2))
        if s > e:
            s, e = e, s
        if e < 1:
            return (None, None, None)
        s = max(1, s)
        return (s, e, None)

    if t.isdigit():
        n = int(t)
        return (1, n, None) if n > 0 else (None, None, None)

    return (None, None, None)


class BaseEngine:
    """Base class for all scraper engines."""
    name: str = "Base"
    domains: list[str] = []
    supported_sorts: dict[UniversalSort, str] = {
        UniversalSort.NEWEST: "newest",
    }

    def get_sort_param(self, sort_type: UniversalSort | str) -> str:
        """Resolve universal sort into platform-specific parameter."""
        if isinstance(sort_type, str):
            try:
                sort_type = UniversalSort(sort_type.lower())
            except Exception:
                return str(sort_type)
        return self.supported_sorts.get(sort_type, "newest")

    def is_supported_url(self, url: str) -> bool:
        if not url or not isinstance(url, str):
            return False
        u_low = url.lower()
        return any(d in u_low for d in self.domains)

    def is_listing_url(self, url: str) -> bool:
        return False

    def is_detail_url(self, url: str) -> bool:
        return False

    def get_details(self, url: str) -> dict:
        raise NotImplementedError

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        raise NotImplementedError

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        raise NotImplementedError
