# engines/kvs.py
"""
KVS (Kernel Video Sharing) Scraper Engine.
Specialized for tube platforms built on KVS CMS:
- X-Video Tube (x-video.tube)
- HornySapiens (hornysapiens.com)
- ViralXXXPorn (viralxxxporn.com)
Extracts direct CDN MP4 streams, quality tags, models, duration, and handles sorting & search.
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
    _clean_highres_image_url,
    extract_tags_and_quality,
    format_date_ist,
)

logger = logging.getLogger(__name__)


def is_kvs_url(url: str) -> bool:
    """Check if URL belongs to any supported KVS tube site."""
    if not url or not isinstance(url, str):
        return False
    u = url.lower()
    return any(d in u for d in ["x-video.tube", "hornysapiens.com", "viralxxxporn.com"])


def is_kvs_video_url(url: str) -> bool:
    """Check if URL is an individual video page on KVS sites."""
    if not is_kvs_url(url):
        return False
    path = urlparse(url.lower()).path.rstrip("/")
    # Exclude tag, model, category, or search listing routes even when suffixed with /videos
    if re.search(r"^/(tags?|models?|categor(?:y|ies)|search)/", path):
        return False
    # Exclude paginated listing index like /videos or /videos/2
    if re.fullmatch(r"/videos(?:/\d{1,2})?", path):
        return False
    return bool(re.match(r"^/videos?/[^/]+", path))


def is_kvs_listing_url(url: str) -> bool:
    """Check if URL is a tag, model, category, or search listing page."""
    if not is_kvs_url(url):
        return False
    return not is_kvs_video_url(url)


def clean_kvs_video_url(raw_url: str) -> str:
    """Clean obfuscated function wrapper from KVS flashvars video URL."""
    if not raw_url:
        return ""
    # Strip function/0/ or function/X/ prefix commonly found in KVS
    cleaned = re.sub(r"^function/\d+/", "", raw_url.strip())
    # Strip trailing slashes after mp4 if present
    cleaned = re.sub(r"(\.mp4)/+$", r"\1", cleaned)
    return cleaned


def get_kvs_video_details(video_url: str) -> dict:
    """Fetch video details from KVS video page and extract direct MP4 stream."""
    soup = _fetch_soup(video_url)
    page_html = str(soup)

    u_low = video_url.lower()
    if "x-video.tube" in u_low:
        site_key = "xvideotube"
        platform_name = "X-Video Tube"
    elif "viralxxxporn" in u_low:
        site_key = "viralxxxporn"
        platform_name = "ViralXXXPorn"
    else:
        site_key = "hornysapiens"
        platform_name = "HornySapiens"

    # Title extraction: Prioritize og:title, schema.org VideoObject, and content title (avoid logo <h1>)
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        cand_t = og_title["content"].strip()
        if cand_t and not any(cand_t.lower() == x for x in ("x-video", "x -video", "hornysapiens", "viralxxxporn")):
            title = cand_t

    if not title:
        h1_cand = soup.find(["h1", "h2", "span"], class_=re.compile(r"\btitle\b|\bheadline\b|video-title", re.I))
        if h1_cand:
            cand_t = h1_cand.get_text(strip=True)
            if cand_t and not any(cand_t.lower() == x for x in ("x-video", "x -video", "hornysapiens", "viralxxxporn")):
                title = cand_t

    if not title:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("name"):
                    title = data["name"].strip()
                    break
            except Exception:
                pass

    if not title:
        if soup.title and soup.title.get_text():
            raw_t = soup.title.get_text(strip=True)
            raw_t = re.sub(r"^Watch\s+online\s+", "", raw_t, flags=re.I)
            raw_t = re.sub(r"\s+on\s+X-video.*$", "", raw_t, flags=re.I)
            raw_t = re.sub(r"\s*[-–|]\s*(?:X-Video Tube|HornySapiens|ViralXXXPorn|X-VIDEO).*$", "", raw_t, flags=re.I)
            if raw_t:
                title = raw_t.strip()

    if not title:
        h1 = soup.find("h1") or soup.find("span", class_=re.compile(r"headline|title", re.I))
        title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "Untitled Video")

    clean_title, tags = extract_tags_and_quality(title)

    # Model / Actor or Tag extraction
    model_name = ""
    model_link = soup.find("a", href=re.compile(r"/models/|/tags/"))
    if model_link:
        model_name = model_link.get_text(strip=True)
    if not model_name:
        m_mod = re.search(r"/(?:models|tags)/([^/]+)/", video_url)
        if m_mod:
            model_name = m_mod.group(1).replace("-", " ").title()

    # Duration extraction
    duration = None
    meta_dur = soup.find("meta", property="video:duration")
    if meta_dur and meta_dur.get("content"):
        try:
            secs = int(meta_dur["content"].strip())
            duration = f"{secs // 60:02d}:{secs % 60:02d}"
        except Exception:
            pass

    if not duration:
        m_iso = re.search(r'duration":\s*["\']PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?["\']', page_html)
        if m_iso:
            h = int(m_iso.group(1) or 0)
            m = int(m_iso.group(2) or 0)
            s = int(m_iso.group(3) or 0)
            total_s = h * 3600 + m * 60 + s
            if total_s > 0:
                duration = f"{total_s // 60:02d}:{total_s % 60:02d}"

    if not duration:
        m_sec = re.search(r"video_duration:\s*['\"]?(\d+)['\"]?", page_html)
        if m_sec:
            secs = int(m_sec.group(1))
            duration = f"{secs // 60:02d}:{secs % 60:02d}"

    if not duration:
        dur_elem = soup.find(class_=re.compile(r"duration|time", re.I))
        if dur_elem and dur_elem.get_text(strip=True):
            d_raw = dur_elem.get_text(strip=True)
            if re.search(r"\d+:\d+|\d+m|\d+s", d_raw):
                duration = d_raw

    if not duration:
        m_dur = re.search(r"duration:\s*['\"]([^'\"]+)['\"]", page_html)
        if m_dur:
            duration = m_dur.group(1)

    if duration and str(duration).isdigit():
        secs = int(duration)
        duration = f"{secs // 60:02d}:{secs % 60:02d}"

    # Quality extraction
    quality = "1080p Full HD" if "1080p" in page_html or "1080" in title else ("720p HD" if "720" in page_html else None)

    # Views extraction
    views = None
    views_elem = soup.find(class_=re.compile(r"views", re.I))
    if views_elem:
        m_v = re.search(r"([\d,.]+\s*(?:K|M|views)?)", views_elem.get_text(strip=True), re.I)
        if m_v:
            views = m_v.group(1).strip()

    # Direct MP4 extraction from flashvars / script / video tag
    streaming_link = None
    # 1. Look for video_url in flashvars
    v_matches = re.findall(r"video_url:\s*['\"]([^'\"]+)['\"]", page_html)
    for vm in v_matches:
        cand = clean_kvs_video_url(vm)
        if cand.startswith("http") and ".mp4" in cand:
            streaming_link = cand
            break

    # 2. Look for video_alt_url in flashvars
    if not streaming_link:
        v_alt = re.findall(r"video_alt_url:\s*['\"]([^'\"]+)['\"]", page_html)
        for vm in v_alt:
            cand = clean_kvs_video_url(vm)
            if cand.startswith("http") and ".mp4" in cand:
                streaming_link = cand
                break

    # 3. Look for video or source tag
    if not streaming_link:
        for src_tag in soup.find_all(["video", "source"], src=True):
            cand = src_tag["src"].strip()
            if ".mp4" in cand:
                streaming_link = cand
                break

    # 4. Fallback: regex search for CDN mp4
    if not streaming_link:
        mp4_matches = re.findall(r"https?://[^\s\"'<>]+\.mp4[^\s\"'<>]*", page_html)
        for m4 in mp4_matches:
            if not any(x in m4 for x in ["preview", "trailer", "banner"]):
                streaming_link = m4
                break

    # Thumbnail extraction
    thumbnail = None
    thumbnail_candidates = []
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        og_url = og_img["content"].strip()
        if not any(x in og_url.lower() for x in ["logo.png", "logo.jpg", "favicon"]):
            thumbnail = og_url
            thumbnail_candidates.append(og_url)

    preview_match = re.search(r"preview_url:\s*['\"]([^'\"]+)['\"]", page_html)
    if preview_match:
        p_url = preview_match.group(1).strip()
        if p_url not in thumbnail_candidates and not any(x in p_url.lower() for x in ["logo.png", "logo.jpg"]):
            thumbnail_candidates.append(p_url)
        if not thumbnail:
            thumbnail = p_url

    v_tag = soup.find("video")
    if v_tag and v_tag.get("poster"):
        pos_url = v_tag["poster"].strip()
        if pos_url not in thumbnail_candidates:
            thumbnail_candidates.append(pos_url)
        if not thumbnail:
            thumbnail = pos_url

    # Check for screenshot thumbs in HTML
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "/videos_screenshots/" in src and src not in thumbnail_candidates:
            thumbnail_candidates.append(src)

    thumbnail = _clean_highres_image_url(thumbnail) if thumbnail else None
    thumbnail_candidates = [_clean_highres_image_url(t) for t in thumbnail_candidates if t]
    if thumbnail and thumbnail not in thumbnail_candidates:
        thumbnail_candidates.insert(0, thumbnail)

    # Date resolution
    dt_ist, date_display = UniversalDateResolver.resolve(
        soup=soup,
        url=video_url,
        fallback_db_url=video_url,
        title=title,
    )
    post_date_raw = dt_ist.isoformat() if dt_ist else None

    return {
        "title": title,
        "clean_title": clean_title,
        "model_name": model_name,
        "quality": quality,
        "duration": duration,
        "views": views,
        "thumbnail": thumbnail,
        "thumbnail_candidates": thumbnail_candidates if thumbnail_candidates else ([thumbnail] if thumbnail else []),
        "streaming_link": streaming_link,
        "streaming_links": [streaming_link] if streaming_link else [],
        "post_url": video_url,
        "date": post_date_raw,
        "date_ist": date_display or "Recently",
        "platform_name": platform_name,
        "site": site_key,
    }


def get_kvs_listing_items(
    listing_url: str,
    sort: str = "latest",
    page: int = 1,
    limit: int = 25,
) -> list[dict]:
    """Fetch video items from KVS listing page (tag, model, search)."""
    base_url = listing_url.split("?")[0].rstrip("/")
    u_low = base_url.lower()

    if "x-video.tube" in u_low and "/models/" in u_low and not u_low.endswith("/videos") and "/videos/" not in u_low:
        base_url = f"{base_url.rstrip('/')}/videos"
        u_low = base_url.lower()

    params = []
    if "x-video.tube" in u_low:
        if sort == "longest":
            params.append("by=duration")
        else:
            params.append("by=post_date")
    else:  # Hornysapiens / ViralXXXPorn
        if sort == "views":
            params.append("sort_by=video_viewed")
        elif sort == "longest":
            params.append("sort_by=duration")
        else:
            params.append("sort_by=post_date")

    if page > 1:
        if "x-video.tube" in u_low:
            base_url = f"{base_url.rstrip('/')}/{page}"
        elif "/search/" in u_low:
            params.append(f"from_videos={page:02d}")
            params.append(f"from={page:02d}")
        else:
            params.append(f"from={page:02d}")

    query_str = ("?" + "&".join(params)) if params else ""
    target_url = f"{base_url.rstrip('/')}/{query_str}" if query_str else f"{base_url.rstrip('/')}/"

    try:
        soup = _fetch_soup(target_url)
    except Exception as e:
        logger.debug(f"KVS listing fetch failed for {target_url}: {e}")
        return []
    items = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Strictly match individual video pages with video ID numbers
        # (e.g. /video/12345/ or /videos/12345/) and reject navigation links (/videos/?by=duration)
        if not re.search(r"/videos?/(?:[a-zA-Z0-9_-]+/)?\d+", href):
            continue
        full_url = urljoin(target_url, href)
        if full_url in seen or full_url.endswith("/videos/") or full_url.endswith("/video/"):
            continue
        seen.add(full_url)

        # Title
        title = a.get("title") or a.get_text(strip=True)
        if not title:
            parent = a.find_parent(["div", "article", "li"])
            if parent:
                t_el = parent.find(["strong", "span", "h3", "h4"])
                if t_el:
                    title = t_el.get_text(strip=True)
        if not title or title.lower() in ("video", "watch"):
            continue

        # Thumbnail
        thumb = None
        img = a.find("img")
        if img:
            thumb = img.get("data-src") or img.get("data-original") or img.get("src")
        if thumb:
            thumb = urljoin(target_url, thumb)

        # Duration
        duration = None
        parent = a.find_parent(["div", "article", "li"])
        if parent:
            dur_el = parent.find(class_=re.compile(r"duration|time", re.I))
            if dur_el:
                duration = dur_el.get_text(strip=True)

        items.append({
            "title": title,
            "url": full_url,
            "thumbnail": thumb,
            "duration": duration,
            "date": None,
            "date_ist": None,
        })
        if len(items) >= limit:
            break

    return items


def search_kvs(site_key: str, query: str, page: int = 1, limit: int = 25) -> list[dict]:
    """Search videos on KVS site."""
    encoded_q = quote_plus(query.strip())
    if site_key == "xvideotube":
        search_url = f"https://x-video.tube/search/{encoded_q}/"
    elif site_key == "viralxxxporn":
        search_url = f"https://viralxxxporn.com/search/{encoded_q}/"
    else:
        search_url = f"https://hornysapiens.com/search/{encoded_q}/"
    return get_kvs_listing_items(search_url, page=page, limit=limit)


def search_kvs_models(site_key: str, query: str, limit: int = 10) -> list[dict]:
    """Search models/tags on KVS sites (LiveCam style)."""
    clean_q = query.strip()
    if not clean_q:
        return []

    models = []
    seen = set()
    seen_names = set()
    query_tokens = [w.lower() for w in re.findall(r"\w+", clean_q) if len(w) > 1]

    if site_key == "xvideotube":
        base_domain = "https://x-video.tube"
    elif site_key == "viralxxxporn":
        base_domain = "https://viralxxxporn.com"
    else:
        base_domain = "https://hornysapiens.com"

    # 1. First test candidate direct model / tag profile slugs
    slug_hyphen = re.sub(r"[^a-zA-Z0-9_-]", "", clean_q.lower().replace(" ", "-"))
    slug_compact = re.sub(r"[^a-zA-Z0-9_-]", "", clean_q.lower().replace(" ", ""))

    candidate_paths = []
    if site_key == "xvideotube":
        candidate_paths = [
            (f"/models/{slug_hyphen}/", clean_q.title(), slug_hyphen),
            (f"/tags/{slug_hyphen}-onlyfans-leaked/videos/", f"{clean_q.title()} OnlyFans Leaked", f"{slug_hyphen}-onlyfans-leaked"),
            (f"/tags/{slug_compact}-onlyfans-leaked/videos/", f"{clean_q.title()} OnlyFans Leaked", f"{slug_compact}-onlyfans-leaked"),
            (f"/tags/{slug_hyphen}/videos/", clean_q.title(), slug_hyphen),
        ]
    else:
        candidate_paths = [
            (f"/models/{slug_hyphen}/", clean_q.title(), slug_hyphen),
            (f"/models/{slug_compact}/", clean_q.title(), slug_compact),
            (f"/tags/{slug_hyphen}/", clean_q.title(), slug_hyphen),
        ]

    for rel_path, display_name, cand_slug in candidate_paths:
        full_cand_url = urljoin(base_domain, rel_path)
        norm_name = re.sub(r"\s+", " ", display_name.lower().strip())
        if full_cand_url in seen or cand_slug in seen or norm_name in seen_names:
            continue
        try:
            cand_soup = _fetch_soup(full_cand_url)
            if cand_soup and cand_soup.title:
                t_str = cand_soup.title.get_text().lower()
                # Ensure it's not an error page or a generic fallback redirect to all models
                if "404" in t_str or "not found" in t_str or "error" in t_str:
                    continue
                # Page title or slug must match query tokens, not generic index pages
                if query_tokens and not any(t in t_str or t in cand_slug for t in query_tokens):
                    continue
                # Verify that the page has actual video/content links
                has_content = any(
                    "/video/" in a.get("href", "") or "/videos/" in a.get("href", "")
                    for a in cand_soup.find_all("a", href=True)
                )
                if not has_content and "onlyfans" not in cand_slug:
                    continue

                seen.add(full_cand_url)
                seen.add(cand_slug)
                seen_names.add(norm_name)
                models.append({
                    "name": display_name,
                    "url": full_cand_url,
                    "slug": cand_slug,
                })
                if len(models) >= limit:
                    return models
        except Exception:
            pass

    # 2. Search listing scan with strict query token matching (ignoring unrelated sidebar widgets)
    encoded_q = quote_plus(clean_q)
    search_urls = [
        f"{base_domain}/search/{encoded_q}/",
        f"{base_domain}/models/?query={encoded_q}",
    ]

    for s_url in search_urls:
        try:
            soup = _fetch_soup(s_url)
        except Exception:
            continue
        if not soup:
            continue
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "/models/" in href or "/tags/" in href:
                full_url = urljoin(base_domain, href).split("?")[0].rstrip("/") + "/"
                if full_url in seen or full_url.endswith("/models/") or full_url.endswith("/tags/"):
                    continue
                parts = full_url.rstrip("/").split("/")
                slug = parts[-1]
                if not slug or slug in seen:
                    continue

                # Clean name
                name = a.get("title") or a.get_text(strip=True)
                name = re.sub(r"^\d+%|\d+[\d,.]*\s*(?:views|videos)?|no image", "", name, flags=re.I).strip()
                if not name or len(name) < 2:
                    name = slug.replace("-", " ").title()

                norm_name = re.sub(r"\s+", " ", name.lower().strip())
                if norm_name in seen_names:
                    continue

                # Strict validation: Must match at least one token from search query
                if query_tokens and not any(t in slug.lower() or t in name.lower() for t in query_tokens):
                    continue

                seen.add(slug)
                seen.add(full_url)
                seen_names.add(norm_name)
                models.append({
                    "name": name,
                    "url": full_url,
                    "slug": slug,
                })
                if len(models) >= limit:
                    break
        if len(models) >= limit:
            break

    return models


class KvsEngine(BaseEngine):
    """Unified KVS Tube Engine."""
    name: str = "KVSTube"
    domains: list[str] = ["x-video.tube", "hornysapiens.com", "viralxxxporn.com"]
    supported_sorts: dict[UniversalSort, str] = {
        UniversalSort.NEWEST: "latest",
        UniversalSort.MOST_VIEWED: "views",
        UniversalSort.LONGEST: "longest",
    }

    def is_listing_url(self, url: str) -> bool:
        return is_kvs_listing_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_kvs_video_url(url)

    def get_details(self, url: str) -> dict:
        return get_kvs_video_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        sort = kwargs.get("sort", "latest")
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 25)
        return get_kvs_listing_items(url, sort=sort, page=page, limit=limit)

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        site_key = kwargs.get("site_key", "hornysapiens")
        page = kwargs.get("page", 1)
        return search_kvs(site_key, query, page=page, limit=limit)
