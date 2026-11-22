# scraper.py

import re
import io
import html
import logging
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


def _is_streaming_link(url: str) -> bool:
    """Check if URL belongs to any supported streaming domain or direct video/archive link."""
    if not url or not isinstance(url, str):
        return False
    try:
        u_low = url.lower().split("?")[0].strip()
        if u_low.endswith(".mp4") or u_low.endswith(".zip"):
            return True
        if "/downloads/" in u_low and ".zip" in u_low:
            return True
        if "/processed/" in u_low and ".mp4" in u_low:
            return True
        domain = urlparse(url).netloc.lower()
        if not domain:
            domain = url.split("/")[0].lower()
        return any(sd in domain for sd in STREAMING_DOMAINS)
    except Exception:
        return False


# Provider Priority Order (Highest -> Lowest)
# Direct CDN Media -> Streamtape -> Vidara -> Streamfiles -> iPlayGo/Lplaygo -> ABStream -> Uqload -> Streamcash -> Rest
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
        elif "streamtape" in domain:
            return "🎬 Streamtape"
        elif "vidara" in domain:
            return "⚡ Vidara"
        elif "streamfile" in domain:
            return "📥 Streamfiles"
        elif "iplaygo" in domain or "lplaygo" in domain:
            return "▶️ iPlayGo"
        elif "abstream" in domain:
            return "📺 ABStream"
        elif "uqload" in domain:
            return "⚡ Uqload"
        elif "streamcash" in domain:
            return "💰 Streamcash"
        elif "dood" in domain:
            return "🎥 Doodstream"
        elif "streamwish" in domain:
            return "✨ Streamwish"
        elif "filelions" in domain:
            return "🦁 Filelions"
        elif "dropload" in domain:
            return "📦 Dropload"
        elif "mixdrop" in domain or "mdzsmutpcvykb" in domain:
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
        elif "streamtape" in domain:
            return "streamtape"
        elif "vidara" in domain:
            return "vidara"
        elif "streamfile" in domain:
            return "streamfiles"
        elif "iplaygo" in domain or "lplaygo" in domain:
            return "iplaygo"
        elif "abstream" in domain:
            return "abstream"
        elif "uqload" in domain:
            return "uqload"
        elif "streamcash" in domain:
            return "streamcash"
        elif "dood" in domain:
            return "doodstream"
        elif "streamwish" in domain:
            return "streamwish"
        elif "filelions" in domain:
            return "filelions"
        elif "dropload" in domain:
            return "dropload"
        elif "mixdrop" in domain or "mdzsmutpcvykb" in domain:
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
    - Bypasses Cloudflare anti-bot 403 on Google Colab / datacenter IPs using persistent curl_cffi Session
      with authentic browser TLS/HTTP-2 fingerprint and session cookie persistence.
    - Falls back to cloudscraper if curl_cffi is unavailable or fails.
    - Uses robust requests.Session for standard sites with connection pooling.
    """
    is_cf_target = "livecamrips.to" in url.lower()

    # Priority 1: curl_cffi Session for Cloudflare-protected domains (livecamrips.to)
    if is_cf_target:
        session = get_cffi_session()
        if session:
            for browser in ["chrome120", "chrome124", "safari17_0", "edge101"]:
                try:
                    resp = session.get(url, impersonate=browser, timeout=timeout)
                    if resp.status_code < 400:
                        return resp
                    logger.debug(f"curl_cffi ({browser}) returned status {resp.status_code} for {url}")
                except Exception as e:
                    logger.debug(f"curl_cffi ({browser}) note for {url}: {e}")

        # Priority 2: cloudscraper fallback
        if HAS_CLOUDSCRAPER:
            try:
                scraper = cloudscraper.create_scraper()
                resp = scraper.get(
                    url,
                    timeout=timeout,
                    headers=HEADERS,
                    proxies=PROXIES if PROXIES else None,
                )
                if resp.status_code < 400:
                    return resp
            except Exception as e:
                logger.debug(f"cloudscraper fetch note for {url}: {e}")

    # Priority 3: Standard requests.Session
    resp = _session.get(url, timeout=timeout)
    if resp.status_code == 403:
        # Auto-retry with curl_cffi session if standard requests encountered 403 Forbidden
        session = get_cffi_session()
        if session:
            for browser in ["chrome120", "chrome124"]:
                try:
                    cffi_resp = session.get(url, impersonate=browser, timeout=timeout)
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
                    headers=HEADERS,
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


IST_TZ = timezone(timedelta(hours=5, minutes=30))


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
    ):
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(IST_TZ)
        except Exception:
            continue
    return None


def format_date_ist(date_str: str | None) -> str | None:
    """Format timestamp into human-readable IST string: '20 Nov 2026, 11:50 AM IST'."""
    dt_ist = parse_to_ist(date_str)
    if not dt_ist:
        return None
    return dt_ist.strftime("%d %b %Y, %I:%M %p IST")


def check_date_filter_match(
    date_str: str | None,
    time_text: str | None,
    date_filter: str = "today",
    full_row_text: str | None = None,
) -> tuple[bool, bool]:
    """
    Check if a post timestamp matches the requested date filter in Indian Standard Time (IST).
    Returns (is_match: bool, is_older: bool).
    date_filter options:
      - 'today': Posted today in IST (00:00 AM IST to now).
      - 'yesterday': Posted yesterday or today in IST (Last ~48 hours).
    """
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST_TZ)
    today_ist = now_ist.date()
    yesterday_ist = today_ist - timedelta(days=1)

    tt = str(time_text or "").strip().lower()
    fr = str(full_row_text or "").strip().lower()
    combined_text = f"{tt} {fr}".strip()

    # Rule 1: Explicit relative date text takes precedence
    if date_filter == "today":
        # If text explicitly says yesterday, days ago, weeks ago, etc. -> definitely NOT today
        if re.search(r"\byesterday\b", combined_text):
            return False, True
        if re.search(r"\b\d+\s*(?:d|day|days|w|wk|weeks|mo|month|months|y|yr|years)\b", combined_text):
            return False, True

        # If text explicitly says today, just now, a moment ago -> definitely today
        if any(w in combined_text for w in ["today", "just now", "moment"]):
            return True, False

        # If hours ago, check how many hours have actually elapsed since 00:00 IST today
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
        # If 2 or more days ago, definitely older
        m_day = re.search(r"\b(\d+)\s*(?:d|day|days)\b", combined_text)
        if m_day and int(m_day.group(1)) >= 2:
            return False, True
        if re.search(r"\b\d+\s*(?:w|wk|weeks|mo|month|months|y|yr|years)\b", combined_text):
            return False, True
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

    # Rule 2: Authoritative ISO from <time datetime="...">
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

    # Rule 3: Explicit calendar dates in relative text (e.g. "Nov 20", "20 Nov")
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
    """
    Check if a post timestamp, relative text, or row text indicates it was posted today.
    Handles Indian Standard Time (IST, UTC+05:30) and UTC/server time.
    Returns: (is_today: bool, is_definitely_older: bool)
    """
    return check_date_filter_match(date_str, time_text, date_filter="today", full_row_text=full_row_text)


def _extract_topics_from_soup(
    soup: BeautifulSoup,
    clean_base: str,
    seen: set,
    limit: int,
    active_date_filter: str | None = None,
) -> tuple[list[dict], bool, int]:
    """
    Extract topics from a single forum page's BeautifulSoup instance.
    Handles IPS Community row styles, extracting title, URL, IST timestamp, views,
    and applies date cutoff filtering (today, yesterday).
    Returns: (new_topics: list[dict], hit_older: bool, new_count: int)
    """
    row_elements = soup.find_all(["li", "div", "article", "tr"], class_=re.compile("ipsDataItem|cForumRow|cTopic", re.I))

    new_topics = []
    hit_older = False
    consecutive_older = 0
    new_count = 0

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

        full_url = urljoin(clean_base, link_elem["href"].strip())
        clean_url = _clean_topic_url(full_url)
        if clean_url in seen:
            continue

        # Skip pinned / sticky / announcement topics when filtering for date
        row_classes = " ".join(row.get("class", [])).lower()
        is_pinned = (
            "pinned" in row_classes
            or "featured" in row_classes
            or "announcement" in row_classes
            or bool(row.find(class_=re.compile(r"pinned|badge_pinned|fa-thumb-?tack|fa-star", re.I)))
            or bool(row.find(lambda t: t.name in ["span", "div", "i", "strong", "em"] and re.search(r"\b(pinned|featured|announcement)\b", t.get_text(), re.I)))
        )
        if is_pinned and active_date_filter:
            continue

        # Extract publication timestamp from topic creation container or row
        main_elem = row.find(class_=re.compile(r"ipsDataItem_main|cForumRow_main", re.I)) or row
        time_tag = main_elem.find("time") or row.find("time")
        date_str = (time_tag.get("datetime") or time_tag.get("title")) if time_tag else None
        time_text = time_tag.get_text(strip=True) if time_tag else None
        row_text = row.get_text(" ", strip=True)

        # Apply Live Date Cutoff when requested via date_filter
        if active_date_filter:
            is_match, is_older = check_date_filter_match(date_str, time_text, date_filter=active_date_filter, full_row_text=row_text)
            if is_older:
                consecutive_older += 1
                if consecutive_older >= 3:
                    logger.info(f"Hit date cutoff after {consecutive_older} older topic(s): '{link_elem.get_text(strip=True)}' (date={date_str}, time={time_text}, filter={active_date_filter}). Stopping scan.")
                    hit_older = True
                    break
                continue
            else:
                consecutive_older = 0

            if not is_match:
                continue

        seen.add(clean_url)
        new_count += 1
        title = link_elem.get_text(strip=True) or "Untitled Post"

        views_str = None
        views_elem = row.find("span", class_=re.compile("ipsType_light|cForumRow_views", re.I))
        if views_elem:
            views_str = views_elem.get_text(strip=True)

        new_topics.append({
            "title": title,
            "url": clean_url,
            "date": date_str,
            "date_ist": format_date_ist(date_str),
            "views": views_str,
        })

        if len(new_topics) >= limit:
            break

    # Fallback if row_elements yielded 0 topics and date cutoff was not reached
    if new_count == 0 and not hit_older:
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "/topic/" in href or "index.php?/topic/" in href:
                full_url = urljoin(clean_base, href)
                clean_url = _clean_topic_url(full_url)
                if clean_url not in seen:
                    if active_date_filter:
                        parent_row = a.find_parent(["li", "div", "article", "tr"])
                        t_tag = parent_row.find("time") if parent_row else None
                        d_str = (t_tag.get("datetime") or t_tag.get("title")) if t_tag else None
                        t_txt = t_tag.get_text(strip=True) if t_tag else None
                        m_match, _ = check_date_filter_match(d_str, t_txt, date_filter=active_date_filter)
                        if not m_match:
                            continue
                    seen.add(clean_url)
                    new_count += 1
                    t_title = a.get_text(strip=True) or "Untitled Post"
                    new_topics.append({"title": t_title, "url": clean_url, "date": None, "date_ist": None, "views": None})
                    if len(new_topics) >= limit:
                        break

    return new_topics, hit_older, new_count


def get_forum_topics(
    forum_url: str,
    sort_by: str = "start_date",
    limit: int = 25,
    only_today: bool = False,
    date_filter: str | None = None,
) -> list[dict]:
    """
    Fetch structured topics from a forum category with date-sorting, metadata, and multi-page pagination.
    sort_by options:
      - 'start_date': Sort by topic creation/upload date (Newest uploads first)
      - 'views': Sort by popularity/views
      - 'updated': Sort by last activity
    only_today:
      - If True: Filters for topics posted today in IST.
    date_filter:
      - 'today': Filter for topics posted today in IST.
      - 'yesterday': Filter for topics posted yesterday or today in IST (Last ~48h).
    """
    active_date_filter = date_filter or ("today" if only_today else None)
    # Detect if user specifically provided a starting page number (e.g. /page/2/ or ?page=2)
    start_page = 1
    m_path_page = re.search(r"/page/(\d+)/?", forum_url, re.I)
    if m_path_page:
        try:
            start_page = max(1, int(m_path_page.group(1)))
        except Exception:
            start_page = 1
    else:
        m_query_page = re.search(r"[?&]page=(\d+)", forum_url, re.I)
        if m_query_page:
            try:
                start_page = max(1, int(m_query_page.group(1)))
            except Exception:
                start_page = 1

    # Extract user-provided query parameters excluding page=
    query_str = ""
    if "?" in forum_url:
        raw_query = forum_url.split("?")[1].split("#")[0]
        filtered_parts = [p for p in raw_query.split("&") if not re.match(r"^page=\d+$", p, re.I)]
        query_str = "&".join(filtered_parts)

    # Normalize invalid or shorthand Invision Community sort keys
    if query_str:
        if "sortby=start_date" in query_str.lower() and "forums_topics.start_date" not in query_str.lower():
            query_str = re.sub(r"sortby=start_date", "sortby=forums_topics.start_date", query_str, flags=re.I)
        if "sortby=date" in query_str.lower() and "forums_topics.start_date" not in query_str.lower():
            query_str = re.sub(r"sortby=date", "sortby=forums_topics.start_date", query_str, flags=re.I)

    if not query_str:
        if sort_by == "start_date":
            query_str = "sortby=forums_topics.start_date&sortdirection=desc"
        elif sort_by == "views":
            query_str = "sortby=views&sortdirection=desc"
        elif sort_by == "updated":
            query_str = "sortby=last_post&sortdirection=desc"

    clean_base = forum_url.split("?")[0].split("#")[0]
    clean_base = re.sub(r"/page/\d+/?$", "/", clean_base)
    if not clean_base.endswith("/"):
        clean_base += "/"

    topics = []
    seen = set()
    current_page = start_page

    # Calculate max_pages
    if active_date_filter:
        max_pages = start_page + 9
    else:
        pages_to_scan = max(1, (limit + 24) // 25)
        max_pages = start_page + pages_to_scan - 1

    logger.info(f"🌐 [get_forum_topics] Starting topic scan for {clean_base} (start_page={start_page}, sort_by={sort_by}, limit={limit}, date_filter={active_date_filter}, max_pages={max_pages})")

    while len(topics) < limit and current_page <= max_pages:
        q_part = f"?{query_str}" if query_str else ""
        if current_page == 1:
            target_url = f"{clean_base}{q_part}"
        else:
            target_url = f"{clean_base}page/{current_page}/{q_part}"

        try:
            logger.info(f"📄 Fetching forum page {current_page}: {target_url}")
            soup = _fetch_soup(target_url)
        except Exception as e:
            logger.warning(f"Could not fetch page {current_page} ({target_url}): {e}")
            break

        page_topics, hit_older, new_on_page = _extract_topics_from_soup(
            soup=soup,
            clean_base=clean_base,
            seen=seen,
            limit=limit - len(topics),
            active_date_filter=active_date_filter,
        )
        topics.extend(page_topics)

        # If query_str was present and returned 0 topics without hitting older date cutoff:
        # Retry with clean URL on this page to recover from rejected or unsupported sort parameters
        if new_on_page == 0 and query_str and not hit_older:
            clean_page_url = f"{clean_base}page/{current_page}/" if current_page > 1 else clean_base
            if clean_page_url != target_url:
                try:
                    logger.info(f"🔄 Retrying forum page {current_page} without query parameters: {clean_page_url}")
                    clean_soup = _fetch_soup(clean_page_url)
                    retry_topics, hit_older_retry, new_retry = _extract_topics_from_soup(
                        soup=clean_soup,
                        clean_base=clean_base,
                        seen=seen,
                        limit=limit - len(topics),
                        active_date_filter=active_date_filter,
                    )
                    topics.extend(retry_topics)
                    new_on_page += new_retry
                    if hit_older_retry:
                        hit_older = True
                except Exception as e:
                    logger.debug(f"Could not fetch clean page {clean_page_url}: {e}")

        # If date cutoff reached, or no topics found on this page: stop pagination
        if hit_older or new_on_page == 0:
            break

        if len(topics) >= limit:
            break

        current_page += 1

    # Subforum traversal: ONLY for parent categories when not active_date_filter and no direct topics were found
    if not topics and not active_date_filter:
        subforum_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if re.search(r"/forum/\d+|/forums/forum/\d+", href, re.I):
                sf_url = urljoin(clean_base, href)
                clean_sf = sf_url.split("?")[0].split("#")[0].rstrip("/") + "/"
                if clean_sf not in subforum_links and clean_sf != clean_base:
                    subforum_links.append(clean_sf)

        for sf_url in subforum_links[:3]:
            try:
                sf_soup = _fetch_soup(sf_url)
                sf_rows = sf_soup.find_all(["li", "div", "article", "tr"], class_=re.compile("ipsDataItem|cForumRow|cTopic", re.I))
                for row in sf_rows:
                    tc = row.find(class_=re.compile(r"ipsDataItem_title|ipsType_break|cForumRow_title", re.I)) or row.find("h4")
                    le = tc.find("a", href=re.compile(r"/topic/|/topics/topic/|index\.php\?/topic/", re.I)) if tc else None
                    if not le:
                        le = row.find("a", href=re.compile(r"/topic/|/topics/topic/|index\.php\?/topic/", re.I))
                    if le:
                        fu = _clean_topic_url(urljoin(sf_url, le["href"].strip()))
                        if fu not in seen:
                            seen.add(fu)
                            title = le.get_text(strip=True) or "Untitled Post"
                            topics.append({"title": title, "url": fu, "date": None, "views": None})
                            if len(topics) >= limit:
                                break
                if len(topics) >= limit:
                    break
            except Exception as e:
                logger.debug(f"Could not scrape subforum {sf_url}: {e}")

    logger.info(f"✅ [get_forum_topics] Finished scan. Found {len(topics)} topic(s) from {clean_base}")
    return topics


CURATED_FORUM_IDS = [20, 2, 31, 4, 5, 6, 21, 58, 34, 64, 35, 40, 9, 23, 24, 10, 28, 54]

CURATED_DROP_FORUMS = {
    2: {"title": "General Discussion", "url": "https://dropmms.com/forum/2-general/"},
    4: {"title": "Desi Videos & MMS", "url": "https://dropmms.com/forum/4-desi-new-semi-nude-masked-no-face-videos-pics/"},
    5: {"title": "Forum 5", "url": "https://dropmms.com/forum/5-category/"},
    6: {"title": "Forum 6", "url": "https://dropmms.com/forum/6-category/"},
    9: {"title": "Forum 9", "url": "https://dropmms.com/forum/9-category/"},
    10: {"title": "Forum 10", "url": "https://dropmms.com/forum/10-category/"},
    20: {"title": "Forum 20", "url": "https://dropmms.com/forum/20-category/"},
    21: {"title": "Forum 21", "url": "https://dropmms.com/forum/21-category/"},
    23: {"title": "Forum 23", "url": "https://dropmms.com/forum/23-category/"},
    24: {"title": "Forum 24", "url": "https://dropmms.com/forum/24-category/"},
    28: {"title": "Forum 28", "url": "https://dropmms.com/forum/28-category/"},
    31: {"title": "Forum 31", "url": "https://dropmms.com/forum/31-category/"},
    34: {"title": "Forum 34", "url": "https://dropmms.com/forum/34-category/"},
    35: {"title": "Forum 35", "url": "https://dropmms.com/forum/35-category/"},
    40: {"title": "Forum 40", "url": "https://dropmms.com/forum/40-category/"},
    54: {"title": "Forum 54", "url": "https://dropmms.com/forum/54-category/"},
    58: {"title": "Forum 58", "url": "https://dropmms.com/forum/58-category/"},
    64: {"title": "Forum 64", "url": "https://dropmms.com/forum/64-category/"},
}

DEFAULT_DROP_FORUMS = [CURATED_DROP_FORUMS[4], CURATED_DROP_FORUMS[2]]


def get_dropmms_forums() -> list[dict]:
    """
    Fetch active forum categories from DropMMS index, filtered strictly to CURATED_FORUM_IDS.
    Returns list of dicts: [{'title': '...', 'url': '...', 'id': 4}, ...]
    """
    id_map = {}
    try:
        soup = _fetch_soup(f"{BASE_URL}/")
        if soup:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                full_url = urljoin(BASE_URL, href).split("?")[0].rstrip("/")
                if "/forum/" in full_url and not is_topic_url(full_url):
                    parts = [p for p in full_url.split("/") if p]
                    if len(parts) >= 4 and parts[2] == "forum":
                        slug = parts[3]
                        prefix = slug.split("-")[0]
                        if prefix.isdigit() and len(parts) == 4:
                            f_id = int(prefix)
                            if f_id in CURATED_FORUM_IDS:
                                title = a.get_text(strip=True)
                                if not title:
                                    parent_h = a.find_parent(["h4", "h3", "h2", "span"])
                                    if parent_h:
                                        title = parent_h.get_text(strip=True)
                                if title:
                                    clean_title = re.sub(r"\s*\(\d+\)\s*$", "", title).strip()
                                    if clean_title.lower() not in ["forums", "categories", "home"]:
                                        if f_id not in id_map:
                                            id_map[f_id] = {"title": clean_title, "url": f"{full_url}/", "id": f_id}
    except Exception as e:
        logger.warning(f"Could not fetch dynamic DropMMS forums: {e}")

    result = []
    for f_id in CURATED_FORUM_IDS:
        if f_id in id_map:
            result.append(id_map[f_id])
        else:
            default_entry = CURATED_DROP_FORUMS.get(f_id)
            if default_entry:
                result.append({
                    "title": default_entry["title"],
                    "url": default_entry["url"],
                    "id": f_id,
                })
            else:
                result.append({
                    "title": f"Forum {f_id}",
                    "url": f"{BASE_URL}/forum/{f_id}-category/",
                    "id": f_id,
                })

    return result


# --- MMSTown Forum Integration ---
MMSTOWN_BASE_URL = "https://mmstown.com"
CURATED_MMSTOWN_FORUM_IDS = [7, 8, 11, 12, 13, 14, 15, 16]

CURATED_MMSTOWN_FORUMS = {
    7: {"title": "Desi New Videos HD / SD", "url": "https://mmstown.com/forum/7-desi-new-videos-hd-sd/"},
    8: {"title": "Desi Exclusive Videos", "url": "https://mmstown.com/forum/8-desi-exclusive-videos/"},
    11: {"title": "Indian Semi Nude & Masked", "url": "https://mmstown.com/forum/11-indian-semi-nude-masked/"},
    12: {"title": "Desi Hardcore Videos", "url": "https://mmstown.com/forum/12-desi-hardcore-videos/"},
    13: {"title": "Indian Webcam & Live", "url": "https://mmstown.com/forum/13-indian-webcam-live/"},
    14: {"title": "Desi Audio & Calls", "url": "https://mmstown.com/forum/14-desi-audio-calls/"},
    15: {"title": "Desi Photos & Albums", "url": "https://mmstown.com/forum/15-desi-photos-albums/"},
    16: {"title": "International Videos", "url": "https://mmstown.com/forum/16-international-videos/"},
}


def is_mmstown_url(url: str) -> bool:
    """Check if URL belongs to mmstown.com."""
    if not url or not isinstance(url, str):
        return False
    return "mmstown.com" in url.lower()


def is_mmstown_topic_url(url: str) -> bool:
    """Check if URL represents an individual MMSTown topic."""
    return is_mmstown_url(url) and is_topic_url(url)


def is_mmstown_forum_url(url: str) -> bool:
    """Check if URL represents an MMSTown forum category."""
    return is_mmstown_url(url) and is_forum_url(url)


def get_mmstown_forums() -> list[dict]:
    """
    Fetch active forum categories from MMSTown, filtered strictly to CURATED_MMSTOWN_FORUM_IDS.
    Returns list of dicts: [{'title': '...', 'url': '...', 'id': 7}, ...]
    """
    id_map = {}
    try:
        soup = _fetch_soup(f"{MMSTOWN_BASE_URL}/")
        if soup:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                full_url = urljoin(MMSTOWN_BASE_URL, href).split("?")[0].rstrip("/")
                if "/forum/" in full_url and not is_topic_url(full_url):
                    parts = [p for p in full_url.split("/") if p]
                    if len(parts) >= 4 and parts[2] == "forum":
                        slug = parts[3]
                        prefix = slug.split("-")[0]
                        if prefix.isdigit() and len(parts) == 4:
                            f_id = int(prefix)
                            if f_id in CURATED_MMSTOWN_FORUM_IDS:
                                title = a.get_text(strip=True)
                                if not title:
                                    parent_h = a.find_parent(["h4", "h3", "h2", "span"])
                                    if parent_h:
                                        title = parent_h.get_text(strip=True)
                                if title:
                                    clean_title = re.sub(r"\s*\(\d+\)\s*$", "", title).strip()
                                    if clean_title.lower() not in ["forums", "categories", "home"]:
                                        if f_id not in id_map:
                                            id_map[f_id] = {"title": clean_title, "url": f"{full_url}/", "id": f_id}
    except Exception as e:
        logger.warning(f"Could not fetch dynamic MMSTown forums: {e}")

    result = []
    for f_id in CURATED_MMSTOWN_FORUM_IDS:
        if f_id in id_map:
            result.append(id_map[f_id])
        else:
            default_entry = CURATED_MMSTOWN_FORUMS.get(f_id)
            if default_entry:
                result.append({
                    "title": default_entry["title"],
                    "url": default_entry["url"],
                    "id": f_id,
                })
            else:
                result.append({
                    "title": f"Forum {f_id}",
                    "url": f"{MMSTOWN_BASE_URL}/forum/{f_id}-category/",
                    "id": f_id,
                })
    return result


def get_dropmms_category_stats(category_url: str) -> dict:
    """
    Fetch DropMMS forum category metadata: clean title, total pages, and estimated total topics.
    Returns:
      {
        "title": "Desi Videos & MMS",
        "total_pages": 45,
        "total_topics_str": "1125 (45 Pages)",
        "url": clean_base,
      }
    """
    clean_base = category_url.split("?")[0].split("#")[0].rstrip("/")
    clean_base = re.sub(r"/page/\d+/?$", "", clean_base)
    if not clean_base.endswith("/"):
        clean_base += "/"

    parts = [p for p in clean_base.split("/") if p]
    raw_slug = parts[-1] if parts else "Forum"
    fallback_title = re.sub(r"^\d+-", "", raw_slug).replace("-", " ").title() or "Forum Category"

    soup = _fetch_soup(clean_base)
    if not soup:
        return {
            "title": fallback_title,
            "total_pages": 1,
            "total_topics_str": "Available",
            "url": clean_base,
        }

    h1 = soup.find("h1", class_=re.compile(r"\bipsType_pageTitle\b", re.I)) or soup.find("h1")
    title = h1.get_text(strip=True) if h1 else fallback_title
    title = re.sub(r"\s*\(\d+\)\s*$", "", title).strip() or fallback_title

    pages = []
    for ul in soup.find_all("ul", class_=re.compile(r"\bipsPagination\b", re.I)):
        dp = ul.get("data-pages")
        if dp and dp.isdigit():
            pages.append(int(dp))

    for a in soup.find_all("a", href=True):
        href = a["href"]
        m_page = re.search(r"/page/(\d+)", href, re.I) or re.search(r"[?&]page=(\d+)", href, re.I)
        if m_page:
            pages.append(int(m_page.group(1)))

    max_page = max(pages) if pages else 1
    items = soup.find_all("li", class_=re.compile(r"\bipsDataItem\b", re.I))
    count_on_p1 = len(items) if items else 25

    if max_page == 1:
        total_str = f"{count_on_p1} (1 Page)" if count_on_p1 > 0 else "Available"
    else:
        total_str = f"{max_page * 25} ({max_page} Pages)"

    return {
        "title": title,
        "total_pages": max_page,
        "total_topics_str": total_str,
        "url": clean_base,
    }


get_ips_category_stats = get_dropmms_category_stats


def search_forum(query: str, limit: int = 5, base_url: str = BASE_URL) -> list[dict]:
    """
    Search an IPS forum (DropMMS or MMSTown) by keyword and return top matching topics.
    """
    b_url = base_url.rstrip("/")
    search_url = f"{b_url}/search/?q={quote_plus(query.strip())}&type=forums_topic"
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


def resolve_cloudfam_url(url: str, timeout: int = 15) -> str | None:
    """
    Resolve a cloudfam.io download page to its direct pre-signed S3 download URL.
    Follows the multi-step redirect chain:
    preload.php -> redirection0.php -> redirection1.php -> premium_upsell.php -> step=2 -> download_handler.php
    Returns the direct download link (e.g. AWS/R2 S3 signed URL) or None if resolution fails.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        session.headers["Referer"] = "https://dropmms.com/"

        # Step 1: Initial URL -> preload.php
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")

        # Step 2: redirection0.php
        next_a = soup.find("a", href=lambda h: h and "redirection" in h)
        if not next_a:
            return None
        red0_url = urljoin(str(resp.url), next_a["href"])
        resp2 = session.get(red0_url, timeout=timeout, allow_redirects=True)
        if resp2.status_code != 200:
            return None
        soup2 = BeautifulSoup(resp2.text, "html.parser")

        # Step 3: redirection1.php via #cf-btn-free
        btn_free = soup2.find(id="cf-btn-free")
        if not btn_free or not btn_free.get("href"):
            return None
        red1_url = urljoin(str(resp2.url), btn_free["href"])
        resp3 = session.get(red1_url, timeout=timeout, allow_redirects=True)
        if resp3.status_code != 200:
            return None
        soup3 = BeautifulSoup(resp3.text, "html.parser")

        # Step 4: premium_upsell.php via #free-btn
        btn_upsell = soup3.find(id="free-btn")
        if not btn_upsell or not btn_upsell.get("href"):
            return None
        upsell_url = urljoin(str(resp3.url), btn_upsell["href"])
        resp4 = session.get(upsell_url, timeout=timeout, allow_redirects=True)
        if resp4.status_code != 200:
            return None
        soup4 = BeautifulSoup(resp4.text, "html.parser")

        # Step 5: step=2 via #free-continue
        btn_continue = soup4.find(id="free-continue")
        if not btn_continue or not btn_continue.get("href"):
            return None
        step2_url = urljoin(str(resp4.url), btn_continue["href"])
        resp5 = session.get(step2_url, timeout=timeout, allow_redirects=True)
        if resp5.status_code != 200:
            return None
        soup5 = BeautifulSoup(resp5.text, "html.parser")

        # Step 6: download_handler.php via #cf-dl-btn
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

    # 5. WordPress dimension suffix removal (e.g. image-180x200.jpg -> image.jpg)
    cleaned = re.sub(r'-\d+x\d+\.(jpg|jpeg|png|webp)', r'.\1', cleaned, flags=re.I)

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
    Download image into memory using intelligent multi-tier fetcher.
    Verifies image magic bytes AND image dimensions with Pillow to ensure
    tiny avatars / icons are filtered out and Telegram never throws Image_process_failed.
    If image_url is an HTML viewer page, automatically resolves and downloads the real image.
    Optimizes aspect ratio to prevent Telegram squarish cropping.
    """
    if not image_url or not isinstance(image_url, str):
        return None
    try:
        resp = _fetch_url(image_url, timeout=12)
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
                direct_resp = _fetch_url(direct_img_url, timeout=12)
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

    # Date extraction (IPS Community <time> tag)
    time_elem = soup.find("time")
    post_date_raw = (time_elem.get("datetime") or time_elem.get("title")) if time_elem else None
    post_date_ist = format_date_ist(post_date_raw) if post_date_raw else None

    return {
        "title": title,
        "clean_title": clean_title,
        "tags": tags,
        "thumbnail": thumbnail,
        "thumbnail_candidates": thumbnail_candidates,
        "streaming_links": streaming_links,
        "post_url": post_url,
        "date": post_date_raw,
        "date_ist": post_date_ist,
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
        or u.rstrip("/") in [
            "https://dropmms.com",
            "http://dropmms.com",
            "https://mmstown.com",
            "http://mmstown.com",
        ]
    )


# --- Slicing & Range Argument Helpers ---

def parse_slicing_args(args: list[str]) -> tuple[str | None, int | None, int | None, bool]:
    """
    Parse target URL and user slice parameters from command arguments.
    Supported patterns:
      - Count: '4' or 'count 4' -> (start=1, end=4, is_last=False)
      - Range: '1-5', '1 - 5', '1 to 5' -> (start=1, end=5, is_last=False)
      - Last N: 'last 5' or 'last5' -> (start=None, end=5, is_last=True)
    Returns: (target_url, start_idx, end_idx, is_last_n)
      indices are 1-based. If not specified, start_idx=None, end_idx=None.
    """
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

    # Check for 'last N' or 'lastN'
    m_last = re.search(r"last\s*(\d+)", text)
    if m_last:
        count = int(m_last.group(1))
        return target_url, None, count, True

    # Check for range 'X-Y' or 'X to Y' or 'X - Y'
    m_range = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)", text)
    if m_range:
        start_i = int(m_range.group(1))
        end_i = int(m_range.group(2))
        return target_url, start_i, end_i, False

    # Check for single count 'N' or 'count N'
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


# --- LiveCamRips Multi-Site Integration Helpers ---

def is_livecam_url(url: str) -> bool:
    """Check if URL belongs to livecamrips.to."""
    if not url or not isinstance(url, str):
        return False
    u = url.lower().strip()
    return "livecamrips.to" in u


def is_livecam_video_url(url: str) -> bool:
    """Check if URL represents an individual livecamrips video."""
    if not is_livecam_url(url):
        return False
    u = url.lower().strip()
    return "/video/" in u


def is_livecam_model_url(url: str) -> bool:
    """Check if URL represents a livecamrips model page."""
    if not is_livecam_url(url):
        return False
    u = url.lower().strip()
    return "/model/" in u or "/models/" in u


def clean_livecam_title(raw_title: str) -> str:
    """
    Clean LiveCamRips title by stripping '- Stripchat Recording', 'Stripchat', 'Recording', dates, etc.
    Leaving the pure model name.
    """
    if not raw_title:
        return "Model"
    cleaned = raw_title
    cleaned = re.sub(r"^livecamrips\.to\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"-\s*stripchat\s*recording", "", cleaned, flags=re.I)
    cleaned = re.sub(r"stripchat\s*recording", "", cleaned, flags=re.I)
    cleaned = re.sub(r"-\s*stripchat", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bstripchat\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\brecording\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\(\s*\d{1,2}\s+[a-zA-Z]+\s+\d{4}[^\)]*\)", "", cleaned)
    cleaned = re.sub(r"-\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", "", cleaned)
    cleaned = re.sub(r"^[\s\-_–—]+|[\s\-_–—]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "Model"


def format_livecam_date(date_str: str | None) -> str:
    """Format LiveCamRips date string (YYYY-MM-DD HH:MM) into clean readable date."""
    if not date_str:
        return "Recent"
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M")
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return date_str.strip()


def is_livecam_today(date_str: str | None) -> bool:
    """Check if LiveCamRips date falls within today (UTC or IST)."""
    if not date_str:
        return False
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
        return dt.date() == now_utc.date() or dt.date() == now_ist.date()
    except Exception:
        return False


def is_livecam_older_than_today(date_str: str | None) -> bool:
    """Check if LiveCamRips date is older than today across timezones."""
    if not date_str:
        return False
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
        min_today_date = min(now_utc.date(), now_ist.date())
        return dt.date() < min_today_date
    except Exception:
        return False


def get_livecam_model_stats(model_url: str) -> dict:
    """
    Fetch model page metadata: model name, total pages, and estimated total videos.
    Returns:
      {
        "name": "GoddessAnna",
        "total_pages": 19,
        "total_videos_str": "304 (19 Pages)",
        "url": clean_base,
      }
    """
    clean_base = model_url.split("?")[0].split("#")[0].rstrip("/")
    parts = [p for p in clean_base.split("/") if p]
    if parts and parts[-1].isdigit() and len(parts) >= 2 and not parts[-2].isdigit() and parts[-2] != "model":
        clean_base = "/".join(clean_base.split("/")[:-1])
        parts = [p for p in clean_base.split("/") if p]

    soup = _fetch_soup(f"{clean_base}?sort=newest")
    if not soup:
        name = parts[-1] if parts else "Model"
        return {"name": clean_livecam_title(name), "total_pages": 1, "total_videos_str": "Available", "url": clean_base}

    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else (parts[-1] if parts else "Model")
    name = clean_livecam_title(name)

    pages = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/model/" in href:
            p_parts = href.split("?")[0].rstrip("/").split("/")
            if p_parts and p_parts[-1].isdigit():
                pages.append(int(p_parts[-1]))

    max_page = max(pages) if pages else 1
    figs_on_p1 = len(soup.find_all("figure"))

    if max_page == 1:
        total_str = f"{figs_on_p1} (1 Page)" if figs_on_p1 > 0 else "Available"
    else:
        total_str = f"{max_page * 16} ({max_page} Pages)"

    return {
        "name": name,
        "total_pages": max_page,
        "total_videos_str": total_str,
        "url": clean_base,
    }


def parse_model_range_input(text: str) -> tuple[int | None, int | None, int | None]:
    """
    Parse user range input for model scraping.
    Returns: (start_idx, end_idx, page_num)
      - "5" -> (1, 5, None)
      - "1-5" -> (1, 5, None)
      - "5-10" -> (5, 10, None)
      - "page 2" or "p2" -> (None, None, 2)
    """
    t = text.strip().lower()

    # Page format: page 2, p2, page2, p 2
    m_page = re.match(r"^(?:page\s*|p\s*)(\d+)$", t)
    if m_page:
        p = int(m_page.group(1))
        return (None, None, p) if p > 0 else (None, None, None)

    # Range format: 1-5, 5-10, 5 to 10, 5:10, 5..10
    m_range = re.match(r"^(\d+)\s*(?:-|to|:|\.\.)\s*(\d+)$", t)
    if m_range:
        s, e = int(m_range.group(1)), int(m_range.group(2))
        if s > e:
            s, e = e, s
        if e < 1:
            return (None, None, None)
        s = max(1, s)
        return (s, e, None)

    # Single number: 5, 10
    if t.isdigit():
        n = int(t)
        return (1, n, None) if n > 0 else (None, None, None)

    return (None, None, None)


def get_livecam_model_videos(
    model_url: str,
    only_today: bool = False,
    limit: int | None = None,
    sort_by: str = "newest",
    start_page: int | None = None,
) -> list[dict]:
    """
    Extract video items from a LiveCamRips model page in sorted order.
    sort_by options: 'newest', 'most_viewed', 'most_liked', 'oldest'
    If only_today=True, strictly filters for videos posted today and breaks on older videos.
    """
    clean_base = model_url.split("?")[0].split("#")[0].rstrip("/")
    detected_start = 1
    parts = [p for p in clean_base.split("/") if p]
    if parts and parts[-1].isdigit() and len(parts) >= 2 and not parts[-2].isdigit() and parts[-2] != "model":
        detected_start = max(1, int(parts[-1]))
        clean_base = "/".join(clean_base.split("/")[:-1])

    page_to_start = start_page if start_page is not None else detected_start
    clean_sort = (sort_by or "newest").lower().strip()
    if clean_sort not in ["newest", "most_viewed", "most_liked", "oldest"]:
        clean_sort = "newest"

    req_limit = limit or (50 if not only_today else 200)
    pages_to_scan = 10 if only_today else max(5, (req_limit + 15) // 16)
    max_pages = page_to_start + pages_to_scan - 1

    videos = []
    seen_ids = set()
    current_page = page_to_start

    while len(videos) < req_limit and current_page <= max_pages:
        if current_page == 1:
            target_url = f"{clean_base}?sort={clean_sort}"
        else:
            target_url = f"{clean_base}/{current_page}?sort={clean_sort}"

        try:
            logger.info(f"📄 Fetching LiveCam model page {current_page}: {target_url}")
            soup = _fetch_soup(target_url)
        except Exception as e:
            logger.warning(f"Could not fetch LiveCam model page {current_page} ({target_url}): {e}")
            break

        figures = soup.find_all("figure", class_=re.compile(r"\btm-video-item\b", re.I))
        if not figures:
            figures = soup.find_all("figure", attrs={"video-id": True})
        if not figures:
            break

        hit_older = False
        new_on_page = 0

        for fig in figures:
            video_id = fig.get("video-id")
            if video_id and video_id in seen_ids:
                continue

            a_tag = fig.find("a", href=True)
            video_url = urljoin(model_url, a_tag["href"].strip()) if a_tag else f"https://livecamrips.to/video/{video_id}"

            img_tag = fig.find("img")
            thumb = img_tag.get("src") if img_tag else None

            dur_tag = fig.find("span", class_=re.compile(r"\btm-bg-dark\b", re.I))
            duration = dur_tag.get_text(strip=True) if dur_tag else None

            parent = fig.parent
            date_str = None
            model_name = None
            platform = None

            if parent:
                date_span = parent.find("span", string=re.compile(r"\d{4}-\d{2}-\d{2}", re.I))
                if date_span:
                    date_str = date_span.get_text(strip=True)

                model_tag = parent.find("span", class_=re.compile(r"\btm-text-gray-light\b", re.I))
                if model_tag:
                    model_name = model_tag.get_text(strip=True)

                plat_a = parent.find("a", href=re.compile(r"/website/", re.I))
                if plat_a:
                    platform = plat_a.get_text(strip=True)

            if not model_name:
                parts_path = [p for p in urlparse(clean_base).path.split("/") if p]
                if len(parts_path) >= 3 and parts_path[0] == "model":
                    model_name = parts_path[2]
                else:
                    model_name = "Model"

            model_name = clean_livecam_title(model_name)
            date_display = format_livecam_date(date_str)

            # Date-wise cutoff when filtering for today's uploads
            if only_today and date_str:
                if is_livecam_older_than_today(date_str):
                    logger.info(f"Hit LiveCamRips date cutoff at older video: {date_str}. Stopping scan.")
                    hit_older = True
                    break
                if not is_livecam_today(date_str):
                    continue

            if video_id:
                seen_ids.add(video_id)
            new_on_page += 1

            videos.append({
                "video_id": video_id,
                "video_url": video_url,
                "url": video_url,
                "thumb": thumb,
                "thumbnail": thumb,
                "duration": duration,
                "raw_date": date_str,
                "date": date_display,
                "model_name": model_name,
                "title": model_name,
                "platform": platform or "Stripchat",
            })

            if len(videos) >= req_limit:
                break

        if hit_older or new_on_page == 0:
            break

        current_page += 1

    return videos


def get_livecam_video_details(video_url: str) -> dict:
    """Fetch video details from LiveCamRips video page, including iframe streaming embeds."""
    soup = _fetch_soup(video_url)

    h1 = soup.find("h1")
    raw_h1_text = h1.get_text(" ", strip=True) if h1 else ""

    model_name = None
    if h1:
        model_a = h1.find("a", href=re.compile(r"/model/", re.I))
        if model_a:
            model_name = model_a.get_text(strip=True)

    if not model_name:
        model_name = clean_livecam_title(raw_h1_text)
    model_name = clean_livecam_title(model_name)

    # Date extraction (YYYY-MM-DD HH:MM)
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\b", raw_h1_text or soup.get_text())
    raw_date = date_match.group(1) if date_match else None
    date_display = format_livecam_date(raw_date)

    # Platform detection
    low_text = (raw_h1_text + " " + soup.get_text()).lower()
    if "chaturbate" in low_text:
        platform = "Chaturbate"
    elif "camsoda" in low_text:
        platform = "CamSoda"
    elif "bongacams" in low_text:
        platform = "BongaCams"
    elif "stripchat" in low_text:
        platform = "Stripchat"
    else:
        platform = "Stripchat"

    # Streaming links / iframe embeds
    streaming_links = []
    seen_links = set()
    for tag in soup.find_all(["iframe", "embed", "source"], src=True):
        src = tag["src"].strip()
        full_src = urljoin(video_url, src)
        if full_src not in seen_links:
            seen_links.add(full_src)
            streaming_links.append(full_src)

    # Additional streaming links from page
    more_links = _extract_streaming_links_from_html(soup, video_url)
    for ml in more_links:
        if ml not in seen_links:
            seen_links.add(ml)
            streaming_links.append(ml)

    # High resolution thumbnail
    v_match = re.search(r"/video/(\d+)", video_url)
    video_id = v_match.group(1) if v_match else None
    thumbnail = None
    if video_id:
        thumbnail = f"https://images.livecamrips.to/{video_id[:4]}/{video_id}.png"

    if not thumbnail:
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            thumbnail = og_img["content"].strip()

    return {
        "model_name": model_name,
        "title": model_name,
        "clean_title": model_name,
        "date": date_display,
        "raw_date": raw_date,
        "duration": None,
        "platform": platform,
        "tags": [model_name, platform],
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_links": streaming_links,
        "video_url": video_url,
        "is_livecam": True,
    }


def format_livecam_card(details: dict, link_mode: str = "streaming") -> str:
    """
    Format LiveCamRips video card with Telegram blockquote and copyable links.
    link_mode options:
      - 'streaming' (default): Show only the streaming embed link(s)
      - 'page': Show only the LiveCamRips video page link
      - 'both': Show both Video Page and Streaming Link(s)
    """
    model_name = html.escape(clean_livecam_title(details.get("model_name") or details.get("title") or "Model"))
    date_str = html.escape(details.get("date") or "Recent")
    duration = html.escape(details.get("duration") or "")
    platform = html.escape(details.get("platform") or "Stripchat")
    video_url = html.escape(details.get("video_url") or "")
    streaming_links = details.get("streaming_links") or []

    tag_model = re.sub(r"[^\w]", "", model_name)
    tag_platform = re.sub(r"[^\w]", "", platform)
    tags_line = f"#{tag_model}"
    if tag_platform and tag_platform.lower() != tag_model.lower():
        tags_line += f" #{tag_platform}"

    raw_text = f"{details.get('title', '')} {details.get('duration', '')}"
    for q in ["1080p", "720p", "4k", "hd"]:
        if q in raw_text.lower() and f"#{q}" not in tags_line.lower():
            tags_line += f" #{q.upper() if q in ['hd', '4k'] else q}"

    lines = [
        "<blockquote>"
        f"📹 <b>{model_name}</b>\n"
        f"📅 <b>Date:</b> {date_str}"
    ]
    if duration:
        lines.append(f"⏱️ <b>Duration:</b> {duration}")
    lines.append(f"🏷️ {tags_line}</blockquote>")

    mode = (link_mode or "streaming").lower().strip()

    # 1. Video Page Link (if mode is 'both' or 'page')
    if mode in ["both", "page"] and video_url:
        lines.append(f"\n🌐 <b>Video Page:</b>\n🔗 <code>{video_url}</code>")

    # 2. Streaming Link (if mode is 'both' or 'streaming')
    if mode in ["both", "streaming"]:
        if streaming_links:
            if len(streaming_links) == 1:
                lines.append(f"\n🍿 <b>Streaming Link:</b>\n🔗 <code>{html.escape(streaming_links[0])}</code>")
            else:
                lines.append("\n🍿 <b>Streaming Links:</b>")
                for i, l in enumerate(streaming_links, 1):
                    badge = get_host_display_name(l)
                    lines.append(f"{i}. {badge}: <code>{html.escape(l)}</code>")
        elif not (mode == "page" and video_url):
            # Fallback to video_url if no iframe streaming link was resolved
            lines.append(f"\n🍿 <b>Streaming Link:</b>\n🔗 <code>{video_url}</code>")

    return "\n".join(lines)


def search_livecam_models(query: str, limit: int = 10) -> list[dict]:
    """
    Search LiveCamRips for models matching the given query.
    Returns list of dicts: [{'name': 'GoddessAnna', 'url': 'https://livecamrips.to/model/36773/GoddessAnna', 'thumb': '...'}, ...]
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    queries_to_try = []
    if " " in clean_q:
        queries_to_try.append(clean_q.replace(" ", ""))
    queries_to_try.append(clean_q)

    results = []
    seen_urls = set()

    for q in queries_to_try:
        search_url = f"https://livecamrips.to/search/{quote(q)}"
        soup = _fetch_soup(search_url)
        if not soup:
            continue

        links = soup.find_all("a", href=lambda h: h and "/model/" in h)
        for a in links:
            href = a.get("href", "").strip()
            if not href:
                continue
            full_url = urljoin("https://livecamrips.to", href)
            clean_url = full_url.split("?")[0].split("#")[0].rstrip("/")

            parts = clean_url.split("/")
            if len(parts) < 5 or parts[-3] != "model":
                continue

            if clean_url in seen_urls:
                continue

            name = a.get_text(strip=True)
            if not name:
                name = parts[-1]

            name = clean_livecam_title(name)
            if not name or name.lower() == "models":
                continue

            img = a.find("img")
            if not img and a.parent:
                img = a.parent.find("img")
            thumb = img.get("src") if img else None

            seen_urls.add(clean_url)
            results.append({
                "name": name,
                "url": clean_url,
                "thumb": thumb,
            })
            if len(results) >= limit:
                break

        if results:
            break

    return results


