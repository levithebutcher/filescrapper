# engines/wordpress.py
"""
WordPress Locker & Tube Engine.
Supports sites like Omaal63 (omaal63.net), DesiJugar (desijugar.me), GulabiHub (gulabihub.com),
and other WordPress-based lockers and tube blogs.
"""

import re
import html
import logging
from urllib.parse import urljoin, urlparse, quote_plus
from bs4 import BeautifulSoup

from engines.base import (
    BaseEngine,
    UniversalSort,
    UniversalDateResolver,
    _fetch_soup,
    _is_streaming_link,
    _clean_highres_image_url,
    _is_valid_thumbnail_url,
    _extract_streaming_links_from_html,
    extract_tags_and_quality,
    format_date_ist,
)

logger = logging.getLogger(__name__)


def is_wp_locker_url(url: str) -> bool:
    """Check if URL belongs to any supported WordPress locker/tube sites."""
    if not url or not isinstance(url, str):
        return False
    u = url.lower()
    return any(dom in u for dom in ["omaal63.net", "desijugar.me", "gulabihub.com", "mmsmaza.im"])


is_wp_url = is_wp_locker_url


def is_wp_locker_listing_url(url: str) -> bool:
    """Check if URL is a WordPress category, tag, author, search, or home archive page."""
    if not url or not is_wp_locker_url(url):
        return False
    u = url.lower().split("#")[0]
    if "?s=" in u or "&s=" in u:
        return True
    u_base = u.split("?")[0].rstrip("/")
    if u_base in [
        "https://omaal63.net", "https://desijugar.me", "https://gulabihub.com", "https://mmsmaza.im",
        "http://omaal63.net", "http://desijugar.me", "http://gulabihub.com", "http://mmsmaza.im"
    ]:
        return True
    return any(p in u_base for p in ["/category/", "/tag/", "/author/", "/page/"])


def is_wp_locker_post_url(url: str) -> bool:
    """Check if URL is an individual WordPress locker post."""
    return is_wp_locker_url(url) and not is_wp_locker_listing_url(url)


def get_wp_post_details(post_url: str) -> dict:
    """Fetch post details from WordPress locker/tube sites (Omaal63, DesiJugar, GulabiHub)."""
    soup = _fetch_soup(post_url)

    h1 = soup.find("h1", class_=re.compile(r"entry-title|post-title|title", re.I)) or soup.find("h1")
    title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "Untitled Post")
    clean_title, tags = extract_tags_and_quality(title)

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

    dt_ist, post_date_ist = UniversalDateResolver.resolve(
        soup=soup,
        url=post_url,
        fallback_db_url=post_url,
        title=title,
    )
    post_date_raw = dt_ist.isoformat() if dt_ist else None

    # Detect platform name from URL
    p_low = post_url.lower()
    site_key = "wp_locker"
    if "omaal63" in p_low:
        platform_name = "Omaal63"
    elif "desijugar" in p_low:
        platform_name = "DesiJugar"
    elif "gulabihub" in p_low:
        platform_name = "GulabiHub"
    elif "mmsmaza" in p_low:
        platform_name = "MMSMaza"
        site_key = "mmsmaza"
    else:
        platform_name = "WordPress Locker"

    # Category extraction from breadcrumbs/meta if available
    category_name = None
    cat_elem = soup.find("a", href=re.compile(r"/category/[^/]+"))
    if cat_elem:
        category_name = cat_elem.get_text(strip=True)

    return {
        "title": title,
        "clean_title": clean_title,
        "category": category_name,
        "category_name": category_name,
        "tags": tags,
        "thumbnail": thumbnail,
        "thumbnail_candidates": [thumbnail] if thumbnail else [],
        "streaming_links": streaming_links,
        "post_url": post_url,
        "date": post_date_raw,
        "date_ist": post_date_ist,
        "platform_name": platform_name,
        "site": site_key,
    }


def get_wp_listing_posts(listing_url: str, page: int = 1, limit: int = 25) -> list[dict]:
    """Fetch post items from WordPress locker listing, search, or category page with pagination."""
    parsed = urlparse(listing_url)
    clean_path = parsed.path.rstrip("/")
    clean_path = re.sub(r"/page/\d+/?$", "", clean_path)
    clean_base = f"{parsed.scheme}://{parsed.netloc}{clean_path}".rstrip("/")
    query_str = f"?{parsed.query}" if parsed.query else ""

    if page == 1:
        target_url = f"{clean_base}/{query_str}"
    else:
        target_url = f"{clean_base}/page/{page}/{query_str}"

    soup = _fetch_soup(target_url)
    posts = []
    seen = set()

    articles = soup.find_all("article")
    if not articles:
        articles = soup.find_all("div", class_=re.compile(r"post|item-video|thumb-block", re.I))

    for art in articles:
        classes = art.get("class", [])
        if any(c in classes for c in ["no-results", "not-found"]):
            continue

        h_elem = art.find(["h1", "h2", "h3", "h4"], class_=re.compile(r"title|entry-title", re.I))
        link = h_elem.find("a", href=True) if h_elem else None

        if not link:
            for a in art.find_all("a", href=True):
                href_cand = a["href"].strip()
                if not any(x in href_cand for x in ["/category/", "/tag/", "/author/", "?s="]):
                    link = a
                    break

        if not link:
            continue

        href = urljoin(target_url, link["href"].strip())
        if href in seen or not href.startswith("http"):
            continue

        title = ""
        if h_elem:
            title = h_elem.get_text(strip=True)
        if not title and link.get("title"):
            title = link["title"].strip()
        if not title:
            title = link.get_text(strip=True)
        if not title or title.lower() in ("nothing found", "no results", "page not found", "untitled post"):
            continue

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


def get_wp_categories(site_key: str) -> list[dict]:
    """Fetch categories from supported WordPress sites (Omaal63, DesiJugar, GulabiHub)."""
    site_urls = {
        "omaal": "https://omaal63.net/",
        "desijugar": "https://desijugar.me/",
        "gulabi": "https://gulabihub.com/categories/",
        "mmsmaza": "https://mmsmaza.im/categories/",
    }
    target = site_urls.get(site_key.lower().strip())
    if not target:
        return []

    soup = _fetch_soup(target)
    if not soup:
        return []

    categories = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/category/" in href:
            clean_url = href.split("?")[0].rstrip("/") + "/"
            name = a.get_text(strip=True)
            if not name or name.lower() in ("categories", "category", "uncategorized") or len(name) > 35:
                continue
            if clean_url not in seen:
                seen.add(clean_url)
                categories.append({
                    "name": name,
                    "url": clean_url,
                })

    return categories


class WordPressLockerEngine(BaseEngine):
    """WordPress Locker & Tube Engine."""
    name: str = "WordPressLocker"
    domains: list[str] = ["omaal63.net", "desijugar.me", "gulabihub.com", "mmsmaza.im"]
    supported_sorts: dict[UniversalSort, str] = {
        UniversalSort.NEWEST: "date",
    }

    def is_listing_url(self, url: str) -> bool:
        return is_wp_locker_listing_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_wp_locker_post_url(url)

    def get_details(self, url: str) -> dict:
        return get_wp_post_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        return get_wp_listing_posts(url, **kwargs)

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        base_domain = kwargs.get("base_domain", "https://desijugar.me")
        search_url = f"{base_domain.rstrip('/')}/?s={quote_plus(query.strip())}"
        return get_wp_listing_posts(search_url, page=kwargs.get("page", 1), limit=limit)
