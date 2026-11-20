# bot.py

import sys
import html
import time
import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMember,
    ChatMemberUpdated,
)
from telegram.constants import ChatMemberStatus, ChatType, ParseMode
from telegram.error import RetryAfter, BadRequest, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)

from config import (
    BOT_NAME,
    BOT_VERSION,
    REPO_URL,
    BOT_TOKEN,
    POST_SEND_DELAY,
    STREAMING_DOMAINS,
    MAX_POSTS_PER_FORUM,
    REQUEST_TIMEOUT,
    BASE_URL,
    DEFAULT_CATEGORY_URL,
    FEED_CHECK_INTERVAL,
    OWNER_ID,
)
from scraper import (
    get_forum_topics,
    get_post_details,
    search_forum,
    is_forum_url,
    is_topic_url,
    get_host_display_name,
)
import db

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Initialize database
db.init_db()


# --- UI & Formatters ---

def group_links_by_host(links: list[str]) -> dict[str, list[str]]:
    """Group streaming links by provider badge name."""
    grouped = {}
    for link in links:
        badge = get_host_display_name(link)
        if badge not in grouped:
            grouped[badge] = []
        if link not in grouped[badge]:
            grouped[badge].append(link)
    return grouped


def format_post_card(details: dict) -> tuple[str, InlineKeyboardMarkup | None]:
    """
    Format single post details into a clean, 1-tap copyable text card.
    Uses multi-line <pre><code> boxes so users can tap any provider box
    to copy all links for that specific host at once (or all links at once).
    """
    title = html.escape(details.get("title", "Untitled Video"))
    post_url = html.escape(details.get("post_url", ""))
    tags = details.get("tags", [])
    links = details.get("streaming_links", [])

    caption_lines = [f"🎬 <b>{title}</b>"]

    if tags:
        tag_str = " ".join([f"<code>#{html.escape(t)}</code>" for t in tags[:5]])
        caption_lines.append(f"🏷️ {tag_str}")

    if post_url:
        caption_lines.append(f"🌐 <a href='{post_url}'>View Forum Thread</a>")

    if not links:
        caption_lines.append("\n⚠️ <i>No direct streaming links found in this post.</i>")
    else:
        grouped = group_links_by_host(links)
        caption_lines.append("\n🍿 <b>Streaming Links (Tap box to copy):</b>")

        for host_badge, host_links in grouped.items():
            count_label = f" ({len(host_links)})" if len(host_links) > 1 else ""
            caption_lines.append(f"\n{host_badge}{count_label}:")
            escaped_links = "\n".join([html.escape(l) for l in host_links])
            caption_lines.append(f"<pre><code>{escaped_links}</code></pre>")

        # Master Batch Copy block (if multiple providers or multiple links)
        if len(grouped) > 1 or len(links) > 1:
            caption_lines.append("\n📋 <b>All Links (Batch Copy All):</b>")
            all_escaped = "\n".join([html.escape(l) for l in links])
            caption_lines.append(f"<pre><code>{all_escaped}</code></pre>")

    caption = "\n".join(caption_lines)
    return caption, None


# --- Post Sender Engine ---

async def send_post_card(bot, chat_id: int | str, details: dict):
    """Deliver a premium post card with thumbnail and copyable link blocks."""
    caption, markup = format_post_card(details)
    thumbnail = details.get("thumbnail")

    # If thumbnail exists and caption fits within photo caption limit (1024 chars)
    if thumbnail and len(caption) <= 1024:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=thumbnail,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=thumbnail,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Thumbnail send failed: {e}")

    # If caption > 1024 chars but thumbnail exists, send photo first with title, then full link card
    if thumbnail and len(caption) > 1024:
        try:
            short_caption = f"🎬 <b>{html.escape(details.get('title', 'Video'))}</b>"
            await bot.send_photo(
                chat_id=chat_id,
                photo=thumbnail,
                caption=short_caption,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # Send text message card
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"Failed to send post card to {chat_id}: {e}")


# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Minimal, elegant greeting."""
    user_name = update.effective_user.first_name if update.effective_user else "Friend"
    text = (
        f"✨ <b>Welcome, {html.escape(user_name)}!</b>\n\n"
        f"<b>{BOT_NAME}</b> automatically extracts verified video streaming links "
        "and monitors new forum uploads in real-time.\n\n"
        "<b>⚡ Quick Commands:</b>\n"
        "• <code>/today</code> — Today's fresh uploads\n"
        "• <code>/latest</code> — Latest forum releases\n"
        "• <code>/search &lt;name&gt;</code> — Find videos by keyword\n"
        "• <code>/scrape &lt;url&gt;</code> — Extract any topic or category\n"
        "• <code>/channels</code> — Manage auto-feed broadcast channels\n\n"
        "<i>💡 Or paste any forum link directly in chat to extract instantly.</i>"
    )

    buttons = [
        [
            InlineKeyboardButton("📅 Today's Drops", callback_data="cb_today"),
            InlineKeyboardButton("⚡ Latest Posts", callback_data="cb_latest"),
        ],
        [
            InlineKeyboardButton("📢 Channel Setup", callback_data="cb_channel_help"),
            InlineKeyboardButton("🌐 Domains", callback_data="cb_domains"),
        ],
    ]

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clean usage guide."""
    text = (
        "📖 <b>Bot User Manual</b>\n\n"
        "<b>1️⃣ Instant Extraction:</b>\n"
        "Send any post or category link directly in chat, or use:\n"
        "<code>/scrape https://dropmms.com/topic/123-title/</code>\n\n"
        "<b>2️⃣ Date-Wise Updates:</b>\n"
        "• <code>/today</code> — View uploads from today\n"
        "• <code>/latest</code> — Top 5 newest topics\n\n"
        "<b>3️⃣ Keyword Search:</b>\n"
        "• <code>/search sample video</code>\n\n"
        "<b>4️⃣ 24/7 Channel Auto-Poster:</b>\n"
        "1. Add this bot to your Telegram Channel as <b>Administrator</b>.\n"
        "2. The bot will automatically link the channel and broadcast new drops every 15 minutes!\n"
        "3. Or use <code>/setchannel &lt;category_url&gt;</code> inside the channel."
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch and display today's uploads."""
    msg = update.effective_message
    status_msg = await msg.reply_text("🔍 <i>Fetching today's uploads...</i>", parse_mode=ParseMode.HTML)

    category_url = context.args[0] if (context.args and len(context.args) > 0) else DEFAULT_CATEGORY_URL

    try:
        topics = await asyncio.to_thread(get_forum_topics, category_url, "start_date", 20)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error fetching category: {html.escape(str(e))}")
        return

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_topics = []

    for t in topics:
        t_date = t.get("date")
        # Match today's date prefix YYYY-MM-DD
        if t_date and t_date.startswith(today_str):
            today_topics.append(t)

    # If no strict date match or date missing, show the top 5 freshest topics
    display_topics = today_topics if today_topics else topics[:5]
    date_header = today_str if today_topics else "Latest Today"

    text = f"📅 <b>Uploads Feed ({date_header}):</b>\n\n"
    buttons = []

    for idx, t in enumerate(display_topics, start=1):
        clean_t = html.escape(t["title"])
        text += f"{idx}. <b>{clean_t}</b>\n"
        # Store in URL cache to strictly respect Telegram's 64-byte callback_data limit
        short_id = db.get_or_create_short_id(t["url"])
        btn = InlineKeyboardButton(f"🎬 View #{idx}", callback_data=f"sc_{short_id}")
        buttons.append([btn])

    text += "\n<i>Tap any button below to extract streaming links directly:</i>"

    await status_msg.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
    )