# --- MMSVibex Multi-Media Integration ---

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
    return bool(re.search(r"[?&]filter=", u, re.I) or "/page/" in u or "/category/" in u or "/tag/" in u or "/actors/" in u)


def is_mmsvibex_video_url(url: str) -> bool:
    """Check if URL represents an individual MMSVibex video page."""
    return is_mmsvibex_url(url) and not is_mmsvibex_photo_url(url) and not is_mmsvibex_listing_url(url)


def get_mmsvibex_video_details(video_url: str) -> dict:
    """Fetch video details from MMSVibex video page including direct CDN MP4 and attached photo album."""
    soup = _fetch_soup(video_url)

    h1 = soup.find("h1") or soup.find("span", class_="title")
    title = h1.get_text(strip=True) if h1 else "Untitled Video"
    clean_title, tags = extract_tags_and_quality(title)

    # Poster / thumbnail
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

    # Duration
    duration = None
    dur_elem = soup.find("span", class_=re.compile(r"duration", re.I))
    if dur_elem:
        duration = dur_elem.get_text(strip=True)

    # Direct CDN MP4 links
    streaming_links = []
    seen = set()

    for s_tag in soup.find_all("source"):
        src = s_tag.get("src", "").strip()
        if src and (".mp4" in src.lower() or "cdn.mmsvibex" in src.lower()):
            if src not in seen:
                seen.add(src)
                streaming_links.append(src)

    if not streaming_links:
        for v in soup.find_all("video", src=True):
            vsrc = v["src"].strip()
            if vsrc and vsrc not in seen:
                seen.add(vsrc)
                streaming_links.append(vsrc)

    if not streaming_links:
        for m in re.finditer(r'https?://[^\s"\'<>]+\.mp4(?:\?[^\s"\'<>]*)?', str(soup)):
            mp4_url = m.group(0)
            if mp4_url not in seen:
                seen.add(mp4_url)
                streaming_links.append(mp4_url)

    # Any other streaming links from html
    more_links = _extract_streaming_links_from_html(soup, video_url)
    for ml in more_links:
        if ml not in seen:
            seen.add(ml)
            streaming_links.append(ml)

    # Attached photo album link
    attached_album_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/photos/" in href and href != "https://mmsvibex.life/photos/":
            attached_album_url = urljoin(video_url, href)
            break

    # Date
    time_elem = soup.find("time")
    post_date_raw = (time_elem.get("datetime") or time_elem.get("title")) if time_elem else None
    post_date_ist = format_date_ist(post_date_raw) if post_date_raw else None

    return {
        "title": title,
        "clean_title": clean_title,
        "tags": tags,
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_links": streaming_links,
        "attached_album_url": attached_album_url,
        "duration": duration,
        "post_url": video_url,
        "date": post_date_raw,
        "date_ist": post_date_ist,
        "site": "mmsvibex",
    }


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

    # Cover image / thumbnail
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

    time_elem = soup.find("time")
    post_date_raw = (time_elem.get("datetime") or time_elem.get("title")) if time_elem else None
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

    if page == 1:
        target_url = f"{clean_base}/?{query}" if query else f"{clean_base}/"
    else:
        target_url = f"{clean_base}/page/{page}/?{query}" if query else f"{clean_base}/page/{page}/"

    soup = _fetch_soup(target_url)
    items = []
    seen = set()

    for block in soup.find_all("div", class_=re.compile(r"thumb-block|video-preview-item|item", re.I)):
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


