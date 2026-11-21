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


# Provider Priority Order (Highest -> Lowest)
# User requested order: Streamtape -> Vidara -> Streamfiles -> iPlayGo/Lplaygo -> ABStream -> Uqload -> Streamcash -> Rest
PROVIDER_PRIORITY = [
    "streamtape",
    "vidara",
    "streamfiles",
    "iplaygo",
    "lplaygo",
    "abstream",
    "uqload",
    "streamcash",
    "doodstream",
    "streamwish",
    "filelions",
    "dropload",
    "mixdrop",
    "streamruby",
]


def get_host_display_name(url: str) -> str:
    """Get clean emoji-badge display name for a streaming provider."""
    try:
        domain = urlparse(url).netloc.lower()
        if "streamtape" in domain:
            return "🎬 Streamtape"
        elif "vidara" in domain:
            return "⚡ Vidara"
        elif "streamfiles" in domain:
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
        else:
            clean = domain.replace("www.", "").split(".")[0].capitalize()
            return f"🎬 {clean}"
    except Exception:
        return "🎬 Watch Video"


def get_host_key(url: str) -> str:
    """Extract standard key for a streaming provider (e.g. streamtape, vidara)."""
    try:
        domain = urlparse(url).netloc.lower()
        if "streamtape" in domain:
            return "streamtape"
        elif "vidara" in domain:
            return "vidara"
        elif "streamfiles" in domain:
            return "streamfiles"
        elif "iplaygo" in domain:
            return "iplaygo"
        elif "lplaygo" in domain:
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


def _is_posted_today(date_str: str | None, time_text: str | None, full_row_text: str | None = None) -> tuple[bool, bool]:
    """
    Check if a post timestamp, relative text, or row text indicates it was posted today.
    Handles Indian Standard Time (IST, UTC+05:30) and UTC/server time.
    Returns: (is_today: bool, is_definitely_older: bool)
    - is_today: Confirmed to be uploaded today (from 1:00 AM IST to now, or within ~24h).
    - is_definitely_older: Confirmed older (yesterday or earlier).
    """
    now_utc = datetime.now(timezone.utc)
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = now_utc.astimezone(IST)
    today_ist_date = now_ist.date()
    today_utc_date = now_utc.date()

    # 1. Authoritative ISO 8601 parsing from <time datetime="...">
    if date_str:
        s = str(date_str).strip()
        try:
            cleaned_iso = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_ist = dt.astimezone(IST)

            # If posted today in IST (from 00:00/01:00 AM IST to current time)
            if dt_ist.date() == today_ist_date:
                return True, False

            # If posted before today in IST, it's definitely older
            if dt_ist.date() < today_ist_date:
                return False, True
            elif dt_ist.date() > today_ist_date:
                return True, False
        except Exception:
            pass

    # 2. Text-based relative checks on time_text specifically (avoids false hits in post titles/usernames)
    tt = str(time_text or "").strip().lower()
    if tt:
        # Check for yesterday
        if re.search(r"\byesterday\b", tt):
            return False, True

        # Check for days / weeks / months / years ago
        if re.search(r"\b\d+\s*(?:d|day|days|w|wk|weeks|mo|month|months|y|yr|years)\b", tt):
            return False, True

        # Check for today / just now / moment
        if any(w in tt for w in ["today", "just now", "moment"]):
            return True, False

        # Relative minutes or seconds ago (e.g. "10 minutes ago", "25m", "45s")
        if re.search(r"\b\d+\s*(?:m|min|mins|minute|minutes|s|sec|secs)\b", tt):
            return True, False

        # Relative hours (e.g. "2 hours ago", "5h", "14 hr")
        m_hr = re.search(r"\b(\d+)\s*(?:h|hr|hrs|hour|hours)\b", tt)
        if m_hr:
            hrs = int(m_hr.group(1))
            if hrs <= 24:
                return True, False
            else:
                return False, True

        # Explicit calendar date in time_text (e.g. "Nov 20", "20 Nov", "November 20")
        today_days = {str(now_ist.day), f"{now_ist.day:02d}", str(now_utc.day), f"{now_utc.day:02d}"}
        today_months = {
            now_ist.strftime("%b").lower(), now_ist.strftime("%B").lower(),
            now_utc.strftime("%b").lower(), now_utc.strftime("%B").lower()
        }
        for m in today_months:
            if m in tt:
                for d in today_days:
                    if re.search(rf"\b{d}\b", tt):
                        return True, False
                # Mentions current month but a different day
                return False, True

        # Other months mentioned (e.g. "Oct 15", "September 3")
        all_months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
        if any(m in tt for m in all_months):
            return False, True

    # 3. Fallback to full_row_text only if time_text was completely absent
    if not tt and full_row_text:
        fr = str(full_row_text).strip().lower()
        if re.search(r"\byesterday\b", fr):
            return False, True
        if re.search(r"\b\d+\s*(?:d|day|days|w|wk|weeks|mo|month|months|y|yr|years)\s*ago\b", fr):
            return False, True
        if re.search(r"\btoday\b", fr):
            return True, False

    return False, False


