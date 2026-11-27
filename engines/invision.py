# engines/invision.py
"""
Invision Community (IPS4) Forum Engine.
Supports DropMMS (dropmms.com), MMSTown (mmstown.com), and similar IPS forum installations.
"""

import re
import html
import logging
from urllib.parse import urljoin, quote_plus
from bs4 import BeautifulSoup

from config import (
    BASE_URL,
    MAX_TITLE_LENGTH,
    MAX_POSTS_PER_FORUM,
)
from engines.base import (
    BaseEngine,
    UniversalSort,
    UniversalDateResolver,
    _fetch_soup,
    _extract_all_image_candidates,
    _is_streaming_link,
    _extract_streaming_links_from_html,
    extract_tags_and_quality,
    format_date_ist,
    check_date_filter_match,
    parse_to_ist,
)

logger = logging.getLogger(__name__)


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
        title_container = row.find(class_=re.compile(r"ipsDataItem_title|ipsType_break|cForumRow_title", re.I)) or row.find("h4")
        if title_container:
            link_elem = title_container.find("a", href=re.compile(r"/topic/|/topics/topic/|index\.php\?/topic/", re.I))
        else:
            link_elem = row.find("a", href=re.compile(r"/topic/|/topics/topic/|index\.php\?/topic/", re.I))

        if not link_elem:
            continue

        raw_href = link_elem["href"].strip()
        full_url = urljoin(clean_base, raw_href)
        clean_url = _clean_topic_url(full_url)

        if clean_url in seen:
            continue

        # Extract topic author creation date specifically, avoiding reply time
        author_meta = row.find(class_=re.compile(r"ipsDataItem_meta|ipsType_light", re.I))
        time_elem = None
        if author_meta:
            time_elem = author_meta.find("time")
        if not time_elem:
            for t in row.find_all("time"):
                if not t.find_parent(class_=re.compile(r"ipsDataItem_lastPoster", re.I)):
                    time_elem = t
                    break
        if not time_elem:
            time_elem = row.find("time")

        post_date_raw = None
        post_date_text = None
        if time_elem:
            post_date_raw = time_elem.get("datetime") or time_elem.get("title")
            post_date_text = time_elem.get_text(strip=True)

        # Isolate author text so replies don't pollute the creation date
        last_poster = row.find(class_=re.compile(r"ipsDataItem_lastPoster", re.I))
        if last_poster:
            lp_text = last_poster.get_text(" ", strip=True)
            full_row_text = row.get_text(" ", strip=True).replace(lp_text, "").strip()
        else:
            full_row_text = row.get_text(" ", strip=True)

        if active_date_filter:
            is_match, is_definitely_older = check_date_filter_match(
                post_date_raw,
                post_date_text,
                date_filter=active_date_filter,
                full_row_text=full_row_text,
            )
            if is_definitely_older:
                consecutive_older += 1
                if consecutive_older >= 3:
                    hit_older = True
                    break
                continue
            else:
                consecutive_older = 0

            if not is_match:
                continue

        seen.add(clean_url)
        new_count += 1

        topic_title = link_elem.get_text(strip=True)
        if not topic_title:
            topic_title = "Untitled Post"

        dt_ist, post_date_ist = UniversalDateResolver.resolve(
            raw_date=post_date_raw,
            time_text=post_date_text,
            title=topic_title,
        )
        if not post_date_raw and dt_ist:
            post_date_raw = dt_ist.isoformat()

        views_elem = row.find(class_=re.compile(r"ipsDataItem_stats|stats|cForumRow_views", re.I))
        views = views_elem.get_text(strip=True) if views_elem else None

        new_topics.append({
            "title": topic_title,
            "url": clean_url,
            "date": post_date_raw,
            "date_ist": post_date_ist,
            "views": views,
        })

        if len(new_topics) >= limit:
            break

    # Fallback parsing if no topics were found using row classes
    if not new_topics and not hit_older:
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "/topic/" in href or "index.php?/topic/" in href:
                clean_url = _clean_topic_url(urljoin(clean_base, href))
                if clean_url not in seen:
                    if active_date_filter:
                        p_elem = a.find_parent(["li", "div", "tr"])
                        t_elem = p_elem.find("time") if p_elem else None
                        r_date = (t_elem.get("datetime") or t_elem.get("title")) if t_elem else None
                        t_text = t_elem.get_text(strip=True) if t_elem else None
                        f_text = p_elem.get_text(" ", strip=True) if p_elem else None
                        is_m, is_old = check_date_filter_match(r_date, t_text, date_filter=active_date_filter, full_row_text=f_text)
                        if is_old or not is_m:
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
    """Fetch structured topics from an IPS forum category with multi-page pagination."""
    active_date_filter = date_filter or ("today" if only_today else None)
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

    query_str = ""
    if "?" in forum_url:
        raw_query = forum_url.split("?")[1].split("#")[0]
        filtered_parts = [p for p in raw_query.split("&") if not re.match(r"^page=\d+$", p, re.I)]
        query_str = "&".join(filtered_parts)

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

        if hit_older or new_on_page == 0:
            break

        if len(topics) >= limit:
            break

        current_page += 1

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