# --- WordPress Locker Engine (Omaal63, DesiJugar, GulabiHub) ---

def is_wp_locker_url(url: str) -> bool:
    """Check if URL belongs to any supported WordPress locker/tube sites."""
    if not url or not isinstance(url, str):
        return False
    u = url.lower()
    return any(dom in u for dom in ["omaal63.net", "desijugar.me", "gulabihub.com"])


def is_wp_locker_listing_url(url: str) -> bool:
    """Check if URL is a WordPress category, tag, author, or home archive page."""
    if not is_wp_locker_url(url):
        return False
    u = url.lower().split("?")[0].rstrip("/")
    if u in [
        "https://omaal63.net", "https://desijugar.me", "https://gulabihub.com",
        "http://omaal63.net", "http://desijugar.me", "http://gulabihub.com"
    ]:
        return True
    return any(p in u for p in ["/category/", "/tag/", "/author/", "/page/"])


def is_wp_locker_post_url(url: str) -> bool:
    """Check if URL is an individual WordPress locker post."""
    return is_wp_locker_url(url) and not is_wp_locker_listing_url(url)


def get_wp_post_details(post_url: str) -> dict:
    """Fetch post details from WordPress locker/tube sites (Omaal63, DesiJugar, GulabiHub)."""
    soup = _fetch_soup(post_url)

    h1 = soup.find("h1", class_=re.compile(r"entry-title|post-title|title", re.I)) or soup.find("h1")
    title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "Untitled Post")
    clean_title, tags = extract_tags_and_quality(title)

    # Thumbnail extraction
    thumbnail = None
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        thumbnail = og["content"].strip()

    if not thumbnail or "svg+xml" in thumbnail:
        for img in soup.find_all("img"):
            candidate = (
                img.get("data-lazy-src")
                or img.get("data-src")
                or img.get("data-orig-file")
                or img.get("src")
            )
            if candidate and _is_valid_thumbnail_url(candidate) and not candidate.startswith("data:"):
                thumbnail = urljoin(post_url, candidate)
                break

    thumbnail = _clean_highres_image_url(thumbnail) if thumbnail else None

    # Streaming links: include iframes (for GulabiHub) + normal streaming links
    streaming_links = []
    seen = set()

    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"].strip()
        full_src = urljoin(post_url, src)
        if _is_streaming_link(full_src) and full_src not in seen:
            seen.add(full_src)
            streaming_links.append(full_src)

    more_links = _extract_streaming_links_from_html(soup, post_url)
    for ml in more_links:
        if ml not in seen:
            seen.add(ml)
            streaming_links.append(ml)

    # Date extraction: <time> tag or URL path (e.g. /2026/11/22/)
    time_elem = soup.find("time")
    post_date_raw = (time_elem.get("datetime") or time_elem.get("title")) if time_elem else None
    if not post_date_raw:
        m_date = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", post_url)
        if m_date:
            post_date_raw = f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}"

    post_date_ist = format_date_ist(post_date_raw) if post_date_raw else None

    return {
        "title": title,
        "clean_title": clean_title,
        "tags": tags,
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_links": streaming_links,
        "post_url": post_url,
        "date": post_date_raw,
        "date_ist": post_date_ist,
        "site": "wp_locker",
    }


