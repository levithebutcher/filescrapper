# engines/livecam.py
"""
LiveCam Engine.
Supports LiveCamRips (livecamrips.to) model recordings, iframe embeds, and search.
"""

import re
import html
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, quote
from bs4 import BeautifulSoup

from engines.base import (
    BaseEngine,
    _fetch_soup,
    _extract_streaming_links_from_html,
    get_host_display_name,
)

logger = logging.getLogger(__name__)


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
    """Clean LiveCamRips title by stripping recording text and metadata."""
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
    """Fetch model page metadata: model name, total pages, and estimated total videos."""
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


def get_livecam_model_videos(
    model_url: str,
    only_today: bool = False,
    limit: int | None = None,
    sort_by: str = "newest",
    start_page: int | None = None,
) -> list[dict]:
    """Extract video items from a LiveCamRips model page in sorted order."""
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

    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\b", raw_h1_text or soup.get_text())
    raw_date = date_match.group(1) if date_match else None
    date_display = format_livecam_date(raw_date)

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

    streaming_links = []
    seen_links = set()
    for tag in soup.find_all(["iframe", "embed", "source"], src=True):
        src = tag["src"].strip()
        full_src = urljoin(video_url, src)
        if full_src not in seen_links:
            seen_links.add(full_src)
            streaming_links.append(full_src)

    more_links = _extract_streaming_links_from_html(soup, video_url)
    for ml in more_links:
        if ml not in seen_links:
            seen_links.add(ml)
            streaming_links.append(ml)

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
    """Format LiveCamRips video card with Telegram blockquote and copyable links."""
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

    if mode in ["both", "page"] and video_url:
        lines.append(f"\n🌐 <b>Video Page:</b>\n🔗 <code>{video_url}</code>")

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
            lines.append(f"\n🍿 <b>Streaming Link:</b>\n🔗 <code>{video_url}</code>")

    return "\n".join(lines)


def search_livecam_models(query: str, limit: int = 10) -> list[dict]:
    """Search LiveCamRips for models matching the given query."""
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


class LiveCamEngine(BaseEngine):
    """LiveCam Engine (LiveCamRips)."""
    name: str = "LiveCam"
    domains: list[str] = ["livecamrips.to"]

    def is_listing_url(self, url: str) -> bool:
        return is_livecam_model_url(url)

    def is_detail_url(self, url: str) -> bool:
        return is_livecam_video_url(url)

    def get_details(self, url: str) -> dict:
        return get_livecam_video_details(url)

    def get_listing_items(self, url: str, **kwargs) -> list[dict]:
        return get_livecam_model_videos(url, **kwargs)

    def search(self, query: str, limit: int = 10, **kwargs) -> list[dict]:
        return search_livecam_models(query, limit=limit)
