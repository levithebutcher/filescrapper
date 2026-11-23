# engines/wordpress.py
"""
WordPress Locker & Tube Engine.
Supports sites like Omaal63 (omaal63.net), DesiJugar (desijugar.me), GulabiHub (gulabihub.com),
and other WordPress-based lockers and tube blogs.
"""

import re
import html
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from engines.base import (
    BaseEngine,
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


class WordPressLockerEngine(BaseEngine):
    """WordPress Locker & Tube Engine."""
    name: str = "WordPressLocker"
    domains: list[str] = ["omaal63.net", "desijugar.me", "gulabihub.com"]

    def is_listing_url(self, url: str) -> bool:
        return is_wp_locker_listing_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_wp_locker_post_url(url)

    def get_details(self, url: str) -> dict:
        return get_wp_post_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        return get_wp_listing_posts(url, **kwargs)
