# messages.py
"""
Text Templates and Status Message Generators for FileScrapper.
Centralizes all static command instructions (/start, /help, /domains, /channels),
status banners, error messages, and prompt text cards for Telegram.
All wording, instructions, and emoji layouts can be edited here without touching business logic.
"""

import html


# --- Static Command Message Templates ---

def get_welcome_message(user_name: str, bot_name: str = "FileScrapper") -> str:
    """Generate the /start welcome message."""
    u_esc = html.escape(user_name or "Friend")
    b_esc = html.escape(bot_name)
    return (
        f"✨ <b>Welcome, {u_esc}!</b>\n\n"
        f"<b>{b_esc}</b> automatically extracts verified video streaming links "
        "and monitors new forum and cam uploads in real-time.\n\n"
        "<b>⚡ Quick Commands:</b>\n"
        "• <code>/today</code> — Today's fresh uploads (DropMMS & LiveCamRips)\n"
        "• <code>/today 4</code> — Get first 4 uploads of today\n"
        "• <code>/today 1-5</code> — Get uploads 1 to 5\n"
        "• <code>/today last 5</code> — Get last 5 uploads\n"
        "• <code>/latest</code> — Latest forum releases\n"
        "• <code>/sethost</code> — Set preferred video player (Streamtape/Vidara/etc.)\n"
        "• <code>/setlink</code> — LiveCam link format (Streaming/Both/Page)\n"
        "• <code>/search &lt;name&gt;</code> — Find videos or models\n"
        "• <code>/scrape &lt;url&gt;</code> — Extract any topic, category, or model\n"
        "• <code>/stop</code> — Immediately cancel active extraction\n"
        "• <code>/channels</code> — Manage auto-feed broadcast channels\n\n"
        "<i>💡 Or paste any DropMMS or LiveCamRips link directly in chat to extract instantly.</i>"
    )


def get_help_message() -> str:
    """Generate the /help user manual."""
    return (
        "📖 <b>Bot User Manual</b>\n\n"
        "<b>1️⃣ Instant Extraction:</b>\n"
        "Send any post, model, or category link directly in chat, or use:\n"
        "• <code>/scrape https://dropmms.com/topic/123-title/</code>\n"
        "• <code>/scrape https://livecamrips.to/model/36773/GoddessAnna 4</code>\n"
        "• <code>/scrape https://livecamrips.to/video/16877744</code>\n\n"
        "<b>2️⃣ Date-Wise & Sliced Updates:</b>\n"
        "• <code>/today</code> — View all uploads from today\n"
        "• <code>/today 4</code> — First 4 uploads from today\n"
        "• <code>/today 1-5</code> — Uploads 1 through 5\n"
        "• <code>/today last 5</code> — Last 5 uploads\n"
        "• <code>/latest</code> — Top 5 newest topics\n\n"
        "<b>3️⃣ Keyword Search:</b>\n"
        "• <code>/search</code> — Universal search with interactive buttons\n"
        "• <code>/search GoddessAnna</code> — Search models or topics directly\n\n"
        "<b>4️⃣ Preferences:</b>\n"
        "• <code>/sethost</code> — Set preferred streaming player (Streamtape, etc.)\n"
        "• <code>/setlink</code> — Choose LiveCam card links (streaming only / both / page only)\n\n"
        "<b>5️⃣ 24/7 Channel Auto-Poster:</b>\n"
        "1. Add this bot to your Telegram Channel as <b>Administrator</b>.\n"
        "2. The bot will automatically link the channel and broadcast new drops every 15 minutes!\n"
        "3. Or use <code>/setchannel &lt;category_url&gt;</code> inside the channel."
    )


def get_domains_message(domains: list[str]) -> str:
    """Generate the /domains supported platforms list."""
    lines = ["🌐 <b>Supported Platforms & Websites:</b>\n"]
    for d in sorted(domains):
        lines.append(f"• <code>{html.escape(d)}</code>")
    lines.append("\n<i>Paste any link from these domains directly in chat to extract instantly.</i>")
    return "\n".join(lines)


def get_channel_help_message() -> str:
    """Generate instructions for setting up auto-feed in channels."""
    return (
        "📢 <b>Channel Auto-Feed Configuration:</b>\n\n"
        "To broadcast new releases automatically:\n"
        "1. Add this bot as an <b>Administrator</b> in your Telegram Channel.\n"
        "2. Send <code>/setchannel &lt;category_or_forum_url&gt;</code> directly inside the channel.\n"
        "3. The bot will check every 15 minutes and publish newly posted drops automatically!\n\n"
        "Use <code>/channels</code> in private chat to manage all registered broadcast feeds."
    )


