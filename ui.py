# ui.py
"""
UI and Visual Formatters for FileScrapper.
Responsible for building all user-facing message strings, post cards, tags,
streaming link sections, search result listings, and metadata lines for Telegram.
All card structures, emojis, and layouts can be edited here without touching business logic.
"""

import html
import re
from engines.base import (
    PROVIDER_PRIORITY,
    get_host_display_name,
    get_host_key,
    filter_links_by_preference,
)


def group_links_by_host(links: list[str]) -> dict[str, list[str]]:
    """Group streaming links by provider badge name, sorted by PROVIDER_PRIORITY."""
    grouped = {}
    host_keys = {}
    for link in links:
        badge = get_host_display_name(link)
        h_key = get_host_key(link)
        if badge not in grouped:
            grouped[badge] = []
            host_keys[badge] = h_key
        if link not in grouped[badge]:
            grouped[badge].append(link)

    def sort_order(item):
        badge = item[0]
        h_key = host_keys.get(badge, "")
        try:
            return PROVIDER_PRIORITY.index(h_key)
        except ValueError:
            return 999

    return dict(sorted(grouped.items(), key=sort_order))


def format_post_card(details: dict, user_pref: str = "streamtape") -> str:
    """
    Universal Post Card Formatter.
    Formats post details into a clean, modern card with rich metadata badges,
    tags, preferred streaming links, albums/series, and origin links.
    """
    title = html.escape(details.get("title", "Untitled Video"))
    post_url = html.escape(details.get("post_url", ""))
    tags = details.get("tags", [])
    raw_links = details.get("streaming_links", [])

    # Dynamic emoji header based on content type
    s_low = str(details.get("site") or "").lower()
    p_low = str(details.get("platform_name") or details.get("platform") or "").lower()
    if s_low == "livecam" or "livecam" in p_low:
        emoji = "📹"
    elif "photo" in title.lower() or "album" in title.lower() or details.get("is_photo"):
        emoji = "📸"
    else:
        emoji = "🎬"

    caption_lines = [f"<blockquote>{emoji} <b>{title}</b></blockquote>"]

    # Tags - Compact code pills
    if tags:
        tag_str = " ".join([f"<code>#{html.escape(t.lstrip('#'))}</code>" for t in tags[:5]])
        caption_lines.append(f"🏷️ {tag_str}")

    # Metadata Line: Date • Platform • Category • Duration
    meta_parts = []
    date_display = details.get("date_ist") or details.get("date")
    if date_display:
        meta_parts.append(f"📅 <b>Date:</b> {html.escape(str(date_display))}")

    platform_name = details.get("platform_name") or details.get("platform")
    if not platform_name:
        u_low = post_url.lower()
        if "mmsvibex" in s_low or "mmsvibex" in u_low:
            platform_name = "MMSVibex"
        elif "livecam" in s_low or "livecamrips" in u_low:
            platform_name = "LiveCamRips"
        elif "dropmms" in u_low:
            platform_name = "DropMMS"
        elif "mmstown" in u_low:
            platform_name = "MMSTown"
        elif "omaal63" in u_low:
            platform_name = "Omaal63"
        elif "desijugar" in u_low:
            platform_name = "DesiJugar"
        elif "gulabihub" in u_low:
            platform_name = "GulabiHub"
        elif s_low == "wp_locker":
            platform_name = "WordPress"
        elif s_low == "invision":
            platform_name = "Invision Community"

    if platform_name:
        meta_parts.append(f"🏛️ <b>Platform:</b> {html.escape(platform_name)}")

    category = details.get("category_name") or details.get("category")
    if category:
        meta_parts.append(f"📁 <b>Category:</b> {html.escape(str(category))}")

    duration = details.get("duration")
    if duration:
        meta_parts.append(f"⏱️ <b>Duration:</b> {html.escape(str(duration))}")

    if meta_parts:
        caption_lines.append("  •  ".join(meta_parts))

    # Streaming Links Section
    if not raw_links:
        caption_lines.append("\n⚠️ <i>No direct streaming links found in this post.</i>")
    elif user_pref == "all":
        # Group and show all providers cleanly
        grouped = group_links_by_host(raw_links)
        caption_lines.append("\n🍿 <b>Streaming Links (All Hosts):</b>")
        for host_badge, h_links in grouped.items():
            caption_lines.append(f"\n{host_badge}:")
            for i, l in enumerate(h_links, 1):
                caption_lines.append(f"{i}. <code>{html.escape(l)}</code>")
    else:
        # Filter by preference with smart fallback following PROVIDER_PRIORITY
        host_badge, filtered_links, is_fallback = filter_links_by_preference(raw_links, user_pref)

        if is_fallback:
            caption_lines.append(f"\n⚠️ <i>{user_pref.capitalize()} not available in this post.</i>")
            caption_lines.append(f"🍿 <b>Using alternative ({host_badge}):</b>")
        else:
            caption_lines.append(f"\n🍿 <b>{host_badge} Links:</b>")

        if len(filtered_links) == 1:
            caption_lines.append(f"🔗 <code>{html.escape(filtered_links[0])}</code>")
        else:
            for i, l in enumerate(filtered_links, 1):
                caption_lines.append(f"{i}. <code>{html.escape(l)}</code>")

    # Attached Photo Albums
    photo_albums = details.get("attached_photo_albums")
    if photo_albums:
        caption_lines.append("\n📸 <b>Attached Photo Albums:</b>")
        for idx, alb in enumerate(photo_albums, 1):
            alb_title = html.escape(alb.get("title", f"Album {idx}"))
            alb_url = alb.get("url", "")
            caption_lines.append(f"{idx}. <a href='{alb_url}'>{alb_title}</a>")
    elif details.get("attached_album_url"):
        caption_lines.append(f"\n📸 <a href='{details['attached_album_url']}'>Attached Photo Album</a>")

    if details.get("collection_url") and not details.get("hide_collection_link"):
        col_name = html.escape(details.get("collection_name") or "All Parts Collection")
        caption_lines.append(f"\n📁 <b>Series Collection:</b> <a href='{details['collection_url']}'>{col_name}</a>")

    # Post URL - Only for forums and WP lockers, NEVER for MMSVibex videos
    if post_url and details.get("site") != "mmsvibex":
        site_type = details.get("site")
        if site_type == "wp_locker":
            link_title = "Original Post"
        elif site_type == "livecam":
            link_title = "Original Video Page"
        else:
            link_title = "Original Forum Thread"
        caption_lines.append(f"\n🌐 <a href='{post_url}'>{link_title}</a>")

    return "\n".join(caption_lines)


