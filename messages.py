# messages.py
"""
Text Templates and Status Message Generators for FileScrapper.
Centralizes all static command instructions (/start, /help, /domains, /channels),
status banners, error messages, and prompt text cards for Telegram.
Designed for a premium, minimal, and clean user experience.
"""

import html


# --- Static Command Message Templates ---

def get_welcome_message(user_name: str, bot_name: str = "FileScrapper") -> str:
    """Generate the sleek, minimal /start welcome card."""
    u_esc = html.escape(user_name or "Friend")
    b_esc = html.escape(bot_name)
    return (
        f"<blockquote>⚡ <b>{b_esc}</b> • <i>Media Scraper & Stream Extractor</i></blockquote>\n"
        f"✨ <b>Welcome, {u_esc}!</b>\n\n"
        "Extract verified streaming links, scrape forums & monitor feeds in real-time.\n\n"
        "<b>⚡ Quick Commands:</b>\n"
        "• <code>/today [N]</code> — Today's fresh uploads (DropMMS & LiveCam)\n"
        "• <code>/latest</code> — Latest forum releases\n"
        "• <code>/search &lt;query&gt;</code> — Search topics, models or videos\n"
        "• <code>/scrape &lt;url&gt;</code> — Extract any topic or category\n"
        "• <code>/sethost</code> — Set preferred video player\n"
        "• <code>/channels</code> — 24/7 Channel auto-broadcast\n\n"
        "<blockquote>💡 <i>Tip: Paste any supported link directly in chat to extract instantly.</i></blockquote>"
    )


def get_help_message() -> str:
    """Generate the clean, organized /help user guide."""
    return (
        "<blockquote>📖 <b>FileScrapper User Manual</b></blockquote>\n\n"
        "<b>1️⃣ Instant Extraction</b>\n"
        "Simply send any supported link in chat, or use:\n"
        "• <code>/scrape &lt;post_or_model_url&gt;</code>\n"
        "• <code>/scrape &lt;url&gt; 5</code> (first 5 items)\n"
        "• <code>/scrape &lt;url&gt; 1-10</code> (custom range)\n\n"
        "<b>2️⃣ Date & Range Slices</b>\n"
        "• <code>/today</code> — All uploads from today\n"
        "• <code>/today 4</code> — First 4 uploads from today\n"
        "• <code>/today last 5</code> — Last 5 uploads\n"
        "• <code>/latest</code> — Top 5 newest topics\n\n"
        "<b>3️⃣ Interactive Search</b>\n"
        "• <code>/search</code> — Open interactive platform picker\n"
        "• <code>/search &lt;keyword&gt;</code> — Instant multi-platform search\n\n"
        "<b>4️⃣ Preferences</b>\n"
        "• <code>/sethost</code> — Set preferred streaming player (Streamtape, Vidara, etc.)\n"
        "• <code>/setlink</code> — LiveCam link format (Streaming / Both / Page)\n\n"
        "<b>5️⃣ 24/7 Channel Auto-Poster</b>\n"
        "1. Add bot to your Telegram Channel as <b>Admin</b>.\n"
        "2. Send <code>/setchannel &lt;url&gt;</code> inside the channel.\n"
        "3. The bot will broadcast newly posted items automatically every 15 mins!"
    )


def get_domains_message(domains: list[str]) -> str:
    """Generate the supported platforms listing card."""
    lines = ["<blockquote>🌐 <b>Supported Platforms & Domains</b></blockquote>\n"]
    for d in sorted(domains):
        lines.append(f"• <code>{html.escape(d)}</code>")
    lines.append("\n<i>💡 Paste any link from these domains directly in chat to extract instantly.</i>")
    return "\n".join(lines)


def get_channel_help_message() -> str:
    """Generate clean instructions for setting up auto-feed in broadcast channels."""
    return (
        "<blockquote>📢 <b>Channel Auto-Feed Setup</b></blockquote>\n\n"
        "To broadcast new releases automatically:\n"
        "1. Add this bot as an <b>Administrator</b> in your Telegram Channel.\n"
        "2. Send <code>/setchannel &lt;category_url&gt;</code> directly inside the channel.\n"
        "3. New drops will be published automatically every 15 minutes!\n\n"
        "<i>Use <code>/channels</code> in private chat to manage active feeds.</i>"
    )


# --- Dynamic Status, Progress & Completion Messages ---

def msg_scanning_today() -> str:
    """Banner displayed when initiating a date-based /today scan."""
    return "<blockquote>📅 <b>Scanning today's uploads...</b></blockquote>"


