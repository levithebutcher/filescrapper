# bot.py

import sys
import html
import io
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
    MenuButtonCommands,
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
    PROVIDER_PRIORITY,
    get_forum_topics,
    get_post_details,
    search_forum,
    is_forum_url,
    is_topic_url,
    get_host_display_name,
    get_host_key,
    filter_links_by_preference,
    download_image_bytes,
    is_livecam_url,
    is_livecam_video_url,
    is_livecam_model_url,
    get_livecam_model_videos,
    get_livecam_video_details,
    format_livecam_card,
    parse_slicing_args,
    apply_slice,
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

# Active scrape tracking & cancellation flags
cancelled_chats: set[int] = set()
active_scrapes: dict[int, bool] = {}


def cancel_scrape_for_chat(chat_id: int | str):
    """Mark active scraping as cancelled for the given chat."""
    try:
        cid = int(chat_id)
        cancelled_chats.add(cid)
        active_scrapes[cid] = False
        logger.info(f"🛑 [CANCELLATION] Cancel flag registered for chat {cid}")
    except Exception as e:
        logger.error(f"Error setting cancel flag for {chat_id}: {e}")


def is_scrape_cancelled(chat_id: int | str) -> bool:
    """Check if cancellation has been requested for this chat."""
    try:
        return int(chat_id) in cancelled_chats
    except Exception:
        return False


def start_scrape_for_chat(chat_id: int | str):
    """Register a scrape run for this chat."""
    try:
        cid = int(chat_id)
        cancelled_chats.discard(cid)
        active_scrapes[cid] = True
        logger.info(f"🚀 [SCRAPE_START] Registered new active scrape for chat {cid}")
    except Exception as e:
        logger.error(f"Error starting scrape for {chat_id}: {e}")


def end_scrape_for_chat(chat_id: int | str):
    """Clean up scrape state when finished or aborted."""
    try:
        cid = int(chat_id)
        cancelled_chats.discard(cid)
        active_scrapes[cid] = False
        logger.info(f"🏁 [SCRAPE_END] Cleaned up scrape state for chat {cid}")
    except Exception as e:
        logger.error(f"Error ending scrape for {chat_id}: {e}")


async def cancellable_sleep(duration: float, chat_id: int | str, step: float = 0.2):
    """Sleep for duration seconds while checking for cancellation every step seconds."""
    elapsed = 0.0
    while elapsed < duration:
        if is_scrape_cancelled(chat_id):
            return
        sleep_time = min(step, duration - elapsed)
        await asyncio.sleep(sleep_time)
        elapsed += sleep_time