def format_search_results_page(
    items: list[dict],
    page: int,
    total_pages: int,
    total_count: int,
    platform_label: str,
    query: str,
) -> str:
    """Format paginated search results listing text with header blockquote and sleek numbered entries."""
    q_esc = html.escape(query)
    plat_esc = html.escape(platform_label)
    header = (
        "<blockquote>"
        f"🔍 <b>Results:</b> <code>{q_esc}</code>\n"
        f"🏛️ <b>Platform:</b> {plat_esc}  •  <b>{total_count}</b> found  •  Page <b>{page}/{total_pages}</b>"
        "</blockquote>\n"
    )

    if not items:
        return header + "<i>No matches found on this page.</i>"

    lines = [header]
    for idx, itm in enumerate(items, start=1):
        t_esc = html.escape(itm.get("title") or itm.get("model_name") or "Video")
        meta_info = []
        if itm.get("date_ist") or itm.get("date"):
            meta_info.append(str(itm.get("date_ist") or itm.get("date")))
        if itm.get("duration"):
            meta_info.append(str(itm.get("duration")))

        line = f"<b>{idx}.</b> {t_esc}"
        if meta_info:
            line += f"  <i>( {' • '.join(meta_info)} )</i>"
        lines.append(line)

    return "\n".join(lines)


def format_listing_menu_card(
    title: str,
    total_items: int = 0,
    is_category: bool = True,
    extra_tips: str = "",
) -> str:
    """Format category or model listing prompt card text."""
    t_esc = html.escape(title)
    icon = "📁" if is_category else "📹"
    lines = [
        "<blockquote>",
        f"{icon} <b>{t_esc}</b>",
    ]
    if total_items > 0:
        lines.append(f"📊 Available items: <b>{total_items}</b>")
    lines.append("Select extraction count or reply with custom range (e.g. <code>1-15</code>):")
    if extra_tips:
        lines.append(f"\n💡 {extra_tips}")
    lines.append("</blockquote>")
    return "\n".join(lines)