def get_forum_topics(
    forum_url: str,
    sort_by: str = "start_date",
    limit: int = 25,
    only_today: bool = False,
) -> list[dict]:
    """
    Fetch structured topics from a forum category with date-sorting, metadata, and multi-page pagination.
    sort_by options:
      - 'start_date': Sort by topic creation/upload date (Newest uploads first)
      - 'views': Sort by popularity/views
      - 'updated': Sort by last activity
    only_today:
      - If True: Option 1 Live Date Cutoff. Filters for topics posted today (IST / UTC),
        multi-page paginating until yesterday's date cutoff is hit.
      - If False: Scrapes up to `limit` posts across forum pages (default: 25).
    """
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

    clean_base = forum_url.split("?")[0].split("#")[0]
    clean_base = re.sub(r"/page/\d+/?$", "/", clean_base)
    if not clean_base.endswith("/"):
        clean_base += "/"

    topics = []
    seen = set()
    current_page = start_page

    # Calculate max_pages
    if only_today:
        max_pages = start_page + 9
    else:
        pages_to_scan = max(1, (limit + 24) // 25)
        max_pages = start_page + pages_to_scan - 1

    logger.info(f"🌐 [get_forum_topics] Starting topic scan for {clean_base} (start_page={start_page}, sort_by={sort_by}, limit={limit}, only_today={only_today}, max_pages={max_pages})")

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

        # Search for topic row elements (IPS Community rows)
        row_elements = soup.find_all(["li", "div", "article", "tr"], class_=re.compile("ipsDataItem|cForumRow|cTopic", re.I))

        hit_older = False
        new_on_page = 0

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

            # Skip pinned / sticky / announcement topics when filtering for today's uploads
            row_classes = " ".join(row.get("class", [])).lower()
            is_pinned = (
                "pinned" in row_classes
                or bool(row.find(class_=re.compile(r"pinned|badge_pinned", re.I)))
                or bool(row.find("span", string=re.compile(r"pinned|featured", re.I)))
            )
            if is_pinned and only_today:
                continue

            # Extract publication timestamp from the topic creation container
            date_str = None
            time_text = None

            main_elem = row.find(class_=re.compile(r"ipsDataItem_main|cForumRow_main", re.I)) or row
            meta_elem = main_elem.find(class_=re.compile(r"ipsDataItem_meta|cForumRow_meta", re.I)) or main_elem

            time_tag = meta_elem.find("time")
            if time_tag:
                date_str = time_tag.get("datetime") or time_tag.get("title")
                time_text = time_tag.get_text(strip=True)

            row_text = meta_elem.get_text(" ", strip=True)

            # Apply Option 1 Live Date Cutoff when requested via /today
            if only_today:
                is_today, is_older = _is_posted_today(date_str, time_text, full_row_text=row_text)
                if is_older:
                    logger.info(f"Hit date cutoff at older topic: '{link_elem.get_text(strip=True)}' (date={date_str}, time={time_text}). Stopping scan.")
                    hit_older = True
                    break
                if not is_today:
                    continue

            seen.add(clean_url)
            new_on_page += 1
            title = link_elem.get_text(strip=True) or "Untitled Post"

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

        # Fallback for ANY page if row elements yielded 0 topics (only when only_today is False)
        if new_on_page == 0 and not only_today:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if "/topic/" in href or "index.php?/topic/" in href:
                    full_url = urljoin(clean_base, href)
                    clean_url = _clean_topic_url(full_url)
                    if clean_url not in seen:
                        seen.add(clean_url)
                        new_on_page += 1
                        t_title = a.get_text(strip=True) or "Untitled Post"
                        topics.append({"title": t_title, "url": clean_url, "date": None, "views": None})
                        if len(topics) >= limit:
                            break

        # If still 0 topics and query params were present, retry without query params on this page
        if new_on_page == 0 and query_str and not only_today:
            clean_page_url = f"{clean_base}page/{current_page}/" if current_page > 1 else clean_base
            if clean_page_url != target_url:
                try:
                    logger.info(f"🔄 Retrying forum page {current_page} without query parameters: {clean_page_url}")
                    clean_soup = _fetch_soup(clean_page_url)
                    for a in clean_soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if "/topic/" in href or "index.php?/topic/" in href:
                            full_url = urljoin(clean_base, href)
                            clean_url = _clean_topic_url(full_url)
                            if clean_url not in seen:
                                seen.add(clean_url)
                                new_on_page += 1
                                t_title = a.get_text(strip=True) or "Untitled Post"
                                topics.append({"title": t_title, "url": clean_url, "date": None, "views": None})
                                if len(topics) >= limit:
                                    break
                except Exception as e:
                    logger.debug(f"Could not fetch clean page {clean_page_url}: {e}")

        # If date cutoff reached, or no topics found on this page: stop pagination
        if hit_older or new_on_page == 0:
            break

        if len(topics) >= limit:
            break

        current_page += 1

    # Subforum traversal: ONLY for parent categories when not only_today and no direct topics were found
    if not topics and not only_today:
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
        if re.match(r"^https?://", a, re.I) or "dropmms.com" in a.lower() or "livecamrips.to" in a.lower():
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


def get_livecam_model_videos(
    model_url: str,
    only_today: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """
    Extract video items from a LiveCamRips model page in date-wise order (Newest -> Oldest).
    If only_today=True, strictly filters for videos posted today and breaks on older videos.
    """
    clean_base = model_url.split("?")[0].split("#")[0].rstrip("/")
    start_page = 1
    parts = [p for p in clean_base.split("/") if p]
    if len(parts) >= 4 and parts[0] == "model" and parts[-1].isdigit():
        start_page = max(1, int(parts[-1]))
        clean_base = "/".join(clean_base.split("/")[:-1])

    req_limit = limit or (50 if not only_today else 200)
    pages_to_scan = 10 if only_today else max(5, (req_limit + 15) // 16)
    max_pages = start_page + pages_to_scan - 1

    videos = []
    seen_ids = set()
    current_page = start_page

    while len(videos) < req_limit and current_page <= max_pages:
        if current_page == 1:
            target_url = f"{clean_base}?sort=newest"
        else:
            target_url = f"{clean_base}/{current_page}?sort=newest"

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