# --- UI & Formatters ---

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
    Format single post details into a clean, minimal message.
    Uses Telegram blockquote for the title, filters links according to user preference,
    and formats them as a clean numbered list of copyable <code> links.
    """
    title = html.escape(details.get("title", "Untitled Video"))
    post_url = html.escape(details.get("post_url", ""))
    tags = details.get("tags", [])
    raw_links = details.get("streaming_links", [])

    caption_lines = [f"<blockquote>🎬 <b>{title}</b></blockquote>"]

    if tags:
        tag_str = " ".join([f"<code>#{html.escape(t)}</code>" for t in tags[:5]])
        caption_lines.append(f"🏷️ {tag_str}")

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

    if post_url:
        caption_lines.append(f"\n🌐 <a href='{post_url}'>Original Forum Thread</a>")

    return "\n".join(caption_lines)


# --- Post Sender Engine ---

async def send_post_card(bot, chat_id: int | str, details: dict, user_id: int = None):
    """Deliver a clean post card with downloaded thumbnail bytes and copyable link(s)."""
    if is_scrape_cancelled(chat_id):
        return

    target_uid = user_id if user_id else (chat_id if isinstance(chat_id, int) and chat_id > 0 else 0)
    user_pref = db.get_user_host_preference(target_uid) if target_uid else "streamtape"
    caption = format_post_card(details, user_pref)

    # Collect thumbnail candidates and download the first valid image into memory
    candidates = details.get("thumbnail_candidates", [])
    if not candidates and details.get("thumbnail"):
        candidates = [details["thumbnail"]]

    image_bytes = None
    for cand_url in candidates[:8]:  # Try up to 8 candidates from post
        if is_scrape_cancelled(chat_id):
            return
        try:
            image_bytes = await asyncio.to_thread(download_image_bytes, cand_url)
            if image_bytes:
                break
        except Exception:
            continue

    if is_scrape_cancelled(chat_id):
        return

    # 1. If image downloaded and caption fits within photo caption limit (1024 chars)
    if image_bytes and len(caption) <= 1024:
        try:
            photo_file = io.BytesIO(image_bytes)
            photo_file.name = "poster.jpg"
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            if is_scrape_cancelled(chat_id):
                return
            try:
                photo_file = io.BytesIO(image_bytes)
                photo_file.name = "poster.jpg"
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_file,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Thumbnail send failed: {e}")

    if is_scrape_cancelled(chat_id):
        return

    # 2. If image downloaded but caption is longer than 1024 chars, send photo first then text
    if image_bytes and len(caption) > 1024:
        try:
            photo_file = io.BytesIO(image_bytes)
            photo_file.name = "poster.jpg"
            short_caption = f"<blockquote>🎬 <b>{html.escape(details.get('title', 'Video'))}</b></blockquote>"
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=short_caption,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"Detached photo send failed: {e}")

    if is_scrape_cancelled(chat_id):
        return

    # 3. Fallback to text message
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        if is_scrape_cancelled(chat_id):
            return
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"Failed to send post card to {chat_id}: {e}")


async def send_livecam_card(bot, chat_id: int | str, details: dict):
    """Deliver a clean LiveCamRips card with uncropped HD thumbnail and copyable links."""
    if is_scrape_cancelled(chat_id):
        return

    caption = format_livecam_card(details)
    thumb_url = details.get("thumbnail")

    image_bytes = None
    if thumb_url:
        try:
            image_bytes = await asyncio.to_thread(download_image_bytes, thumb_url)
        except Exception as e:
            logger.debug(f"LiveCamRips thumbnail download note: {e}")

    if is_scrape_cancelled(chat_id):
        return

    if image_bytes and len(caption) <= 1024:
        try:
            photo_file = io.BytesIO(image_bytes)
            photo_file.name = "thumb.jpg"
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            if is_scrape_cancelled(chat_id):
                return
            try:
                photo_file = io.BytesIO(image_bytes)
                photo_file.name = "thumb.jpg"
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_file,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"LiveCamRips photo send failed: {e}")

    if is_scrape_cancelled(chat_id):
        return

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        if is_scrape_cancelled(chat_id):
            return
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )
    except Exception as e:
        logger.error(f"Failed to send LiveCamRips card: {e}")


async def process_livecam_scrape(bot, chat_id: int | str, video_item: dict):
    """Extract streaming links and deliver LiveCamRips card."""
    if is_scrape_cancelled(chat_id):
        return
    try:
        video_url = video_item.get("video_url") or video_item.get("url")
        details = await asyncio.to_thread(get_livecam_video_details, video_url)
        # Preserve model, duration, date from video_item if already parsed from model page
        for k in ["duration", "platform", "model_name", "date"]:
            if video_item.get(k) and not details.get(k):
                details[k] = video_item[k]
        if video_item.get("thumb") and not details.get("thumbnail"):
            details["thumbnail"] = video_item["thumb"]
        if video_item.get("duration"):
            details["duration"] = video_item["duration"]

        if is_scrape_cancelled(chat_id):
            return

        await send_livecam_card(bot, chat_id, details)
    except Exception as e:
        if is_scrape_cancelled(chat_id):
            return
        logger.error(f"Error in process_livecam_scrape: {e}")
        safe_err = html.escape(str(e))
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ <b>Could not extract LiveCam video:</b>\n<code>{html.escape(video_item.get('video_url', ''))}</code>\n<i>Reason: {safe_err}</i>",
            parse_mode=ParseMode.HTML,
        )


# --- Command Handlers ---

def get_host_settings_keyboard(current_pref: str = "streamtape") -> InlineKeyboardMarkup:
    """Generate keyboard for selecting preferred streaming provider."""
    hosts = [
        ("streamtape", "🎬 Streamtape"),
        ("vidara", "⚡ Vidara"),
        ("streamfiles", "📥 Streamfiles"),
        ("iplaygo", "▶️ iPlayGo"),
        ("abstream", "📺 ABStream"),
        ("uqload", "⚡ Uqload"),
        ("doodstream", "🎥 Doodstream"),
        ("streamwish", "✨ Streamwish"),
        ("all", "🌐 All Providers"),
    ]
    buttons = []
    row = []
    for key, label in hosts:
        check = " ✅" if key == current_pref else ""
        row.append(InlineKeyboardButton(f"{label}{check}", callback_data=f"sethost_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


async def sethost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow user to choose their preferred streaming provider."""
    user = update.effective_user
    uid = user.id if user else update.effective_chat.id
    current_pref = db.get_user_host_preference(uid) or "streamtape"

    text = (
        "⚙️ <b>Streaming Player Preferences</b>\n\n"
        f"Current preferred player: <b>{current_pref.upper()}</b>\n\n"
        "Choose your preferred video player. The bot will deliver <b>copyable direct links for this provider</b>.\n\n"
        "<i>💡 If a post does not contain your selected player, the bot automatically "
        "falls back to the next best provider in priority order so you never miss a video.</i>"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_host_settings_keyboard(current_pref),
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Minimal, elegant greeting."""
    user_name = update.effective_user.first_name if update.effective_user else "Friend"
    text = (
        f"✨ <b>Welcome, {html.escape(user_name)}!</b>\n\n"
        f"<b>{BOT_NAME}</b> automatically extracts verified video streaming links "
        "and monitors new forum and cam uploads in real-time.\n\n"
        "<b>⚡ Quick Commands:</b>\n"
        "• <code>/today</code> — Today's fresh uploads (DropMMS & LiveCamRips)\n"
        "• <code>/today 4</code> — Get first 4 uploads of today\n"
        "• <code>/today 1-5</code> — Get uploads 1 to 5\n"
        "• <code>/today last 5</code> — Get last 5 uploads\n"
        "• <code>/latest</code> — Latest forum releases\n"
        "• <code>/sethost</code> — Set preferred video player (Streamtape/Vidara/etc.)\n"
        "• <code>/search &lt;name&gt;</code> — Find videos by keyword\n"
        "• <code>/scrape &lt;url&gt;</code> — Extract any topic, category, or model\n"
        "• <code>/stop</code> — Immediately cancel active extraction\n"
        "• <code>/channels</code> — Manage auto-feed broadcast channels\n\n"
        "<i>💡 Or paste any DropMMS or LiveCamRips link directly in chat to extract instantly.</i>"
    )

    buttons = [
        [
            InlineKeyboardButton("📅 Today's Drops", callback_data="cb_today"),
            InlineKeyboardButton("⚡ Latest Posts", callback_data="cb_latest"),
        ],
        [
            InlineKeyboardButton("⚙️ Preferred Player", callback_data="cb_sethost"),
            InlineKeyboardButton("🔍 Search Videos", callback_data="cb_search"),
        ],
        [
            InlineKeyboardButton("📢 Channel Setup", callback_data="cb_channel_help"),
            InlineKeyboardButton("📖 User Guide", callback_data="cb_help"),
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
        "• <code>/search sample video</code>\n\n"
        "<b>4️⃣ 24/7 Channel Auto-Poster:</b>\n"
        "1. Add this bot to your Telegram Channel as <b>Administrator</b>.\n"
        "2. The bot will automatically link the channel and broadcast new drops every 15 minutes!\n"
        "3. Or use <code>/setchannel &lt;category_url&gt;</code> inside the channel."
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Immediately stop any active topic, model, or category scraping in this chat."""
    chat = update.effective_chat
    chat_id = chat.id if chat else None
    if not chat_id:
        return

    logger.info(f"🛑 [/stop] Stop requested by user in chat {chat_id}")
    cancel_scrape_for_chat(chat_id)
    await update.effective_message.reply_text(
        "🛑 <b>Scraping stopped.</b>\n\n"
        "Active extraction has been cancelled. Remaining posts will not be sent.",
        parse_mode=ParseMode.HTML,
    )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fetch and deliver today's fresh uploads (Option 1: Live Date Cutoff).
    Supports DropMMS forum categories and LiveCamRips model pages.
    Supports post count, ranges, and last-N slicing:
      /today
      /today 4
      /today 1-5
      /today last 5
      /today <url>
      /today <url> 4
      /today <url> 1-5
      /today <url> last 5
    """
    msg = update.effective_message
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = msg.chat_id

    # Log incoming command and arguments
    logger.info(f"📅 [/today] Chat {chat_id} (User: {user_id}) - context.args={context.args}")

    # Register scrape immediately so /stop or button cancels it without delay
    start_scrape_for_chat(chat_id)

    target_url, start_idx, end_idx, is_last_n = parse_slicing_args(context.args or [])
    if not target_url:
        target_url = DEFAULT_CATEGORY_URL
    elif not target_url.startswith("http://") and not target_url.startswith("https://"):
        target_url = f"https://{target_url}"

    has_slice = (start_idx is not None) or (end_idx is not None) or is_last_n
    logger.info(f"🎯 [/today] Target URL: {target_url} | Slice: start={start_idx}, end={end_idx}, is_last_n={is_last_n}")

    status_msg = await msg.reply_text("📅 <i>Scanning today's uploads...</i>", parse_mode=ParseMode.HTML)

    # 1. LiveCamRips URL Handling
    if is_livecam_url(target_url):
        # 1A. Single video URL
        if is_livecam_video_url(target_url):
            await status_msg.edit_text("🔍 <i>Extracting LiveCam video streaming link...</i>", parse_mode=ParseMode.HTML)
            try:
                details = await asyncio.to_thread(get_livecam_video_details, target_url)
                await send_livecam_card(context.bot, chat_id, details)
            except Exception as e:
                await status_msg.edit_text(f"❌ Error extracting LiveCam video: {html.escape(str(e))}")
                return
            finally:
                end_scrape_for_chat(chat_id)
            try:
                await status_msg.delete()
            except Exception:
                pass
            return

        # 1B. Model page URL
        only_today = not has_slice  # If user requested a slice (e.g. 4 or 1-5), fetch recent videos

        try:
            # Fetch up to 50 videos from model page (sorted newest first)
            videos = await asyncio.to_thread(get_livecam_model_videos, target_url, only_today, 50)
            if has_slice:
                videos = apply_slice(videos, start_idx, end_idx, is_last_n)
        except Exception as e:
            await status_msg.edit_text(f"❌ Error fetching model page: {html.escape(str(e))}")
            end_scrape_for_chat(chat_id)
            return

        if not videos:
            end_scrape_for_chat(chat_id)
            await status_msg.edit_text(
                "📅 <b>No uploads found today for this model!</b>\n\n"
                "<i>Older videos were skipped. Tip: Specify a count or range to view recent uploads:</i>\n"
                f"<code>/today {html.escape(target_url)} 4</code>\n"
                f"<code>/scrape {html.escape(target_url)} 1-5</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        stop_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛑 Stop Extraction", callback_data="btn_stop_scrape")
        ]])
        await status_msg.edit_text(
            f"📅 <b>Found {len(videos)} video(s)!</b>\n<i>Extracting details & streaming links...</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=stop_markup,
        )

        try:
            for idx, v in enumerate(videos, start=1):
                if is_scrape_cancelled(chat_id):
                    logger.info(f"LiveCam scrape cancelled by user in chat {chat_id}")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🛑 <b>Scrape stopped!</b> Delivered {idx-1}/{len(videos)} videos.",
                        parse_mode=ParseMode.HTML,
                    )
                    break
                await process_livecam_scrape(context.bot, chat_id, v)
                if is_scrape_cancelled(chat_id):
                    break
                await cancellable_sleep(POST_SEND_DELAY, chat_id)
        finally:
            end_scrape_for_chat(chat_id)

        try:
            await status_msg.delete()
        except Exception:
            pass
        return

    # 2. DropMMS single topic URL
    if is_topic_url(target_url):
        await status_msg.edit_text("🔍 <i>Extracting streaming links from topic...</i>", parse_mode=ParseMode.HTML)
        try:
            await process_topic_scrape(context.bot, chat_id, target_url, user_id=user_id)
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status_msg.delete()
        except Exception:
            pass
        return

    # 3. DropMMS Forum Category
    try:
        # Fetch today's topics without artificial limit (stops when yesterday reached, paginating up to 10 pages)
        all_today_topics = await asyncio.to_thread(get_forum_topics, target_url, "start_date", 200, True)
    except Exception as e:
        logger.error(f"Error fetching forum category: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error fetching category: {html.escape(str(e))}")
        end_scrape_for_chat(chat_id)
        return

    # Apply slicing if specified
    topics = apply_slice(all_today_topics, start_idx, end_idx, is_last_n)

    # If user explicitly asked for a slice (e.g. 4 or 1-5) and 0 uploads occurred today,
    # gracefully fall back to latest posts from that category so the user's slice is fulfilled
    if not topics and has_slice:
        logger.info(f"No today posts found for slice in {target_url}. Fetching recent posts.")
        await status_msg.edit_text("📅 <i>No posts uploaded today. Fetching recent uploads...</i>", parse_mode=ParseMode.HTML)
        try:
            recent_topics = await asyncio.to_thread(get_forum_topics, target_url, "start_date", 50, False)
            topics = apply_slice(recent_topics, start_idx, end_idx, is_last_n)
        except Exception as e:
            logger.warning(f"Fallback fetch error: {e}")

    if not topics:
        end_scrape_for_chat(chat_id)
        quick_buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Latest Posts", callback_data="cb_latest")],
            [InlineKeyboardButton("🔍 Search Videos", callback_data="cb_search")],
        ])
        await status_msg.edit_text(
            "📅 <b>No new posts found today yet!</b>\n\n"
            "<i>No topics uploaded today in this category. Older posts were skipped.</i>\n\n"
            "💡 <i>Tips:</i>\n"
            f"• Get recent uploads with count or range:\n"
            f"  <code>/scrape {html.escape(target_url)} 4</code>\n"
            f"  <code>/scrape {html.escape(target_url)} 1-5</code>\n"
            "• Or tap below to view latest releases:",
            parse_mode=ParseMode.HTML,
            reply_markup=quick_buttons,
        )
        return

    stop_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Stop Extraction", callback_data="btn_stop_scrape")
    ]])
    await status_msg.edit_text(
        f"📅 <b>Found {len(topics)} upload(s)!</b>\n<i>Extracting links...</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=stop_markup,
    )

    try:
        for idx, t in enumerate(topics, start=1):
            if is_scrape_cancelled(chat_id):
                logger.info(f"Today scrape cancelled by user in chat {chat_id}")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🛑 <b>Today scrape stopped!</b> Sent {idx-1}/{len(topics)} posts.",
                    parse_mode=ParseMode.HTML,
                )
                break
            await process_topic_scrape(context.bot, chat_id, t["url"], user_id=user_id)
            if is_scrape_cancelled(chat_id):
                break
            await cancellable_sleep(POST_SEND_DELAY, chat_id)
    finally:
        end_scrape_for_chat(chat_id)

    try:
        await status_msg.delete()
    except Exception:
        pass


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

async def process_topic_scrape(bot, chat_id: int | str, url: str, user_id: int = None):
    """Scrape and deliver single topic card with cancellation support."""
    if is_scrape_cancelled(chat_id):
        return
    try:
        details = await asyncio.to_thread(get_post_details, url)
        if is_scrape_cancelled(chat_id):
            return
        await send_post_card(bot, chat_id, details, user_id=user_id)
    except Exception as e:
        if is_scrape_cancelled(chat_id):
            return
        safe_err = html.escape(str(e))
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ <b>Could not extract:</b>\n<code>{html.escape(url)}</code>\n<i>Reason: {safe_err}</i>",
            parse_mode=ParseMode.HTML,
        )


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /scrape <url> [slice] command."""
    msg = update.effective_message
    logger.info(f"🛠️ [/scrape] Chat {update.effective_chat.id} (User: {update.effective_user.id if update.effective_user else None}) - context.args={context.args}")
    if not context.args:
        await msg.reply_text(
            "ℹ️ <b>Usage:</b> <code>/scrape &lt;url&gt; [count or range]</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/scrape https://dropmms.com/topic/123-title/</code>\n"
            "• <code>/scrape https://dropmms.com/forum/2-general/ 5</code>\n"
            "• <code>/scrape https://dropmms.com/forum/2-general/ 1-5</code>\n"
            "• <code>/scrape https://livecamrips.to/model/36773/GoddessAnna 4</code>\n"
            "• <code>/scrape https://livecamrips.to/video/16877744</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    raw_input = " ".join(context.args)
    await handle_raw_url(update, context, raw_input)


async def handle_raw_url(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_text: str):
    """Process URLs and slice options pasted directly in chat or via /scrape."""
    msg = update.effective_message
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = msg.chat_id

    tokens = raw_text.strip().split()
    target_url, start_idx, end_idx, is_last_n = parse_slicing_args(tokens)
    if not target_url:
        return

    if not target_url.startswith("http://") and not target_url.startswith("https://"):
        if "dropmms.com" in target_url:
            target_url = f"https://{target_url}"
        elif "livecamrips.to" in target_url:
            target_url = f"https://{target_url}"
        else:
            return

    logger.info(f"🔗 [handle_raw_url] Chat {chat_id} (User: {user_id}) - Target URL: {target_url} | Slice: start={start_idx}, end={end_idx}, is_last_n={is_last_n}")
    start_scrape_for_chat(chat_id)

    # 1. LiveCamRips Single Video
    if is_livecam_video_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting LiveCam video streaming link...</i>", parse_mode=ParseMode.HTML)
        try:
            details = await asyncio.to_thread(get_livecam_video_details, target_url)
            await send_livecam_card(context.bot, chat_id, details)
        except Exception as e:
            await status.edit_text(f"❌ Error extracting LiveCam video: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 2. LiveCamRips Model Page
    if is_livecam_model_url(target_url):
        status = await msg.reply_text("📂 <i>Scanning LiveCam model page...</i>", parse_mode=ParseMode.HTML)
        try:
            videos = await asyncio.to_thread(get_livecam_model_videos, target_url, False, 50)
            if start_idx is not None or end_idx is not None or is_last_n:
                videos = apply_slice(videos, start_idx, end_idx, is_last_n)
            else:
                videos = videos[:MAX_POSTS_PER_FORUM]

            if not videos:
                await status.edit_text("❌ No videos found on this model page.")
                end_scrape_for_chat(chat_id)
                return

            stop_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("🛑 Stop Extraction", callback_data="btn_stop_scrape")
            ]])
            await status.edit_text(f"✅ Found {len(videos)} video(s)! Extracting...", reply_markup=stop_markup)

            for idx, v in enumerate(videos, start=1):
                if is_scrape_cancelled(chat_id):
                    logger.info(f"Model scrape cancelled by user in chat {chat_id}")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🛑 <b>Scraping stopped!</b> Delivered {idx-1}/{len(videos)} videos.",
                        parse_mode=ParseMode.HTML,
                    )
                    break
                await process_livecam_scrape(context.bot, chat_id, v)
                if is_scrape_cancelled(chat_id):
                    break
                await cancellable_sleep(POST_SEND_DELAY, chat_id)
        except Exception as e:
            await status.edit_text(f"❌ Error: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)

        try:
            await status.delete()
        except Exception:
            pass
        return

    # 3. DropMMS Single Topic
    if is_topic_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting streaming links...</i>", parse_mode=ParseMode.HTML)
        try:
            await process_topic_scrape(context.bot, chat_id, target_url, user_id=user_id)
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 4. DropMMS Forum Category
    if is_forum_url(target_url):
        status = await msg.reply_text("📂 <i>Scanning forum category...</i>", parse_mode=ParseMode.HTML)
        try:
            topics = await asyncio.to_thread(get_forum_topics, target_url, "start_date", 50, False)
            if start_idx is not None or end_idx is not None or is_last_n:
                topics = apply_slice(topics, start_idx, end_idx, is_last_n)
            else:
                topics = topics[:MAX_POSTS_PER_FORUM]

            if not topics:
                await status.edit_text("❌ No topics found in this category.")
                end_scrape_for_chat(chat_id)
                return

            stop_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("🛑 Stop Extraction", callback_data="btn_stop_scrape")
            ]])
            await status.edit_text(f"✅ Found {len(topics)} topics! Extracting...", reply_markup=stop_markup)

            for idx, t in enumerate(topics, start=1):
                if is_scrape_cancelled(chat_id):
                    logger.info(f"Category scrape cancelled by user in chat {chat_id}")
                    await context.bot.send_message(
                        chat_id=msg.chat_id,
                        text=f"🛑 <b>Scraping stopped!</b> Processed {idx-1}/{len(topics)} topics.",
                        parse_mode=ParseMode.HTML,
                    )
                    break
                await process_topic_scrape(context.bot, msg.chat_id, t["url"], user_id=user_id)
                if is_scrape_cancelled(chat_id):
                    break
                await cancellable_sleep(POST_SEND_DELAY, chat_id)
        except Exception as e:
            await status.edit_text(f"❌ Error: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)

        try:
            await status.delete()
        except Exception:
            pass
        return

    end_scrape_for_chat(chat_id)
    await msg.reply_text("❓ Please send a valid DropMMS or LiveCamRips URL (video or category/model page).", parse_mode=ParseMode.HTML)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Filter and handle plain text messages containing links or control keywords."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    logger.info(f"📩 [handle_message] Received text from Chat {update.effective_chat.id} (User: {update.effective_user.id if update.effective_user else None}): {text!r}")

    # Allow users to stop simply by typing 'stop' or 'cancel' without slash
    if text.lower() in ["stop", "cancel", "/stop", "/cancel", "halt"]:
        await stop_command(update, context)
        return

    if text.startswith("http://") or text.startswith("https://") or "dropmms.com" in text or "livecamrips.to" in text:
        await handle_raw_url(update, context, text)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle interactive button taps."""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    if data == "btn_stop_scrape":
        chat_id = query.message.chat_id
        cancel_scrape_for_chat(chat_id)
        try:
            await query.edit_message_text(
                "🛑 <b>Scraping stopped by user.</b>\nRemaining topics will not be processed.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    elif data == "cb_today":
        await today_command(update, context)
    elif data == "cb_latest":
        await latest_command(update, context)
    elif data == "cb_search":
        await query.message.reply_text(
            "🔍 <b>How to Search Videos:</b>\n\n"
            "Use the <code>/search</code> command followed by a movie title or keyword:\n\n"
            "<b>Examples:</b>\n"
            "• <code>/search 1080p</code>\n"
            "• <code>/search action</code>\n"
            "• <code>/search sample</code>\n\n"
            "<i>Just type /search &lt;keyword&gt; to search instantly!</i>",
            parse_mode=ParseMode.HTML,
        )
    elif data == "cb_help":
        await help_command(update, context)
    elif data == "cb_domains":
        await domains_command(update, context)
    elif data == "cb_channel_help":
        await setchannel_command(update, context)
    elif data == "cb_sethost":
        await sethost_command(update, context)
    elif data.startswith("sethost_"):
        new_pref = data[8:]
        user_id = query.from_user.id
        db.set_user_host_preference(user_id, new_pref)
        display_label = new_pref.upper() if new_pref != "all" else "ALL HOSTS"
        try:
            await query.edit_message_text(
                f"✅ <b>Preferred Player Updated to {display_label}!</b>\n\n"
                "All future posts will prioritize this video player (with automatic smart fallback).\n\n"
                "You can change your selection anytime below:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_host_settings_keyboard(new_pref),
            )
        except Exception:
            pass
    elif data.startswith("sc_"):
        target_id = data[3:]
        target_url = None
        if target_id.isdigit():
            target_url = db.get_url_from_short_id(int(target_id))
        else:
            target_url = target_id

        if target_url:
            await process_topic_scrape(context.bot, query.message.chat_id, target_url, user_id=query.from_user.id)
        else:
            await query.message.reply_text("⚠️ This link has expired or is invalid. Please search or extract again.")
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
            if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
                return
            await update.effective_message.reply_text(
                "⚠️ A temporary error occurred while processing your request. Please try again."
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
        BotCommand("sethost", "Choose preferred video player"),
        BotCommand("search", "Search videos by keyword"),
        BotCommand("scrape", "Extract links from URL"),
        BotCommand("domains", "Supported streaming hosts"),
        BotCommand("setchannel", "Link channel for auto-feed"),
        BotCommand("channels", "View connected channels"),
        BotCommand("stop", "Stop active category extraction"),
        BotCommand("help", "Help & instructions"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        # Enable native Telegram command menu button at bottom-left of chat input
        try:
            await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        except Exception as e_menu:
            logger.debug(f"Menu button set note: {e_menu}")
        logger.info("✅ Telegram Bot Commands & Menu Button registered.")
    except Exception as e:
        logger.warning(f"Could not register commands with BotFather: {e}")

    # Launch background auto-feed loop
    asyncio.create_task(auto_feed_loop(application))


def main():
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("❌ ERROR: BOT_TOKEN not configured in .env file!")
        sys.exit(1)

    print(f"🤖 Initializing {BOT_NAME} v{BOT_VERSION}...")
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("latest", latest_command))
    app.add_handler(CommandHandler("sethost", sethost_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CommandHandler("domains", domains_command))
    app.add_handler(CommandHandler("setchannel", setchannel_command))
    app.add_handler(CommandHandler("channels", channels_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("cancel", stop_command))

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