# Curated DropMMS forums
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
    """Fetch active forum categories from DropMMS index, filtered to CURATED_FORUM_IDS."""
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


# Curated MMSTown forums
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
    """Fetch active forum categories from MMSTown, filtered to CURATED_MMSTOWN_FORUM_IDS."""
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
    """Fetch DropMMS / IPS forum category metadata: title, total pages, estimated topics."""
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


def search_forum_advanced(
    query: str,
    page: int = 1,
    limit: int = 10,
    search_in: str = "titles",
    sort_by: str = "newest",
    base_url: str = BASE_URL,
    forum_id: int | str | None = None,
) -> dict:
    """
    Advanced multi-parameter IPS4 forum search with total results counting and typo-tolerance.
    Supports title-only filtering, forum node scoping (in-forum search), date sorting, and multi-page pagination.
    """
    clean_query = query.strip()
    if not clean_query:
        return {"topics": [], "total_count": 0, "total_pages": 1, "page": page, "query": "", "forum_id": forum_id}

    b_url = base_url.rstrip("/")
    # Build primary search URL with title filter and date sort (no nodes parameter in URL to avoid Nginx 404)
    search_params = [
        f"q={quote_plus(clean_query)}",
        "type=forums_topic",
    ]
    if search_in == "titles":
        search_params.append("search_in=titles")
    if sort_by:
        search_params.append(f"sortby={quote_plus(sort_by)}")
    if page > 1:
        search_params.append(f"page={page}")

    search_url = f"{b_url}/search/?{'&'.join(search_params)}"

    def _execute_search_parse(target_url: str) -> tuple[list[dict], int, int]:
        try:
            soup = _fetch_soup(target_url)
        except Exception as e:
            logger.warning(f"Search fetch error for {target_url}: {e}")
            return [], 0, 1

        if not soup:
            return [], 0, 1

        # 1. Extract total count
        total_count = 0
        h1 = soup.find("h1", class_=re.compile(r"ipsType_pageTitle", re.I)) or soup.find("h1")
        if h1:
            m_count = re.search(r"(\d+)\s+results?", h1.get_text())
            if m_count:
                total_count = int(m_count.group(1))

        if not total_count:
            p_reset = soup.find("p", class_=re.compile(r"ipsType_reset", re.I))
            if p_reset:
                m_count = re.search(r"(\d+)\s+results?", p_reset.get_text())
                if m_count:
                    total_count = int(m_count.group(1))

        # 2. Extract total pages
        total_pages = 1
        for ul in soup.find_all("ul", class_=re.compile(r"ipsPagination", re.I)):
            dp = ul.get("data-pages")
            if dp and dp.isdigit():
                total_pages = max(total_pages, int(dp))

        results = []
        seen = set()

        # Check structured stream items first (IPS4 standard)
        stream_items = soup.find_all("li", class_=re.compile(r"ipsStreamItem", re.I))
        for item in stream_items:
            # If scoped to a specific forum_id, check if item belongs to that forum
            if forum_id:
                f_link = item.find("a", href=re.compile(rf"/forum/{forum_id}(?:-[^/\"' >]*)?/?"))
                if not f_link:
                    all_f_links = item.find_all("a", href=re.compile(r"/forum/(\d+)"))
                    matched = False
                    for fl in all_f_links:
                        m_f = re.search(r"/forum/(\d+)", fl.get("href", ""))
                        if m_f and str(m_f.group(1)) == str(forum_id):
                            matched = True
                            break
                    if all_f_links and not matched:
                        continue

            h2 = item.find("h2", class_=re.compile(r"ipsStreamItem_title", re.I)) or item.find("h2") or item.find("h3")
            if h2:
                a_tag = h2.find("a", href=True)
                if a_tag:
                    href = a_tag["href"].strip()
                    full = urljoin(target_url, href)
                    if "/topic/" in full:
                        clean = _clean_topic_url(full)
                        if clean not in seen:
                            seen.add(clean)
                            title = a_tag.get_text(strip=True)
                            if title and len(title) > 3:
                                # Extract topic creation date
                                time_elem = item.find("time")
                                post_date_raw = None
                                post_date_text = None
                                if time_elem:
                                    post_date_raw = time_elem.get("datetime") or time_elem.get("title")
                                    post_date_text = time_elem.get_text(strip=True)
                                dt_ist, date_ist = UniversalDateResolver.resolve(
                                    raw_date=post_date_raw,
                                    time_text=post_date_text,
                                )
                                results.append({
                                    "title": title,
                                    "url": clean,
                                    "date": post_date_raw or (dt_ist.isoformat() if dt_ist else None),
                                    "date_ist": date_ist,
                                })
                                if len(results) >= limit:
                                    break

        # Fallback to general anchor search if stream items didn't match
        if not results:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                full = urljoin(target_url, href)
                if "/topic/" in full:
                    clean = _clean_topic_url(full)
                    if clean not in seen:
                        seen.add(clean)
                        title = a.get_text(strip=True)
                        if title and len(title) > 3 and not title.lower().startswith("page"):
                            results.append({"title": title, "url": clean, "date": None, "date_ist": None})
                            if len(results) >= limit:
                                break

        if not total_count:
            total_count = len(results)

        return results, total_count, total_pages

    items, total_found, total_p = _execute_search_parse(search_url)

    # Smart Typo & Fallback: If 0 results with search_in=titles, retry with search_and_or=or and full content
    if not items and search_in == "titles":
        fallback_params = [
            f"q={quote_plus(clean_query)}",
            "type=forums_topic",
            "search_and_or=or",
            f"sortby={quote_plus(sort_by or 'newest')}",
        ]
        if page > 1:
            fallback_params.append(f"page={page}")
        fallback_url = f"{b_url}/search/?{'&'.join(fallback_params)}"
        items, total_found, total_p = _execute_search_parse(fallback_url)

    # Secondary In-Forum Scanner: If scoped to a forum_id and search yielded few/no items,
    # match against topics from the forum category page directly
    if forum_id and len(items) < limit:
        cat_url = f"{b_url}/forum/{forum_id}-category/"
        try:
            cat_topics = get_forum_topics(cat_url, sort_by="start_date", limit=30)
            seen_urls = {it["url"] for it in items}
            q_words = [w.lower() for w in clean_query.split() if len(w) > 1]
            for ct in cat_topics:
                t_low = ct["title"].lower()
                if (clean_query.lower() in t_low) or any(w in t_low for w in q_words):
                    if ct["url"] not in seen_urls:
                        seen_urls.add(ct["url"])
                        items.append(ct)
                        if len(items) >= limit:
                            break
            if items:
                total_found = max(total_found, len(items))
        except Exception as e_cat:
            logger.debug(f"Direct category topic matching note: {e_cat}")

    return {
        "topics": items,
        "total_count": total_found,
        "total_pages": total_p,
        "page": page,
        "query": clean_query,
        "forum_id": forum_id,
    }