# --- Dynamic Status, Progress & Completion Messages ---

def msg_scanning_today() -> str:
    """Banner displayed when initiating a date-based /today scan."""
    return "📅 <i>Scanning today's uploads...</i>"


def msg_extracting_streaming_link(source_label: str = "topic") -> str:
    """Banner displayed while parsing links from a single page."""
    return f"🔍 <i>Extracting streaming links from {html.escape(source_label)}...</i>"


def msg_fetching_latest_releases() -> str:
    """Banner displayed when loading latest forum topics."""
    return "⚡ <i>Fetching latest forum releases...</i>"


def msg_scrape_started(found_count: int, item_type: str = "upload") -> str:
    """Status card when items are found and extraction begins."""
    return f"📅 <b>Found {found_count} {html.escape(item_type)}(s)!</b>\n<i>Extracting links...</i>"


def msg_scrape_stopped(delivered_count: int, total_count: int, item_type: str = "post") -> str:
    """Notice when an active scrape is aborted via /stop or button."""
    return f"🛑 <b>Scrape stopped!</b> Delivered {delivered_count}/{total_count} {html.escape(item_type)}s."


def msg_extraction_complete(delivered_count: int, item_type: str = "topic") -> str:
    """Standardized completion banner."""
    return (
        "<blockquote>"
        "✅ <b>Extraction Complete!</b>\n"
        f"📁 Delivered: <b>{delivered_count}</b> {html.escape(item_type)}(s)"
        "</blockquote>"
    )


def msg_no_uploads_today(target_url: str = "", item_type: str = "model") -> str:
    """Notification when no posts occurred today, with tips on how to fetch recent posts."""
    u_esc = html.escape(target_url)
    return (
        f"📅 <b>No uploads found today for this {html.escape(item_type)}!</b>\n\n"
        "<i>Older items were skipped. Tip: Specify a count or range to view recent uploads:</i>\n"
        f"<code>/today {u_esc} 4</code>\n"
        f"<code>/scrape {u_esc} 1-5</code>"
    )


def msg_no_items_found(message: str = "No topics found in this category.") -> str:
    """Notification when zero items match a search or category."""
    return f"❌ {html.escape(message)}"


def msg_search_prompt(platform_label: str, example_query: str) -> str:
    """Prompt asking user to send a keyword in chat."""
    return (
        "<blockquote>"
        f"🔍 <b>Searching:</b> {html.escape(platform_label)}\n\n"
        f"✏️ <i>Please send the keyword or title in your next message (e.g. <code>{html.escape(example_query)}</code>):</i>"
        "</blockquote>"
    )


def msg_universal_search_prompt() -> str:
    """Prompt for /search with no arguments."""
    return (
        "<blockquote>"
        "🔍 <b>Universal Search Engine</b>\n\n"
        "Select which platform you would like to explore or search, or type a keyword directly in chat:"
        "</blockquote>"
    )


def msg_search_query_prompt(query: str) -> str:
    """Prompt for /search with query argument."""
    return (
        f"🔍 <b>Search Query:</b> <code>{html.escape(query)}</code>\n\n"
        "Choose a platform to search:"
    )


def msg_mmsvibex_video_prompt(card_title: str) -> str:
    """Prompt asking user to choose between Normal Mode and Advance Mode."""
    return (
        "<blockquote>"
        "⚡ <b>MMSVibex Video Detected</b>\n"
        f"🎬 <b>{html.escape(card_title)}</b>\n\n"
        "📁 <b>Multi-Part Series Collection Available!</b>\n\n"
        "Select Extraction Mode:\n"
        "• <b>Normal Mode:</b> Single video card + <i>Extract All Parts</i> button\n"
        "• <b>Advance Mode:</b> Automatically extract all parts of this collection"
        "</blockquote>"
    )


def msg_chat_busy() -> str:
    """Alert when another scrape is running in the same chat."""
    return (
        "⚠️ <b>Another extraction is already active in this chat!</b>\n\n"
        "Please wait for it to finish, or tap <code>/stop</code> to abort it."
    )


def msg_error(error_text: str) -> str:
    """Standardized error notification."""
    return f"❌ <b>Error:</b> {html.escape(str(error_text))}"


def msg_invalid_range_format() -> str:
    """Alert when custom range text cannot be parsed."""
    return "⚠️ <b>Invalid range format!</b> Please send a valid number or range (e.g. <code>5</code> or <code>1-10</code>)."