async def latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch latest 5 posts."""
    msg = update.effective_message
    status_msg = await msg.reply_text("⚡ <i>Fetching latest forum releases...</i>", parse_mode=ParseMode.HTML)

    category_url = context.args[0] if (context.args and len(context.args) > 0) else DEFAULT_CATEGORY_URL

    try:
        topics = await asyncio.to_thread(get_forum_topics, category_url, "start_date", 6)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {html.escape(str(e))}")
        return

    if not topics:
        await status_msg.edit_text("❌ No topics found in this category.")
        return

    text = "⚡ <b>Latest Forum Drops:</b>\n\n"
    buttons = []
    for idx, t in enumerate(topics, start=1):
        clean_t = html.escape(t["title"])
        text += f"{idx}. <b>{clean_t}</b>\n"
        short_id = db.get_or_create_short_id(t["url"])
        btn = InlineKeyboardButton(f"🎬 Get Links #{idx}", callback_data=f"sc_{short_id}")
        buttons.append([btn])

    await status_msg.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search the forum by keyword."""
    msg = update.effective_message
    if not context.args:
        await msg.reply_text(
            "ℹ️ <b>Usage:</b> <code>/search &lt;keyword&gt;</code>\n"
            "Example: <code>/search 1080p video</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    query = " ".join(context.args).strip()
    status_msg = await msg.reply_text(f"🔍 <i>Searching for '{html.escape(query)}'...</i>", parse_mode=ParseMode.HTML)

    try:
        results = await asyncio.to_thread(search_forum, query, 5)
    except Exception as e:
        await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
        return

    if not results:
        await status_msg.edit_text(f"❌ No matching videos found for <b>{html.escape(query)}</b>.", parse_mode=ParseMode.HTML)
        return

    text = f"🔎 <b>Search Results for '{html.escape(query)}':</b>\n\n"
    buttons = []
    for idx, r in enumerate(results, start=1):
        text += f"{idx}. <b>{html.escape(r['title'])}</b>\n"
        short_id = db.get_or_create_short_id(r["url"])
        btn = InlineKeyboardButton(f"🎬 Extract #{idx}", callback_data=f"sc_{short_id}")
        buttons.append([btn])

    await status_msg.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def domains_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List supported streaming providers."""
    badges = [get_host_display_name(f"https://{d}/") for d in STREAMING_DOMAINS]
    text = (
        f"🌐 <b>Supported Streaming Providers ({len(STREAMING_DOMAINS)}):</b>\n\n"
        + "\n".join([f"• {b}" for b in badges])
        + "\n\n<i>Direct video links from these providers are automatically captured.</i>"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


# --- Channel & Auto-Feed Management ---

async def setchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Connect a Channel or Supergroup for automatic broadcasts.
    Can be run directly in the channel or in private chat.
    """
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    target_category = context.args[0] if (context.args and len(context.args) > 0) else DEFAULT_CATEGORY_URL

    # Case A: Command run inside a channel or supergroup
    if chat.type in [ChatType.CHANNEL, ChatType.GROUP, ChatType.SUPERGROUP]:
        success = db.add_or_update_channel(
            channel_id=chat.id,
            title=chat.title or "Connected Channel",
            username=chat.username,
            category_url=target_category,
            added_by=user.id if user else None,
        )
        if success:
            await msg.reply_text(
                "✅ <b>Channel Linked Successfully!</b>\n\n"
                f"📢 <b>Channel:</b> {html.escape(chat.title)}\n"
                f"🎯 <b>Monitoring:</b> <code>{html.escape(target_category)}</code>\n"
                "⏱️ <b>Auto-Feed:</b> Active (New drops will post here automatically)",
                parse_mode=ParseMode.HTML,
            )
        return

    # Case B: Command run in private chat: /setchannel <channel_id_or_@username> [category_url]
    if not context.args:
        await msg.reply_text(
            "ℹ️ <b>How to Link a Channel:</b>\n\n"
            "<b>Method 1 (Easiest):</b>\n"
            "Add this bot to your Telegram Channel as <b>Administrator</b> with 'Post Messages' rights. "
            "It will auto-link immediately!\n\n"
            "<b>Method 2:</b>\n"
            "Send this command inside the channel:\n"
            "<code>/setchannel</code>\n\n"
            "<b>Method 3:</b>\n"
            "From this chat, pass the channel username/ID:\n"
            "<code>/setchannel @mychannel https://dropmms.com/forum/2-general/</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    target_channel_id = context.args[0]
    custom_cat = context.args[1] if len(context.args) > 1 else DEFAULT_CATEGORY_URL

    try:
        chat_info = await context.bot.get_chat(target_channel_id)
        db.add_or_update_channel(
            channel_id=chat_info.id,
            title=chat_info.title,
            username=chat_info.username,
            category_url=custom_cat,
            added_by=user.id,
        )
        await msg.reply_text(
            f"✅ <b>Linked to Channel:</b> {html.escape(chat_info.title)}\n"
            f"🎯 <b>Category:</b> <code>{html.escape(custom_cat)}</code>\n"
            "🚀 Auto-feed activated!",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await msg.reply_text(f"❌ Failed to connect channel: {html.escape(str(e))}\nMake sure the bot is an Admin in the channel!")


async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all active auto-feed channels."""
    channels = db.get_all_active_channels()
    if not channels:
        await update.effective_message.reply_text(
            "📢 <b>No active channels linked yet.</b>\n\n"
            "Add the bot as Admin to your channel or use <code>/setchannel</code> to start auto-posting.",
            parse_mode=ParseMode.HTML,
        )
        return

    text = f"📢 <b>Connected Broadcast Channels ({len(channels)}):</b>\n\n"
    buttons = []
    for c in channels:
        title = html.escape(c["title"] or str(c["channel_id"]))
        cat = html.escape(c["category_url"] or DEFAULT_CATEGORY_URL)
        text += f"• <b>{title}</b>\n  └ Category: <code>{cat}</code>\n"
        btn = InlineKeyboardButton(f"❌ Unlink {title}", callback_data=f"unlink_{c['channel_id']}")
        buttons.append([btn])

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def chat_member_updated(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Automatic Channel Linking:
    Triggered when the bot is added as an administrator to any channel.
    """
    result = update.my_chat_member
    if not result:
        return

    chat = result.chat
    new_member = result.new_chat_member

    # When bot is promoted to administrator in a channel or group
    if new_member.status in [ChatMemberStatus.ADMINISTRATOR]:
        db.add_or_update_channel(
            channel_id=chat.id,
            title=chat.title or "Auto Channel",
            username=chat.username,
            category_url=DEFAULT_CATEGORY_URL,
            added_by=result.from_user.id if result.from_user else None,
        )
        logger.info(f"✅ Auto-linked channel: {chat.title} ({chat.id})")

        # Send greeting in channel if we have permission
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    f"🎉 <b>{BOT_NAME} Activated!</b>\n\n"
                    "This channel is now auto-linked. New streaming video releases will automatically be posted here.\n\n"
                    f"🎯 <b>Monitored Category:</b> <code>{html.escape(DEFAULT_CATEGORY_URL)}</code>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"Could not send welcome message to channel: {e}")

    # When bot is removed from channel
    elif new_member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED]:
        db.remove_channel(chat.id)
        logger.info(f"Channel unlinked (bot removed): {chat.title} ({chat.id})")


# --- Background Auto-Feed Engine ---

async def auto_feed_loop(app: Application):
    """
    Background worker: monitors linked channels' categories and broadcasts new drops.
    Runs continuously without requiring external scheduler libraries.
    """
    logger.info("🚀 Background Auto-Feed Engine started.")
    await asyncio.sleep(10)  # Initial grace delay on startup

    while True:
        try:
            channels = db.get_all_active_channels()
            if channels:
                for channel in channels:
                    channel_id = channel["channel_id"]
                    cat_url = channel.get("category_url") or DEFAULT_CATEGORY_URL

                    try:
                        topics = await asyncio.to_thread(get_forum_topics, cat_url, "start_date", 10)
                        # Process oldest unseen first to maintain chronological order
                        for t in reversed(topics):
                            t_url = t["url"]
                            if not db.is_post_seen(t_url):
                                details = await asyncio.to_thread(get_post_details, t_url)
                                await send_post_card(app.bot, channel_id, details)
                                db.mark_post_seen(t_url, details.get("title", ""))
                                await asyncio.sleep(POST_SEND_DELAY)
                    except Exception as err:
                        logger.warning(f"Auto-feed error for channel {channel_id}: {err}")

        except Exception as e:
            logger.error(f"Unexpected error in auto_feed_loop: {e}")

        await asyncio.sleep(FEED_CHECK_INTERVAL)


# --- URL Processing & Button Callback Handlers ---

async def process_topic_scrape(bot, chat_id: int | str, url: str):
    """Scrape and deliver single topic card."""
    try:
        details = await asyncio.to_thread(get_post_details, url)
        await send_post_card(bot, chat_id, details)
    except Exception as e:
        safe_err = html.escape(str(e))
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ <b>Could not extract:</b>\n<code>{html.escape(url)}</code>\n<i>Reason: {safe_err}</i>",
            parse_mode=ParseMode.HTML,
        )


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /scrape <url> command."""
    msg = update.effective_message
    if not context.args:
        await msg.reply_text(
            "ℹ️ <b>Usage:</b> <code>/scrape &lt;url&gt;</code>\n"
            "Example: <code>/scrape https://dropmms.com/topic/123-title/</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    target_url = context.args[0].strip()
    await handle_raw_url(update, context, target_url)


async def handle_raw_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Process URLs pasted directly in chat."""
    msg = update.effective_message
    url = url.strip()

    if not url.startswith("http://") and not url.startswith("https://"):
        return

    if is_topic_url(url):
        status = await msg.reply_text("🔍 <i>Extracting streaming links...</i>", parse_mode=ParseMode.HTML)
        await process_topic_scrape(context.bot, msg.chat_id, url)
        try:
            await status.delete()
        except Exception:
            pass
    elif is_forum_url(url):
        status = await msg.reply_text("📂 <i>Scanning forum category...</i>", parse_mode=ParseMode.HTML)
        try:
            topics = await asyncio.to_thread(get_forum_topics, url, "start_date", MAX_POSTS_PER_FORUM)
            if not topics:
                await status.edit_text("❌ No topics found in this category.")
                return

            await status.edit_text(f"✅ Found {len(topics)} topics! Extracting...")
            for t in topics:
                await process_topic_scrape(context.bot, msg.chat_id, t["url"])
                await asyncio.sleep(POST_SEND_DELAY)
        except Exception as e:
            await status.edit_text(f"❌ Error: {html.escape(str(e))}")
    else:
        await msg.reply_text("❓ Please send a valid topic (<code>/topic/...</code>) or forum category (<code>/forum/...</code>) URL.", parse_mode=ParseMode.HTML)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Filter and handle plain text messages."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        await handle_raw_url(update, context, text)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle interactive button taps."""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    if data == "cb_today":
        await today_command(update, context)
    elif data == "cb_latest":
        await latest_command(update, context)
    elif data == "cb_domains":
        await domains_command(update, context)
    elif data == "cb_channel_help":
        await setchannel_command(update, context)
    elif data.startswith("sc_"):
        target_id = data[3:]
        target_url = None
        if target_id.isdigit():
            target_url = db.get_url_from_short_id(int(target_id))
        else:
            target_url = target_id

        if target_url:
            await process_topic_scrape(context.bot, query.message.chat_id, target_url)
        else:
            await query.message.reply_text("⚠️ Link expire ho gaya hai ya invalid hai. Kripya dobara search karein.")
    elif data.startswith("unlink_"):
        try:
            ch_id = int(data[7:])
            db.remove_channel(ch_id)
            await query.edit_message_text(f"✅ Channel {ch_id} has been unlinked.")
        except Exception as e:
            logger.error(f"Error unlinking channel: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler for telegram bot exceptions."""
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            # If Telegram complains about message not modified, ignore
            if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
                return
            await update.effective_message.reply_text(
                "⚠️ Bot par ek temporary error aaya. Kripya dobara prayas karein."
            )
        except Exception:
            pass


# --- Post Init & Main Runner ---

async def post_init(application: Application):
    """Register slash commands in Telegram menu and launch background auto-feed."""
    commands = [
        BotCommand("start", "Start the bot & main menu"),
        BotCommand("today", "Today's fresh uploads"),
        BotCommand("latest", "Latest releases from forum"),
        BotCommand("search", "Search videos by keyword"),
        BotCommand("scrape", "Extract links from URL"),
        BotCommand("domains", "Supported streaming hosts"),
        BotCommand("setchannel", "Link channel for auto-feed"),
        BotCommand("channels", "View connected channels"),
        BotCommand("help", "Help & instructions"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Telegram Bot Commands registered.")
    except Exception as e:
        logger.warning(f"Could not register commands with BotFather: {e}")

    # Launch background auto-feed loop
    asyncio.create_task(auto_feed_loop(application))


def main():
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("❌ ERROR: BOT_TOKEN not configured in .env file!")
        sys.exit(1)

    print(f"🤖 Initializing {BOT_NAME} v{BOT_VERSION}...")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("latest", latest_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CommandHandler("domains", domains_command))
    app.add_handler(CommandHandler("setchannel", setchannel_command))
    app.add_handler(CommandHandler("channels", channels_command))

    # Automatic Channel Link Handler (when bot is added as Admin)
    app.add_handler(ChatMemberHandler(chat_member_updated, ChatMemberHandler.MY_CHAT_MEMBER))

    # Button Callbacks
    app.add_handler(CallbackQueryHandler(callback_query_handler))

    # Plain text links
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Global Error Handler
    app.add_error_handler(error_handler)

    logger.info("✅ Bot initialized and listening for updates...")
    print("🚀 Bot is LIVE! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