def get_wp_listing_posts(listing_url: str, page: int = 1, limit: int = 25) -> list[dict]:
    """Fetch post items from WordPress locker listing or category page with pagination."""
    clean_base = listing_url.split("?")[0].split("#")[0].rstrip("/")
    if page == 1:
        target_url = f"{clean_base}/"
    else:
        target_url = f"{clean_base}/page/{page}/"

    soup = _fetch_soup(target_url)
    posts = []
    seen = set()

    articles = soup.find_all("article")
    if not articles:
        articles = soup.find_all("div", class_=re.compile(r"post|item-video|thumb-block", re.I))

    for art in articles:
        link = art.find("a", href=True)
        if not link:
            continue
        href = urljoin(target_url, link["href"].strip())
        if href in seen or not href.startswith("http"):
            continue

        title_elem = art.find(["h2", "h3", "h4", "span"], class_=re.compile(r"title|entry-title", re.I)) or link
        title = title_elem.get_text(strip=True) if title_elem else link.get("title", "")
        if not title:
            title = "Untitled Post"

        img = art.find("img")
        thumb = None
        if img:
            candidate = (
                img.get("data-lazy-src")
                or img.get("data-src")
                or img.get("data-orig-file")
                or img.get("src")
            )
            if candidate and not candidate.startswith("data:"):
                thumb = _clean_highres_image_url(urljoin(target_url, candidate))

        time_tag = art.find("time")
        d_raw = time_tag.get("datetime") if time_tag else None
        if not d_raw:
            m_date = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
            if m_date:
                d_raw = f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}"

        seen.add(href)
        posts.append({
            "title": title,
            "url": href,
            "thumbnail": thumb,
            "date": d_raw,
            "date_ist": format_date_ist(d_raw) if d_raw else None,
        })
        if len(posts) >= limit:
            break

    return posts


