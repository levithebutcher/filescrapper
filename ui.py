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

    # Title and Metadata enclosed together in blockquote for a unified, clean aesthetic
    quote_parts = [f"{emoji} <b>{title}</b>"]
    if meta_parts:
        quote_parts.append("  •  ".join(meta_parts))
    caption_lines = ["<blockquote>" + "\n".join(quote_parts) + "</blockquote>"]

    # Tags - Compact code pills
    if tags:
        tag_str = " ".join([f"<code>#{html.escape(t.lstrip('#'))}</code>" for t in tags[:5]])
        caption_lines.append(f"🏷️ {tag_str}")

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


def format_category_options_card(
    cat_title: str,
    total_str: str = "Available",
    sort_val: str = "start_date",
) -> str:
    """Format the forum category options prompt card (Screenshot 3)."""
    sort_label = "Upload Date (Start Date)" if sort_val == "start_date" else "Recently Updated"
    return (
        "<blockquote>"
        f"💬 <b>{html.escape(cat_title)}</b>\n"
        f"📊 <b>Total Topics:</b> {html.escape(str(total_str))}\n"
        f"🎯 <b>Sort:</b> {sort_label}\n\n"
        "⚡ <b>Quick Filter by Date (IST):</b>\n"
        "Tap a button below for instant extraction.\n\n"
        "✏️ <b>Or Enter Custom Range, Count or Page:</b>\n"
        "• <code>10</code> ➔ First 10 topics\n"
        "• <code>1-10</code> ➔ Topics 1 to 10\n"
        "• <code>10-20</code> ➔ Topics 10 to 20\n"
        "• <code>page 2</code> ➔ Full Page 2 (25 topics)\n"
        "• <code>today</code> ➔ Today's uploads\n"
        "• <code>yesterday</code> ➔ Yesterday & Today"
        "</blockquote>"
    )


def format_category_completion_card(
    delivered_count: int,
    cat_title: str,
    total_str: str = "Available",
    sort_val: str = "start_date",
    stopped: bool = False,
) -> str:
    """
    Format extraction completion combined with the category options card at the bottom.
    Allows user to immediately request more posts or navigate without scrolling back up.
    """
    sort_label = "Upload Date (Start Date)" if sort_val == "start_date" else "Recently Updated"
    status_header = (
        f"🛑 <b>Scraping stopped!</b> Delivered: <b>{delivered_count}</b> topic(s)"
        if stopped
        else f"✅ <b>Extraction Complete!</b>\n📁 Delivered: <b>{delivered_count}</b> topic(s)"
    )
    return (
        f"<blockquote>{status_header}</blockquote>\n\n"
        "<blockquote>"
        f"💬 <b>{html.escape(cat_title)}</b>\n"
        f"📊 <b>Total Topics:</b> {html.escape(str(total_str))}\n"
        f"🎯 <b>Sort:</b> {sort_label}\n\n"
        "⚡ <b>Quick Filter by Date (IST):</b>\n"
        "Tap a button below for instant extraction.\n\n"
        "✏️ <b>Or Enter Custom Range, Count or Page:</b>\n"
        "• <code>10</code> ➔ First 10 topics\n"
        "• <code>1-10</code> ➔ Topics 1 to 10\n"
        "• <code>10-20</code> ➔ Topics 10 to 20\n"
        "• <code>page 2</code> ➔ Full Page 2 (25 topics)\n"
        "• <code>today</code> ➔ Today's uploads\n"
        "• <code>yesterday</code> ➔ Yesterday & Today"
        "</blockquote>"
    )


def format_clean_search_results_page(
    query: str,
    scope_name: str,
    page: int,
    total_pages: int,
    total_count: int,
    items: list[dict],
    delivered_indices: set[int] | None = None,
) -> str:
    """
    Format clean, readable text search results with numbers 1 to 10.
    Zero buttons clutter: user can extract by typing any number in chat.
    """
    delivered_indices = delivered_indices or set()
    lines = [
        "<blockquote>"
        f"🔎 <b>{html.escape(scope_name)} Search Results</b>\n"
        f"🎯 <b>Query:</b> <code>{html.escape(query)}</code>\n"
        f"📊 <b>Total:</b> Found <b>{total_count}</b> Topics (Page {page}/{total_pages})\n"
        "🕒 <b>Sort:</b> Newest Uploads (Date Wise)"
        "</blockquote>\n"
    ]

    for idx, itm in enumerate(items, start=1):
        t_esc = html.escape(itm.get("title") or "Untitled Topic")
        badge = " ✅ <i>(Delivered)</i>" if idx in delivered_indices else ""
        date_str = itm.get("date_ist") or itm.get("date") or ""
        meta_sub = f" <i>({html.escape(str(date_str))})</i>" if date_str else ""
        lines.append(f"<b>{idx}.</b> {t_esc}{meta_sub}{badge}")

    lines.append(
        "\n<blockquote>"
        "💡 <b>How to Extract:</b>\n"
        "Reply with any number (e.g. <code>1</code>, <code>2</code>, <code>1-3</code>, or <code>all</code>) to get the post!"
        "</blockquote>"
    )
    return "\n".join(lines)


def format_search_completion_card(
    delivered_summary: str,
    query: str,
    scope_name: str,
    page: int,
    total_pages: int,
    total_count: int,
    items: list[dict],
    delivered_indices: set[int] | None = None,
) -> str:
    """Format post-delivery confirmation combined with the search results list at the bottom."""
    delivered_indices = delivered_indices or set()
    lines = [
        f"<blockquote>✅ <b>Delivered:</b> {html.escape(delivered_summary)}</blockquote>\n\n"
        "<blockquote>"
        f"🔎 <b>{html.escape(scope_name)} Results:</b> '<code>{html.escape(query)}</code>' (Page {page}/{total_pages})"
        "</blockquote>\n"
    ]

    for idx, itm in enumerate(items, start=1):
        t_esc = html.escape(itm.get("title") or "Untitled Topic")
        badge = " ✅ <i>(Delivered)</i>" if idx in delivered_indices else ""
        date_str = itm.get("date_ist") or itm.get("date") or ""
        meta_sub = f" <i>({html.escape(str(date_str))})</i>" if date_str else ""
        lines.append(f"<b>{idx}.</b> {t_esc}{meta_sub}{badge}")

    lines.append(
        "\n<blockquote>"
        "💡 Type another number (e.g. <code>5</code>) or tap <b>Next ➡️</b> to see more!"
        "</blockquote>"
    )
    return "\n".join(lines)


def parse_search_selection(text: str, total_items: int) -> list[int]:
    """
    Parse user selection from numbered search list (e.g. '1', '2', '1-3', 'all', '1, 3').
    Returns 1-based indices within range [1, total_items].
    """
    clean = text.strip().lower()
    if not clean:
        return []
    if clean in ("all", "sab", "saare"):
        return list(range(1, total_items + 1))

    m_range = re.match(r"^(\d+)\s*(?:-|to)\s*(\d+)$", clean)
    if m_range:
        start, end = int(m_range.group(1)), int(m_range.group(2))
        return [i for i in range(min(start, end), max(start, end) + 1) if 1 <= i <= total_items]

    parts = re.split(r"[, ]+", clean)
    indices = []
    for p in parts:
        if p.isdigit():
            val = int(p)
            if 1 <= val <= total_items and val not in indices:
                indices.append(val)
    return indices