def search_forum(query: str, limit: int = 5, base_url: str = BASE_URL, page: int = 1) -> list[dict]:
    """Search an IPS forum (DropMMS or MMSTown) by keyword and return top matching topics."""
    if isinstance(base_url, int):
        # Recover if positional arguments (query, page, limit) were provided
        page, limit, base_url = limit, base_url, BASE_URL
    res = search_forum_advanced(query=query, page=page, limit=limit, base_url=base_url)
    return res.get("topics", [])


def get_post_links_from_forum(forum_url: str) -> list[str]:
    """Legacy helper: Extract list of post URLs from a forum page."""
    topics = get_forum_topics(forum_url, sort_by="start_date", limit=MAX_POSTS_PER_FORUM)
    return [t["url"] for t in topics]


def get_post_details(post_url: str) -> dict:
    """Fetch post details: title, tags, thumbnail, and streaming links."""
    soup = _fetch_soup(post_url)

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

    first_post = soup.select_one(".cPost, .ipsComment, [data-role='comment']")
    target_soup = first_post if first_post else soup

    dt_ist, post_date_ist = UniversalDateResolver.resolve(
        soup=target_soup,
        url=post_url,
        fallback_db_url=post_url,
        title=title,
    )
    post_date_raw = dt_ist.isoformat() if dt_ist else None

    # Detect platform name from URL
    p_low = post_url.lower()
    if "dropmms" in p_low:
        platform_name = "DropMMS"
    elif "mmstown" in p_low:
        platform_name = "MMSTown"
    else:
        platform_name = "Invision Community"

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
        "platform_name": platform_name,
        "site": "invision",
    }


class InvisionCommunityEngine(BaseEngine):
    """Invision Community IPS4 Forum Engine (DropMMS, MMSTown, etc.)."""
    name: str = "InvisionCommunity"
    domains: list[str] = ["dropmms.com", "mmstown.com"]
    supported_sorts: dict[UniversalSort, str] = {
        UniversalSort.NEWEST: "start_date",
        UniversalSort.MOST_VIEWED: "views",
        UniversalSort.OLDEST: "oldest",
    }

    def is_listing_url(self, url: str) -> bool:
        return is_forum_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_topic_url(url)

    def get_details(self, url: str) -> dict:
        return get_post_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        return get_forum_topics(url, **kwargs)

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        base_url = kwargs.get("base_url", BASE_URL)
        return search_forum(query, limit=limit, base_url=base_url)