def msg_extracting_streaming_link(source_label: str = "topic") -> str:
    """Banner displayed while parsing links from a single page."""
    return f"<blockquote>🔍 <b>Extracting streaming links from {html.escape(source_label)}...</b></blockquote>"


def msg_fetching_latest_releases() -> str:
    """Banner displayed when loading latest forum topics."""
    return "<blockquote>⚡ <b>Fetching latest forum releases...</b></blockquote>"


def msg_scrape_started(found_count: int, item_type: str = "upload") -> str:
    """Status card when items are found and extraction begins."""
    return f"<blockquote>🚀 <b>Found {found_count} {html.escape(item_type)}(s)</b>\n<i>Extracting streaming links...</i></blockquote>"


def msg_scrape_stopped(delivered_count: int, total_count: int, item_type: str = "post") -> str:
    """Notice when an active scrape is aborted via /stop or button."""
    return f"<blockquote>🛑 <b>Extraction Stopped!</b>\nDelivered {delivered_count}/{total_count} {html.escape(item_type)}s.</blockquote>"


def msg_extraction_complete(delivered_count: int, item_type: str = "topic") -> str:
    """Standardized completion banner."""
    return (
        "<blockquote>"
        "✅ <b>Extraction Complete!</b>\n"
        f"Delivered: <b>{delivered_count}</b> {html.escape(item_type)}(s)"
        "</blockquote>"
    )


def msg_no_uploads_today(target_url: str = "", item_type: str = "model") -> str:
    """Notification when no posts occurred today, with tips on how to fetch recent posts."""
    u_esc = html.escape(target_url)
    return (
        f"<blockquote>📅 <b>No uploads found today for this {html.escape(item_type)}!</b></blockquote>\n\n"
        "<i>Tip: Specify a count or range to view recent uploads:</i>\n"
        f"• <code>/today {u_esc} 4</code>\n"
        f"• <code>/scrape {u_esc} 1-5</code>"
    )


def msg_no_items_found(message: str = "No topics found in this category.") -> str:
    """Notification when zero items match a search or category."""
    return f"<blockquote>❌ {html.escape(message)}</blockquote>"


def msg_search_prompt(platform_label: str, example_query: str) -> str:
    """Prompt asking user to send a keyword in chat."""
    return (
        "<blockquote>"
        f"🔍 <b>Searching:</b> {html.escape(platform_label)}\n\n"
        f"✏️ Send keyword or title in your next message (e.g. <code>{html.escape(example_query)}</code>):"
        "</blockquote>"
    )


def msg_universal_search_prompt() -> str:
    """Prompt for /search with no arguments."""
    return (
        "<blockquote>"
        "🔍 <b>Universal Search Engine</b>\n\n"
        "Select a platform below or send a search keyword directly in chat:"
        "</blockquote>"
    )


def msg_search_query_prompt(query: str) -> str:
    """Prompt for /search with query argument."""
    return (
        "<blockquote>"
        f"🔍 <b>Search Query:</b> <code>{html.escape(query)}</code>\n\n"
        "Choose a platform to search:"
        "</blockquote>"
    )


def msg_mmsvibex_video_prompt(card_title: str) -> str:
    """Prompt asking user to choose between Normal Mode and Advance Mode."""
    return (
        "<blockquote>"
        "⚡ <b>MMSVibex Multi-Part Series</b>\n"
        f"🎬 <b>{html.escape(card_title)}</b>\n\n"
        "Select Extraction Mode:\n"
        "• <b>Normal Mode:</b> Single video card + <i>Extract All Parts</i> button\n"
        "• <b>Advance Mode:</b> Automatically extract all parts of this collection"
        "</blockquote>"
    )


def msg_chat_busy() -> str:
    """Alert when another scrape is running in the same chat."""
    return (
        "<blockquote>"
        "⚠️ <b>Extraction in Progress</b>\n\n"
        "Another extraction is active in this chat. Please wait or tap <code>/stop</code>."
        "</blockquote>"
    )


def msg_error(error_text: str) -> str:
    """Standardized error notification."""
    return f"<blockquote>❌ <b>Error:</b> {html.escape(str(error_text))}</blockquote>"


def msg_invalid_range_format() -> str:
    """Alert when custom range text cannot be parsed."""
    return "<blockquote>⚠️ <b>Invalid Range:</b> Send a valid number or range (e.g. <code>5</code> or <code>1-10</code>).</blockquote>"
