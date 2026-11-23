# bot.py

import sys
import re
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
from telegram.error import RetryAfter, BadRequest, TelegramError, Conflict
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
    search_livecam_models,
    clean_livecam_title,
    get_livecam_model_stats,
    parse_model_range_input,
    get_dropmms_forums,
    get_dropmms_category_stats,
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
    is_mmstown_url,
    is_mmstown_topic_url,
    is_mmstown_forum_url,
    get_mmstown_forums,
    is_mmsvibex_url,
    is_mmsvibex_photo_url,
    is_mmsvibex_video_url,
    is_mmsvibex_listing_url,
    get_mmsvibex_video_details,
    get_mmsvibex_actor_videos,
    get_mmsvibex_photo_details,
    get_mmsvibex_listing_items,
    search_mmsvibex,
    is_wp_locker_url,
    is_wp_locker_listing_url,
    is_wp_locker_post_url,
    get_wp_post_details,
    get_wp_listing_posts,
    search_forum_advanced,
    get_universal_post_details,
)
import db

from ui import (
    group_links_by_host,
    format_post_card,
    format_search_results_page,
    format_listing_menu_card,
)
from keyboards import (
    build_stop_keyboard,
    build_card_keyboard,
    get_navigation_keyboard,
    get_host_settings_keyboard,
    get_link_mode_keyboard,
    build_main_menu_keyboard,
    build_search_platform_keyboard,
    build_search_execute_platform_keyboard,
    build_search_results_keyboard,
    build_mmsvibex_mode_keyboard,
    build_slice_selection_keyboard,
    build_forum_options_keyboard,
    build_forum_sort_keyboard,
    build_model_options_keyboard,
    build_model_sort_keyboard,
    build_channel_management_keyboard,
    build_back_cancel_row,
    build_back_cancel_keyboard,
)
import messages
import progress

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


def is_chat_busy(chat_id: int | str) -> bool:
    """Check if an active scrape is currently running for this chat."""
    try:
        return bool(active_scrapes.get(int(chat_id), False))
    except Exception:
        return False



async def cancellable_sleep(duration: float, chat_id: int | str, step: float = 0.2):
    """Sleep for duration seconds while checking for cancellation every step seconds."""
    elapsed = 0.0
    while elapsed < duration:
        if is_scrape_cancelled(chat_id):
            return
        sleep_time = min(step, duration - elapsed)
        await asyncio.sleep(sleep_time)
        elapsed += sleep_time


# --- UI & Presentation Layer ---
# All card formatters, keyboards, and message templates have been cleanly separated
# into ui.py, keyboards.py, messages.py, and progress.py for easy customization.


# --- Post Sender Engine ---

async def send_post_card(bot, chat_id: int | str, details: dict, user_id: int = None, reply_markup=None):
    """Deliver a clean post card with downloaded thumbnail bytes and copyable link(s)."""
    if is_scrape_cancelled(chat_id):
        return

    target_uid = user_id if user_id else (chat_id if isinstance(chat_id, int) and chat_id > 0 else 0)
    user_pref = db.get_user_host_preference(target_uid) if target_uid else "streamtape"
    caption = format_post_card(details, user_pref)
    if reply_markup is None:
        reply_markup = build_card_keyboard(details, user_pref)

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
                reply_markup=reply_markup,
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
                    reply_markup=reply_markup,
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
            reply_markup=reply_markup,
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
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"Failed to send post card to {chat_id}: {e}")


async def send_livecam_card(bot, chat_id: int | str, details: dict, user_id: int | str = None, reply_markup=None):
    """Deliver a clean LiveCamRips card with uncropped HD thumbnail and copyable links using Universal Card Engine."""
    if is_scrape_cancelled(chat_id):
        return

    uid = user_id or chat_id
    target_uid = uid if isinstance(uid, int) and uid > 0 else 0
    user_pref = db.get_user_host_preference(target_uid) if target_uid else "streamtape"
    link_mode = db.get_user_link_mode(uid)

    # Normalize details for Universal Card
    details_copy = dict(details)
    if not details_copy.get("title") and details_copy.get("model_name"):
        details_copy["title"] = details_copy["model_name"]
    details_copy.setdefault("site", "livecam")
    details_copy.setdefault("platform_name", "LiveCamRips")
    if details_copy.get("date") and not details_copy.get("date_ist"):
        details_copy["date_ist"] = details_copy["date"]

    if link_mode == "page" and details_copy.get("video_url"):
        details_copy["streaming_links"] = [details_copy["video_url"]]

    caption = format_post_card(details_copy, user_pref=user_pref)
    if reply_markup is None:
        reply_markup = build_card_keyboard(details_copy, user_pref)

    thumb_url = details_copy.get("thumbnail")

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
                reply_markup=reply_markup,
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
                    reply_markup=reply_markup,
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
            reply_markup=reply_markup,
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
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"Failed to send LiveCamRips card: {e}")


async def process_livecam_scrape(bot, chat_id: int | str, video_item: dict, user_id: int | str = None):
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

        await send_livecam_card(bot, chat_id, details, user_id=user_id)
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


async def run_livecam_model_scrape(
    bot,
    chat_id: int | str,
    target_url: str,
    only_today: bool = False,
    sort_by: str = "newest",
    start_idx: int = 1,
    end_idx: int | None = None,
    page_num: int | None = None,
    req_limit: int | None = None,
    status_msg=None,
    user_id: int | str = None,
):
    """
    Standardized worker to scrape and deliver videos from a LiveCamRips model page.
    Supports sorting, flexible range (e.g. 5-10), direct page, stopping, and quoted status cards.
    """
    cid = int(chat_id)
    uid = user_id or cid
    if is_chat_busy(cid):
        txt = "<blockquote>⚠️ Another scrape is currently running in this chat. Use /stop first.</blockquote>"
        if status_msg:
            try:
                await status_msg.edit_text(txt, parse_mode=ParseMode.HTML)
            except Exception:
                await bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.HTML)
        return

    start_scrape_for_chat(cid)
    clean_u = target_url.split("?")[0].split("#")[0].rstrip("/")
    parts = [p for p in clean_u.split("/") if p]
    model_name = clean_livecam_title(parts[-1] if len(parts) >= 3 else "Model")

    sort_labels = {
        "newest": "Newest",
        "most_viewed": "Most Viewed",
        "most_liked": "Most Liked",
        "oldest": "Oldest",
    }
    sort_label = sort_labels.get(sort_by, "Newest")

    # Determine range and fetch params
    if page_num is not None:
        start_page = page_num
        offset = 0
        count = 16
        limit_needed = 16
        range_label = f"Page {page_num}"
    elif end_idx is not None:
        s_idx = max(1, start_idx or 1)
        e_idx = max(s_idx, end_idx)
        start_page = 1 + (s_idx - 1) // 16
        offset = (s_idx - 1) % 16
        count = e_idx - s_idx + 1
        limit_needed = offset + count
        range_label = f"{s_idx} to {e_idx}"
    else:
        count = req_limit or (50 if not only_today else 200)
        start_page = 1
        offset = 0
        limit_needed = count
        range_label = f"Top {count}" if not only_today else "Today's Uploads"

    loading_text = (
        "<blockquote>"
        f"📹 <b>{html.escape(model_name)}</b>\n"
        f"🎯 <b>Sort:</b> {sort_label}\n"
        f"🔢 <b>Range:</b> {range_label}\n"
        "⏳ <b>Status:</b> Scanning model page...</blockquote>"
    )
    if status_msg:
        try:
            await status_msg.edit_text(loading_text, parse_mode=ParseMode.HTML)
        except Exception:
            status_msg = await bot.send_message(chat_id=cid, text=loading_text, parse_mode=ParseMode.HTML)
    else:
        status_msg = await bot.send_message(chat_id=cid, text=loading_text, parse_mode=ParseMode.HTML)

    try:
        raw_videos = await asyncio.to_thread(
            get_livecam_model_videos,
            target_url,
            only_today=only_today,
            limit=limit_needed,
            sort_by=sort_by,
            start_page=start_page,
        )
        videos = raw_videos[offset : offset + count]

        if not videos:
            msg_text = (
                "<blockquote>"
                f"📹 <b>{html.escape(model_name)}</b>\n"
                "📅 <b>No uploads found today for this model!</b></blockquote>"
                if only_today
                else (
                    "<blockquote>"
                    f"📹 <b>{html.escape(model_name)}</b>\n"
                    f"❌ No videos found for {range_label}.</blockquote>"
                )
            )
            await status_msg.edit_text(msg_text, parse_mode=ParseMode.HTML)
            end_scrape_for_chat(cid)
            return

        stop_markup = build_stop_keyboard()
        extracting_text = (
            "<blockquote>"
            f"📹 <b>{html.escape(model_name)}</b>\n"
            f"🎯 <b>Sort:</b> {sort_label}\n"
            f"🔢 <b>Range:</b> {range_label} ({len(videos)} videos)\n"
            "⏳ <b>Status:</b> Extracting streaming links...</blockquote>"
        )
        await status_msg.edit_text(extracting_text, parse_mode=ParseMode.HTML, reply_markup=stop_markup)

        for idx, v in enumerate(videos, start=1):
            if is_scrape_cancelled(cid):
                logger.info(f"Model scrape cancelled by user in chat {cid}")
                await bot.send_message(
                    chat_id=cid,
                    text=f"<blockquote>🛑 <b>Scraping stopped!</b> Delivered {idx-1}/{len(videos)} videos.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
                break
            await process_livecam_scrape(bot, cid, v, user_id=uid)
            if is_scrape_cancelled(cid):
                break
            await cancellable_sleep(POST_SEND_DELAY, cid)

        if not is_scrape_cancelled(cid):
            try:
                await status_msg.edit_text(
                    f"<blockquote>✅ <b>Extraction Complete!</b>\n📹 <b>{html.escape(model_name)}</b>\n📦 Delivered: <b>{len(videos)}</b> videos</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_navigation_keyboard(),
                )
            except Exception:
                try:
                    await bot.send_message(
                        chat_id=cid,
                        text=f"<blockquote>✅ <b>Extraction Complete!</b>\n📹 <b>{html.escape(model_name)}</b>\n📦 Delivered: <b>{len(videos)}</b> videos</blockquote>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_navigation_keyboard(),
                    )
                except Exception:
                    pass
        else:
            try:
                await status_msg.delete()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error scraping LiveCam model {target_url}: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"<blockquote>❌ Error: {html.escape(str(e))}</blockquote>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    finally:
        end_scrape_for_chat(cid)


async def run_forum_category_scrape(
    bot,
    chat_id: int | str,
    target_url: str,
    only_today: bool = False,
    date_filter: str | None = None,
    sort_by: str = "start_date",
    start_idx: int | None = None,
    end_idx: int | None = None,
    page_num: int | None = None,
    req_limit: int | None = None,
    is_last_n: bool = False,
    status_msg=None,
    user_id: int | str = None,
    cat_title: str | None = None,
):
    """
    Standardized worker to scrape and deliver topics from a DropMMS forum category.
    Supports sorting, date filtering (today, yesterday), flexible range (e.g. 5-10), direct page, stopping, and quoted status cards.
    """
    cid = int(chat_id)
    uid = user_id or cid
    if is_chat_busy(cid):
        txt = "<blockquote>⚠️ Another scrape is currently running in this chat. Use /stop first.</blockquote>"
        if status_msg:
            try:
                await status_msg.edit_text(txt, parse_mode=ParseMode.HTML)
            except Exception:
                await bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.HTML)
        return

    start_scrape_for_chat(cid)

    sort_labels = {
        "start_date": "Upload Date (Start Date)",
        "updated": "Recently Updated",
        "views": "Most Viewed",
    }
    sort_label = sort_labels.get(sort_by, "Upload Date")

    # Clean target URL and determine title
    clean_base = target_url.split("?")[0].split("#")[0].rstrip("/")
    if not cat_title:
        parts = [p for p in clean_base.split("/") if p]
        raw_slug = parts[-1] if parts else "Forum"
        if raw_slug.isdigit() and len(parts) >= 2 and parts[-2] == "page":
            raw_slug = parts[-3] if len(parts) >= 3 else "Forum"
        slug_clean = re.sub(r"^\d+-", "", raw_slug).replace("-", " ").title()
        cat_title = slug_clean or "Forum Category"

    active_date_filter = date_filter or ("today" if only_today else None)

    # Construct URL if page_num specified
    effective_url = target_url
    if active_date_filter == "today":
        range_label = "Today's Uploads (IST)"
        limit_needed = req_limit or 100
    elif active_date_filter in ["yesterday", "2days"]:
        range_label = "Yesterday & Today (IST)"
        limit_needed = req_limit or 150
    elif page_num is not None:
        effective_url = re.sub(r"/page/\d+/?", "/", clean_base)
        effective_url = f"{effective_url.rstrip('/')}/page/{page_num}/"
        range_label = f"Page {page_num}"
        limit_needed = req_limit or 25
    elif end_idx is not None:
        s_idx = max(1, start_idx or 1)
        range_label = f"{s_idx} to {end_idx}"
        limit_needed = max(end_idx, 25)
    elif is_last_n and end_idx is not None:
        range_label = f"Last {end_idx}"
        limit_needed = max(end_idx, 25)
    else:
        count = req_limit or 25
        range_label = f"Top {count}"
        limit_needed = count

    loading_text = (
        "<blockquote>"
        f"💬 <b>{html.escape(cat_title)}</b>\n"
        f"🎯 <b>Sort:</b> {sort_label}\n"
        f"🔢 <b>Range:</b> {range_label}\n"
        "⏳ <b>Status:</b> Scanning forum category...</blockquote>"
    )
    if status_msg:
        try:
            await status_msg.edit_text(loading_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    else:
        status_msg = await bot.send_message(chat_id=cid, text=loading_text, parse_mode=ParseMode.HTML)

    try:
        raw_topics = await asyncio.to_thread(
            get_forum_topics,
            effective_url,
            sort_by=sort_by,
            limit=limit_needed,
            only_today=(active_date_filter == "today"),
            date_filter=active_date_filter,
        )

        if start_idx is not None or end_idx is not None or is_last_n:
            topics = apply_slice(raw_topics, start_idx, end_idx, is_last_n)
        elif not active_date_filter:
            topics = raw_topics[:limit_needed]
        else:
            topics = raw_topics

        if not topics:
            short_id = db.get_or_create_short_id(clean_base)
            buttons = []
            if active_date_filter == "today":
                not_found_desc = (
                    "📅 <b>No uploads found today (IST) in this category!</b>\n\n"
                    "<i>Tip: Uploads may not have started yet today. Try checking yesterday's posts or scraping recent uploads below:</i>"
                )
                buttons.append([
                    InlineKeyboardButton("📆 Check Yesterday & Today", callback_data=f"sp_cdate:{short_id}:{sort_by}:yesterday"),
                    InlineKeyboardButton("🔝 Latest 10 Posts", callback_data=f"sp_crun:{short_id}:10"),
                ])
            elif active_date_filter in ["yesterday", "2days"]:
                not_found_desc = (
                    "📅 <b>No uploads found yesterday or today in this category!</b>\n\n"
                    "<i>Tip: Try scraping recent uploads below:</i>"
                )
                buttons.append([
                    InlineKeyboardButton("🔝 Latest 10 Posts", callback_data=f"sp_crun:{short_id}:10"),
                ])
            else:
                not_found_desc = f"❌ No topics found for {range_label}."
                buttons.append([
                    InlineKeyboardButton("🔝 Latest 10 Posts", callback_data=f"sp_crun:{short_id}:10"),
                ])

            buttons.append([
                InlineKeyboardButton("🔙 Back to Category", callback_data=f"sp_cat:{short_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ])
            markup = InlineKeyboardMarkup(buttons)

            msg_text = (
                "<blockquote>"
                f"💬 <b>{html.escape(cat_title)}</b>\n"
                f"{not_found_desc}</blockquote>"
            )
            if status_msg:
                try:
                    await status_msg.edit_text(msg_text, parse_mode=ParseMode.HTML, reply_markup=markup)
                except Exception:
                    await bot.send_message(chat_id=cid, text=msg_text, parse_mode=ParseMode.HTML, reply_markup=markup)
            else:
                await bot.send_message(chat_id=cid, text=msg_text, parse_mode=ParseMode.HTML, reply_markup=markup)
            end_scrape_for_chat(cid)
            return

        stop_markup = build_stop_keyboard()
        extracting_text = (
            "<blockquote>"
            f"💬 <b>{html.escape(cat_title)}</b>\n"
            f"🎯 <b>Sort:</b> {sort_label}\n"
            f"🔢 <b>Range:</b> {range_label} ({len(topics)} topics)\n"
            "⏳ <b>Status:</b> Extracting streaming links...</blockquote>"
        )
        await status_msg.edit_text(extracting_text, parse_mode=ParseMode.HTML, reply_markup=stop_markup)

        for idx, t in enumerate(topics, start=1):
            if is_scrape_cancelled(cid):
                logger.info(f"Category scrape cancelled by user in chat {cid}")
                await bot.send_message(
                    chat_id=cid,
                    text=f"<blockquote>🛑 <b>Scraping stopped!</b> Delivered {idx-1}/{len(topics)} topics.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
                break
            await process_topic_scrape(bot, cid, t["url"], user_id=uid, topic_meta=t)
            if is_scrape_cancelled(cid):
                break
            await cancellable_sleep(POST_SEND_DELAY, cid)

        if not is_scrape_cancelled(cid):
            try:
                await status_msg.edit_text(
                    f"<blockquote>✅ <b>Extraction Complete!</b>\n📁 Delivered: <b>{len(topics)}</b> topics</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_navigation_keyboard(),
                )
            except Exception:
                try:
                    await bot.send_message(
                        chat_id=cid,
                        text=f"<blockquote>✅ <b>Extraction Complete!</b>\n📁 Delivered: <b>{len(topics)}</b> topics</blockquote>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_navigation_keyboard(),
                    )
                except Exception:
                    pass
        else:
            try:
                await status_msg.delete()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error scraping forum category {target_url}: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"<blockquote>❌ Error: {html.escape(str(e))}</blockquote>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    finally:
        end_scrape_for_chat(cid)


async def run_mmsvibex_listing_scrape(
    bot,
    chat_id: int | str,
    target_url: str,
    start_idx: int | None = None,
    end_idx: int | None = None,
    is_last_n: bool = False,
    status_msg=None,
    user_id: int | str = None,
    listing_title: str | None = None,
):
    """
    Worker to scrape and deliver videos or photo albums from MMSVibex listings.
    Supports slicing (start_idx, end_idx, is_last_n), in-place status cards, and cancellation.
    """
    cid = int(chat_id)
    uid = user_id or cid
    if is_chat_busy(cid):
        txt = "<blockquote>⚠️ Another scrape is currently running in this chat. Use /stop first.</blockquote>"
        if status_msg:
            try:
                await status_msg.edit_text(txt, parse_mode=ParseMode.HTML)
            except Exception:
                await bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.HTML)
        return

    start_scrape_for_chat(cid)
    try:
        title = listing_title or ("MMSVibex Photo Albums" if "/photos" in target_url else "MMSVibex Latest Videos")
        limit = max(end_idx or 10, 25)
        loading_text = (
            "<blockquote>"
            f"⚡ <b>{html.escape(title)}</b>\n"
            "⏳ <i>Scanning listing items...</i>"
            "</blockquote>"
        )
        if status_msg:
            try:
                await status_msg.edit_text(loading_text, parse_mode=ParseMode.HTML)
            except Exception:
                status_msg = await bot.send_message(chat_id=cid, text=loading_text, parse_mode=ParseMode.HTML)
        else:
            status_msg = await bot.send_message(chat_id=cid, text=loading_text, parse_mode=ParseMode.HTML)

        items = await asyncio.to_thread(get_mmsvibex_listing_items, target_url, page=1, limit=limit)
        items = apply_slice(items, start_idx=start_idx, end_idx=end_idx, is_last_n=is_last_n)

        if not items:
            await status_msg.edit_text(
                f"<blockquote>⚡ <b>{html.escape(title)}</b>\n❌ No items found.</blockquote>",
                parse_mode=ParseMode.HTML,
            )
            return

        stop_markup = build_stop_keyboard()
        await status_msg.edit_text(
            f"<blockquote>⚡ <b>{html.escape(title)}</b>\n"
            f"🔢 Found {len(items)} items. Extracting direct links...</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=stop_markup,
        )

        for idx, it in enumerate(items, 1):
            if is_scrape_cancelled(cid):
                await bot.send_message(
                    chat_id=cid,
                    text=f"<blockquote>🛑 <b>Scraping stopped!</b> Delivered {idx-1}/{len(items)} items.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
                break

            url = it["url"]
            if is_mmsvibex_photo_url(url):
                details = await asyncio.to_thread(get_mmsvibex_photo_details, url)
            else:
                details = await asyncio.to_thread(get_mmsvibex_video_details, url)

            await send_post_card(bot, cid, details, user_id=uid)
            if is_scrape_cancelled(cid):
                break
            await cancellable_sleep(POST_SEND_DELAY, cid)

        if not is_scrape_cancelled(cid):
            try:
                await status_msg.edit_text(
                    f"<blockquote>✅ <b>Extraction Complete!</b>\n⚡ Delivered: <b>{len(items)}</b> items</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_navigation_keyboard(),
                )
            except Exception:
                try:
                    await bot.send_message(
                        chat_id=cid,
                        text=f"<blockquote>✅ <b>Extraction Complete!</b>\n⚡ Delivered: <b>{len(items)}</b> items</blockquote>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_navigation_keyboard(),
                    )
                except Exception:
                    pass
        else:
            try:
                await status_msg.delete()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error in run_mmsvibex_listing_scrape: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"<blockquote>❌ Error: {html.escape(str(e))}</blockquote>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    finally:
        end_scrape_for_chat(cid)


async def run_wp_listing_scrape(
    bot,
    chat_id: int | str,
    target_url: str,
    start_idx: int | None = None,
    end_idx: int | None = None,
    is_last_n: bool = False,
    status_msg=None,
    user_id: int | str = None,
    listing_title: str | None = None,
):
    """
    Worker to scrape and deliver posts from WordPress locker/tube sites (Omaal63, DesiJugar, GulabiHub).
    Supports slicing (start_idx, end_idx, is_last_n), in-place status cards, and cancellation.
    """
    cid = int(chat_id)
    uid = user_id or cid
    if is_chat_busy(cid):
        txt = "<blockquote>⚠️ Another scrape is currently running in this chat. Use /stop first.</blockquote>"
        if status_msg:
            try:
                await status_msg.edit_text(txt, parse_mode=ParseMode.HTML)
            except Exception:
                await bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=cid, text=txt, parse_mode=ParseMode.HTML)
        return

    start_scrape_for_chat(cid)
    try:
        domain = urlparse(target_url).netloc.lower().replace("www.", "")
        title = listing_title or f"{domain.capitalize()} Latest Drops"
        limit = max(end_idx or 10, 25)
        loading_text = (
            "<blockquote>"
            f"🌐 <b>{html.escape(title)}</b>\n"
            "⏳ <i>Scanning posts...</i>"
            "</blockquote>"
        )
        if status_msg:
            try:
                await status_msg.edit_text(loading_text, parse_mode=ParseMode.HTML)
            except Exception:
                status_msg = await bot.send_message(chat_id=cid, text=loading_text, parse_mode=ParseMode.HTML)
        else:
            status_msg = await bot.send_message(chat_id=cid, text=loading_text, parse_mode=ParseMode.HTML)

        posts = await asyncio.to_thread(get_wp_listing_posts, target_url, page=1, limit=limit)
        posts = apply_slice(posts, start_idx=start_idx, end_idx=end_idx, is_last_n=is_last_n)

        if not posts:
            await status_msg.edit_text(
                f"<blockquote>🌐 <b>{html.escape(title)}</b>\n❌ No posts found.</blockquote>",
                parse_mode=ParseMode.HTML,
            )
            return

        stop_markup = build_stop_keyboard()
        await status_msg.edit_text(
            f"<blockquote>🌐 <b>{html.escape(title)}</b>\n"
            f"🔢 Found {len(posts)} posts. Extracting streaming links...</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=stop_markup,
        )

        for idx, p in enumerate(posts, 1):
            if is_scrape_cancelled(cid):
                await bot.send_message(
                    chat_id=cid,
                    text=f"<blockquote>🛑 <b>Scraping stopped!</b> Delivered {idx-1}/{len(posts)} posts.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
                break

            details = await asyncio.to_thread(get_wp_post_details, p["url"])
            await send_post_card(bot, cid, details, user_id=uid)
            if is_scrape_cancelled(cid):
                break
            await cancellable_sleep(POST_SEND_DELAY, cid)

        if not is_scrape_cancelled(cid):
            try:
                await status_msg.edit_text(
                    f"<blockquote>✅ <b>Extraction Complete!</b>\n🌐 Delivered: <b>{len(posts)}</b> posts</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_navigation_keyboard(),
                )
            except Exception:
                try:
                    await bot.send_message(
                        chat_id=cid,
                        text=f"<blockquote>✅ <b>Extraction Complete!</b>\n🌐 Delivered: <b>{len(posts)}</b> posts</blockquote>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_navigation_keyboard(),
                    )
                except Exception:
                    pass
        else:
            try:
                await status_msg.delete()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error in run_wp_listing_scrape: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"<blockquote>❌ Error: {html.escape(str(e))}</blockquote>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    finally:
        end_scrape_for_chat(cid)



# --- Command Handlers ---

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


async def setlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow user to choose which links to include in LiveCam video cards."""
    user = update.effective_user
    uid = user.id if user else update.effective_chat.id

    if context.args:
        chosen = context.args[0].lower().strip()
        if chosen in ["streaming", "stream", "embed"]:
            mode = "streaming"
        elif chosen in ["both", "all", "2"]:
            mode = "both"
        elif chosen in ["page", "video", "1"]:
            mode = "page"
        else:
            mode = None

        if mode:
            db.set_user_link_mode(uid, mode)
            label = "🍿 Streaming Only (Default)" if mode == "streaming" else ("🔗 Both (Page + Stream)" if mode == "both" else "🌐 Video Page Only")
            await update.effective_message.reply_text(
                f"✅ <b>LiveCam Link Mode Updated to {label}!</b>\n\n"
                "All future LiveCam video cards will use this link format.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_link_mode_keyboard(mode),
            )
            return

    current_mode = db.get_user_link_mode(uid) or "streaming"
    label = "🍿 Streaming Only (Default)" if current_mode == "streaming" else ("🔗 Both (Page + Stream)" if current_mode == "both" else "🌐 Video Page Only")
    text = (
        "⚙️ <b>LiveCam Link Display Settings</b>\n\n"
        f"Current format: <b>{label}</b>\n\n"
        "Choose which link(s) to include in LiveCam video cards:\n\n"
        "• <b>🍿 Streaming Only (Default):</b> Direct embed link only (cleanest)\n"
        "• <b>🔗 Both:</b> Video page link + Direct streaming link\n"
        "• <b>🌐 Video Page Only:</b> Video page link only"
    )
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_link_mode_keyboard(current_mode),
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Minimal, elegant greeting."""
    user_name = update.effective_user.first_name if update.effective_user else "Friend"
    text = messages.get_welcome_message(user_name=user_name, bot_name=BOT_NAME)
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=build_main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clean usage guide."""
    await update.effective_message.reply_text(messages.get_help_message(), parse_mode=ParseMode.HTML)


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
                await send_livecam_card(context.bot, chat_id, details, user_id=user_id)
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

        stop_markup = build_stop_keyboard()
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
                await process_livecam_scrape(context.bot, chat_id, v, user_id=user_id)
                if is_scrape_cancelled(chat_id):
                    break
                await cancellable_sleep(POST_SEND_DELAY, chat_id)
        finally:
            end_scrape_for_chat(chat_id)

        if not is_scrape_cancelled(chat_id):
            try:
                await status_msg.edit_text(
                    f"<blockquote>✅ <b>Extraction Complete!</b>\n📹 Delivered: <b>{len(videos)}</b> videos</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_navigation_keyboard(),
                )
            except Exception:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"<blockquote>✅ <b>Extraction Complete!</b>\n📹 Delivered: <b>{len(videos)}</b> videos</blockquote>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_navigation_keyboard(),
                    )
                except Exception:
                    pass
        else:
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
        if not is_scrape_cancelled(chat_id):
            try:
                await status_msg.edit_text(
                    "<blockquote>✅ <b>Extraction Complete!</b>\n🎬 Delivered: <b>1</b> topic</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_navigation_keyboard(),
                )
            except Exception:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="<blockquote>✅ <b>Extraction Complete!</b>\n🎬 Delivered: <b>1</b> topic</blockquote>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_navigation_keyboard(),
                    )
                except Exception:
                    pass
        else:
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

    stop_markup = build_stop_keyboard()
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

    if not is_scrape_cancelled(chat_id):
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"<blockquote>✅ <b>Extraction Complete!</b>\n📁 Delivered: <b>{len(topics)}</b> topics</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_navigation_keyboard(),
            )
        except Exception:
            pass

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


async def send_resurfaced_active_listing(bot, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Re-surface the active search or category listing at the bottom of the chat after a post is delivered.
    Marks the delivered post with a checkmark and shows remaining clickable buttons without requiring
    the user to scroll back up.
    """
    if not hasattr(context, "user_data") or not isinstance(context.user_data, dict):
        return False

    active = context.user_data.get("active_listing")
    if not active or not isinstance(active, dict) or not active.get("items"):
        return False

    delivered_ids = active.setdefault("delivered_ids", set())
    items = active.get("items", [])
    title = active.get("title", "Active Results")

    text = f"<blockquote>📋 <b>{html.escape(str(title))}</b>\n\n"
    buttons = []

    for idx, itm in enumerate(items, start=1):
        if not isinstance(itm, dict):
            continue
        sid = itm.get("short_id")
        itm_title = html.escape(str(itm.get("title", "Item")))
        if sid in delivered_ids:
            text += f"✅ {idx}. {itm_title} <i>(Delivered)</i>\n"
        else:
            text += f"👉 {idx}. {itm_title}\n"
            btn = InlineKeyboardButton(f"🎬 Extract #{idx}", callback_data=f"sc_{sid}")
            buttons.append([btn])

    text += "</blockquote>"

    # Multi-page pagination controls if applicable
    p = active.get("page", 1)
    tp = active.get("total_pages", 1)
    plat = active.get("platform", "fm")
    if isinstance(tp, int) and tp > 1:
        nav_row = []
        if isinstance(p, int) and p > 1:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sp_p:{plat}:{p-1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {p}/{tp}", callback_data="noop"))
        if isinstance(p, int) and p < tp:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"sp_p:{plat}:{p+1}"))
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton("🔍 New Search", callback_data="cb_search"),
        InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
    ])

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return True
    except Exception as e:
        logger.warning(f"Error sending resurfaced active listing: {e}")
        return False


async def execute_platform_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    plat: str,
    query: str,
    edit_msg=None,
    page: int = 1,
):
    """Execute search on the selected platform with total counts and multi-page pagination."""
    clean_query = query.strip()
    if not clean_query:
        if edit_msg:
            await edit_msg.edit_text("⚠️ Search query cannot be empty.")
        else:
            await update.effective_message.reply_text("⚠️ Search query cannot be empty.")
        return

    plat_names = {
        "lc": "LiveCam Models",
        "fm": "DropMMS Forum",
        "mmst": "MMSTown Forum",
        "vibex": "MMSVibex Videos",
        "wplock": "WordPress Lockers",
    }
    plat_label = plat_names.get(plat, "Platform")
    status_text = f"🔍 <i>Searching {plat_label} for '<b>{html.escape(clean_query)}</b>' (Page {page})...</i>"

    if edit_msg:
        try:
            status_msg = await edit_msg.edit_text(status_text, parse_mode=ParseMode.HTML)
        except Exception:
            status_msg = await update.effective_message.reply_text(status_text, parse_mode=ParseMode.HTML)
    else:
        status_msg = await update.effective_message.reply_text(status_text, parse_mode=ParseMode.HTML)

    if plat == "lc":
        try:
            results = await asyncio.to_thread(search_livecam_models, clean_query, 8)
        except Exception as e:
            await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
            return

        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Search LiveCam Again", callback_data="sp_choose:lc")],
                [InlineKeyboardButton("💬 Search DropMMS Instead", callback_data="sp_switch:fm")],
                [InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"❌ No LiveCam models found for <b>{html.escape(clean_query)}</b>.\n\n"
                "<i>Tip: Check spelling or try a shorter name.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        text = f"🔎 <b>LiveCam Models Matching '{html.escape(clean_query)}':</b>\n\n"
        buttons = []
        for idx, m in enumerate(results, start=1):
            name = m["name"]
            url = m["url"]
            text += f"{idx}. <b>{html.escape(name)}</b>\n"
            short_id = db.get_or_create_short_id(url)
            btn = InlineKeyboardButton(f"📹 {name}", callback_data=f"sp_mdl:{short_id}")
            buttons.append([btn])

        buttons.append([
            InlineKeyboardButton("🔄 New Search", callback_data="cb_search"),
            InlineKeyboardButton("📁 Change Platform", callback_data="cb_search"),
        ])
        buttons.append([
            InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ])
        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif plat == "vibex":
        try:
            results = await asyncio.to_thread(search_mmsvibex, clean_query, 8)
        except Exception as e:
            await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
            return

        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Search MMSVibex Again", callback_data="sp_choose:vibex")],
                [InlineKeyboardButton("🔙 Back to Search", callback_data="cb_search")],
                [InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"❌ No MMSVibex videos found for <b>{html.escape(clean_query)}</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        text = f"🔎 <b>MMSVibex Videos Matching '{html.escape(clean_query)}':</b>\n\n"
        buttons = []
        items_for_active = []
        for idx, r in enumerate(results, start=1):
            short_id = db.get_or_create_short_id(r["url"])
            text += f"{idx}. <b>{html.escape(r['title'])}</b>\n"
            btn = InlineKeyboardButton(f"⚡ Extract #{idx}", callback_data=f"sc_{short_id}")
            buttons.append([btn])
            items_for_active.append({
                "title": r["title"],
                "url": r["url"],
                "short_id": short_id,
            })

        context.user_data["active_listing"] = {
            "title": f"MMSVibex: '{clean_query}'",
            "type": "search",
            "platform": "vibex",
            "query": clean_query,
            "page": 1,
            "total_pages": 1,
            "items": items_for_active,
            "delivered_ids": set(),
        }

        buttons.append([
            InlineKeyboardButton("🔄 New Search", callback_data="cb_search"),
            InlineKeyboardButton("📁 Change Platform", callback_data="cb_search"),
        ])
        buttons.append([
            InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ])
        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif plat == "wplock":
        try:
            search_url = f"https://desijugar.me/?s={quote_plus(clean_query)}"
            results = await asyncio.to_thread(get_wp_listing_posts, search_url, page, 8)
        except Exception as e:
            await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
            return

        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Search Again", callback_data="sp_choose:wplock")],
                [InlineKeyboardButton("🔙 Back to Search", callback_data="cb_search")],
                [InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"❌ No locker posts found for <b>{html.escape(clean_query)}</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        text = f"🔎 <b>WordPress Locker Posts Matching '{html.escape(clean_query)}':</b>\n\n"
        buttons = []
        items_for_active = []
        for idx, r in enumerate(results, start=1):
            short_id = db.get_or_create_short_id(r["url"])
            text += f"{idx}. <b>{html.escape(r['title'])}</b>\n"
            btn = InlineKeyboardButton(f"🌐 Extract #{idx}", callback_data=f"sc_{short_id}")
            buttons.append([btn])
            items_for_active.append({
                "title": r["title"],
                "url": r["url"],
                "short_id": short_id,
            })

        context.user_data["active_listing"] = {
            "title": f"WordPress: '{clean_query}'",
            "type": "search",
            "platform": "wplock",
            "query": clean_query,
            "page": page,
            "total_pages": 1,
            "items": items_for_active,
            "delivered_ids": set(),
        }

        buttons.append([
            InlineKeyboardButton("🔄 New Search", callback_data="cb_search"),
            InlineKeyboardButton("📁 Change Platform", callback_data="cb_search"),
        ])
        buttons.append([
            InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
            InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
        ])
        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    else:
        # Forum search (DropMMS or MMSTown) with advanced parameters & total counts
        base_search_url = "https://mmstown.com" if plat == "mmst" else BASE_URL
        try:
            search_res = await asyncio.to_thread(
                search_forum_advanced, clean_query, page, 6, "titles", "relevancy", base_search_url
            )
            results = search_res.get("topics", [])
            total_count = search_res.get("total_count", len(results))
            total_pages = search_res.get("total_pages", 1)
        except Exception as e:
            await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
            return

        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔄 Search {plat_label} Again", callback_data=f"sp_choose:{plat}")],
                [InlineKeyboardButton("🔙 Back to Search", callback_data="cb_search")],
                [InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"❌ No topics found on {plat_label} for <b>{html.escape(clean_query)}</b>.\n\n"
                "<i>Tip: Check spelling or try a broader keyword.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        count_str = f"Found {total_count} Topics" if total_count else "Available"
        text = (
            "<blockquote>"
            f"🔎 <b>{plat_label} Results</b>\n"
            f"🎯 <b>Query:</b> <code>{html.escape(clean_query)}</code>\n"
            f"📊 <b>Total:</b> {count_str}"
        )
        if total_pages > 1:
            text += f" (Page {page}/{total_pages})"
        text += "</blockquote>\n\n"

        buttons = []
        items_for_active = []
        for idx, r in enumerate(results, start=1):
            short_id = db.get_or_create_short_id(r["url"])
            text += f"{idx}. <b>{html.escape(r['title'])}</b>\n"
            btn = InlineKeyboardButton(f"🎬 Extract #{idx}", callback_data=f"sc_{short_id}")
            buttons.append([btn])
            items_for_active.append({
                "title": r["title"],
                "url": r["url"],
                "short_id": short_id,
            })

        context.user_data["active_listing"] = {
            "title": f"{plat_label}: '{clean_query}'",
            "type": "search",
            "platform": plat,
            "query": clean_query,
            "page": page,
            "total_pages": total_pages,
            "items": items_for_active,
            "delivered_ids": set(),
        }

        # Multi-page pagination
        if total_pages > 1:
            nav_row = []
            if page > 1:
                nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sp_p:{plat}:{page-1}"))
            nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
            if page < total_pages:
                nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"sp_p:{plat}:{page+1}"))
            buttons.append(nav_row)

        # Cross-platform search switcher tabs
        tab_row = []
        if plat != "fm":
            tab_row.append(InlineKeyboardButton("💬 DropMMS", callback_data="sp_switch:fm"))
        if plat != "mmst":
            tab_row.append(InlineKeyboardButton("💬 MMSTown", callback_data="sp_switch:mmst"))
        if plat != "vibex":
            tab_row.append(InlineKeyboardButton("⚡ MMSVibex", callback_data="sp_switch:vibex"))
        if plat != "lc":
            tab_row.append(InlineKeyboardButton("📹 LiveCam", callback_data="sp_switch:lc"))
        if tab_row:
            buttons.append(tab_row)

        buttons.append([
            InlineKeyboardButton("🔄 New Search", callback_data="cb_search"),
            InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
        ])
        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Interactive universal search engine with direct keyword prompt & platform tabs."""
    msg = update.effective_message
    query = " ".join(context.args).strip() if (context.args and len(context.args) > 0) else ""

    if not query:
        context.user_data["awaiting_search"] = "prompt"
        markup = build_search_platform_keyboard()
        card_text = messages.msg_universal_search_prompt()
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    card_text, parse_mode=ParseMode.HTML, reply_markup=markup
                )
            except Exception:
                await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        else:
            await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    context.user_data["search_query"] = query
    markup = build_search_execute_platform_keyboard()
    reply_text = messages.msg_search_query_prompt(query)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                reply_text, parse_mode=ParseMode.HTML, reply_markup=markup
            )
        except Exception:
            await msg.reply_text(reply_text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await msg.reply_text(
            reply_text, parse_mode=ParseMode.HTML, reply_markup=markup
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

async def process_topic_scrape(bot, chat_id: int | str, url: str, user_id: int = None, topic_meta: dict = None):
    """Scrape and deliver single topic card with cancellation support across all supported sites."""
    if is_scrape_cancelled(chat_id):
        return
    try:
        if is_mmsvibex_photo_url(url):
            details = await asyncio.to_thread(get_mmsvibex_photo_details, url)
        elif is_mmsvibex_video_url(url):
            details = await asyncio.to_thread(get_mmsvibex_video_details, url)
        elif is_wp_locker_post_url(url):
            details = await asyncio.to_thread(get_wp_post_details, url)
        else:
            details = await asyncio.to_thread(get_post_details, url)

        if topic_meta:
            if topic_meta.get("date_ist") and not details.get("date_ist"):
                details["date_ist"] = topic_meta["date_ist"]
            if topic_meta.get("date") and not details.get("date"):
                details["date"] = topic_meta["date"]
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
            "• <code>/scrape https://mmstown.com/topic/62375-title/</code>\n"
            "• <code>/scrape https://mmsvibex.life/video-title/</code>\n"
            "• <code>/scrape https://omaal63.net/post-title/</code>\n"
            "• <code>/scrape https://desijugar.me/2026/11/22/title/</code>\n"
            "• <code>/scrape https://dropmms.com/forum/2-general/ 5</code>\n"
            "• <code>/scrape https://livecamrips.to/model/36773/GoddessAnna 4</code>",
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
        if any(
            d in target_url.lower()
            for d in [
                "dropmms.com",
                "mmstown.com",
                "mmsvibex.life",
                "gulabihub.com",
                "omaal63.net",
                "desijugar.me",
                "livecamrips.to",
            ]
        ):
            target_url = f"https://{target_url}"
        else:
            return

    logger.info(f"🔗 [handle_raw_url] Chat {chat_id} (User: {user_id}) - Target URL: {target_url} | Slice: start={start_idx}, end={end_idx}, is_last_n={is_last_n}")
    start_scrape_for_chat(chat_id)

    # 1. MMSVibex Photo Album
    if is_mmsvibex_photo_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting MMSVibex photo album & ZIP download...</i>", parse_mode=ParseMode.HTML)
        try:
            details = await asyncio.to_thread(get_mmsvibex_photo_details, target_url)
            await send_post_card(context.bot, chat_id, details, user_id=user_id)
        except Exception as e:
            await status.edit_text(f"❌ Error extracting photo album: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 2. MMSVibex Single Video
    if is_mmsvibex_video_url(target_url):
        status = await msg.reply_text("🔍 <i>Inspecting MMSVibex video & collection...</i>", parse_mode=ParseMode.HTML)
        try:
            details = await asyncio.to_thread(get_mmsvibex_video_details, target_url)
            col_url = details.get("collection_url")

            if col_url:
                short_id = db.get_or_create_short_id(target_url)
                context.user_data[f"mv_dt_{short_id}"] = details

                mode_markup = build_mmsvibex_mode_keyboard(short_id)
                card_title = details.get("title", "Video")
                prompt_text = messages.msg_mmsvibex_video_prompt(card_title)
                await status.edit_text(prompt_text, parse_mode=ParseMode.HTML, reply_markup=mode_markup)
                end_scrape_for_chat(chat_id)
                return
            else:
                await send_post_card(context.bot, chat_id, details, user_id=user_id)
        except Exception as e:
            await status.edit_text(f"❌ Error extracting MMSVibex video: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 3. MMSVibex Listing / Archive
    if is_mmsvibex_listing_url(target_url):
        end_scrape_for_chat(chat_id)
        if start_idx is not None or end_idx is not None or is_last_n:
            await run_mmsvibex_listing_scrape(
                bot=context.bot,
                chat_id=chat_id,
                target_url=target_url,
                start_idx=start_idx,
                end_idx=end_idx,
                is_last_n=is_last_n,
                user_id=user_id,
            )
            return

        title = "MMSVibex Photo Albums" if "/photos" in target_url else "MMSVibex Videos"
        short_id = db.get_or_create_short_id(target_url)
        context.user_data[f"vibex_url_{short_id}"] = target_url
        context.user_data["awaiting_vibex_range"] = {
            "url": target_url,
            "sort_key": "custom",
            "sort_label": title,
            "chat_id": chat_id,
            "message_id": None,
        }
        markup = build_slice_selection_keyboard(short_id, [5, 10, 20], prefix="sp_vrun")
        card_text = format_listing_menu_card(title, is_category=False)
        s_msg = await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["awaiting_vibex_range"]["message_id"] = s_msg.message_id
        return

    # 4. WordPress Locker Post (Omaal63, DesiJugar, GulabiHub)
    if is_wp_locker_post_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting streaming links...</i>", parse_mode=ParseMode.HTML)
        try:
            details = await asyncio.to_thread(get_wp_post_details, target_url)
            await send_post_card(context.bot, chat_id, details, user_id=user_id)
        except Exception as e:
            await status.edit_text(f"❌ Error extracting post: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 5. WordPress Locker Listing / Archive (Omaal63, DesiJugar, GulabiHub)
    if is_wp_locker_listing_url(target_url):
        end_scrape_for_chat(chat_id)
        if start_idx is not None or end_idx is not None or is_last_n:
            await run_wp_listing_scrape(
                bot=context.bot,
                chat_id=chat_id,
                target_url=target_url,
                start_idx=start_idx,
                end_idx=end_idx,
                is_last_n=is_last_n,
                user_id=user_id,
            )
            return

        domain = urlparse(target_url).netloc.lower().replace("www.", "")
        title = f"{domain.capitalize()} Archive"
        short_id = db.get_or_create_short_id(target_url)
        context.user_data[f"wp_url_{short_id}"] = target_url
        context.user_data["awaiting_wp_range"] = {
            "url": target_url,
            "site_key": "custom",
            "site_name": title,
            "chat_id": chat_id,
            "message_id": None,
        }
        markup = build_slice_selection_keyboard(short_id, [5, 10, 20], prefix="sp_wprun_id")
        card_text = format_listing_menu_card(title, is_category=True)
        s_msg = await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["awaiting_wp_range"]["message_id"] = s_msg.message_id
        return

    # 1. LiveCamRips Single Video
    if is_livecam_video_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting LiveCam video streaming link...</i>", parse_mode=ParseMode.HTML)
        try:
            details = await asyncio.to_thread(get_livecam_video_details, target_url)
            await send_livecam_card(context.bot, chat_id, details, user_id=user_id)
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
        if start_idx is not None or end_idx is not None or is_last_n:
            end_scrape_for_chat(chat_id)
            await run_livecam_model_scrape(
                bot=context.bot,
                chat_id=chat_id,
                target_url=target_url,
                start_idx=start_idx or 1,
                end_idx=end_idx,
                req_limit=(end_idx if (start_idx is None and end_idx) else None),
                user_id=user_id,
            )
            return

        end_scrape_for_chat(chat_id)
        clean_u = target_url.split("?")[0].split("#")[0].rstrip("/")
        parts = [p for p in clean_u.split("/") if p]
        if parts and parts[-1].isdigit() and len(parts) >= 2 and not parts[-2].isdigit() and parts[-2] != "model":
            clean_u = "/".join(clean_u.split("/")[:-1])
            parts = [p for p in clean_u.split("/") if p]

        model_name = clean_livecam_title(parts[-1] if parts else "Model")
        short_id = db.get_or_create_short_id(clean_u)

        init_text = (
            "<blockquote>"
            f"📹 <b>{html.escape(model_name)}</b>\n"
            "⏳ <i>Loading model information...</i>"
            "</blockquote>"
        )
        status_msg = await msg.reply_text(init_text, parse_mode=ParseMode.HTML)
        stats = await asyncio.to_thread(get_livecam_model_stats, clean_u)
        model_name = stats.get("name") or model_name
        total_str = stats.get("total_videos_str") or "Available"

        context.user_data[f"model_stats_{short_id}"] = {
            "name": model_name,
            "total_str": total_str,
            "url": stats.get("url") or clean_u,
        }

        markup = build_model_sort_keyboard(short_id)

        card_text = (
            "<blockquote>"
            f"📹 <b>{html.escape(model_name)}</b>\n"
            f"📊 <b>Total Videos:</b> {total_str}"
            "</blockquote>"
        )
        await status_msg.edit_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
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
        end_scrape_for_chat(chat_id)
        if start_idx is not None or end_idx is not None or is_last_n:
            await run_forum_category_scrape(
                bot=context.bot,
                chat_id=chat_id,
                target_url=target_url,
                start_idx=start_idx,
                end_idx=end_idx,
                is_last_n=is_last_n,
                user_id=user_id,
            )
            return

        # No slice provided: show interactive category card with 2 sorting options!
        clean_u = target_url.split("?")[0].split("#")[0].rstrip("/")
        parts = [p for p in clean_u.split("/") if p]
        raw_slug = parts[-1] if parts else "Forum"
        if raw_slug.isdigit() and len(parts) >= 2 and parts[-2] == "page":
            raw_slug = parts[-3] if len(parts) >= 3 else "Forum"
        cat_title = re.sub(r"^\d+-", "", raw_slug).replace("-", " ").title() or "Forum Category"
        short_id = db.get_or_create_short_id(clean_u)

        init_text = (
            "<blockquote>"
            f"💬 <b>{html.escape(cat_title)}</b>\n"
            "⏳ <i>Loading category information...</i>"
            "</blockquote>"
        )
        status_msg = await msg.reply_text(init_text, parse_mode=ParseMode.HTML)
        stats = await asyncio.to_thread(get_dropmms_category_stats, clean_u)
        cat_title = stats.get("title") or cat_title
        total_str = stats.get("total_topics_str") or "Available"

        context.user_data[f"cat_stats_{short_id}"] = {
            "title": cat_title,
            "total_str": total_str,
            "url": stats.get("url") or clean_u,
        }

        markup = build_forum_sort_keyboard(short_id)

        card_text = (
            "<blockquote>"
            f"💬 <b>{html.escape(cat_title)}</b>\n"
            f"📊 <b>Total Topics:</b> {total_str}"
            "</blockquote>"
        )
        await status_msg.edit_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    # 5. Universal Fallback for any other valid HTTP/HTTPS URL
    if target_url.startswith("http://") or target_url.startswith("https://"):
        status = await msg.reply_text("🌐 <i>Analyzing webpage with Universal Scraper...</i>", parse_mode=ParseMode.HTML)
        try:
            details = await asyncio.to_thread(get_universal_post_details, target_url)
            if details.get("streaming_links"):
                await send_post_card(context.bot, chat_id, details, user_id=user_id)
            else:
                await status.edit_text(
                    "<blockquote>⚠️ <b>Universal Engine:</b> No streaming video embeds or direct media files were found on this page.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
                return
        except Exception as e:
            await status.edit_text(f"❌ Universal extraction note: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    end_scrape_for_chat(chat_id)
    await msg.reply_text("❓ Please send a valid URL to extract media.", parse_mode=ParseMode.HTML)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Filter and handle plain text messages containing links or control keywords."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    logger.info(f"📩 [handle_message] Received text from Chat {update.effective_chat.id} (User: {update.effective_user.id if update.effective_user else None}): {text!r}")

    # 1. Interactive Model Range Input Flow
    model_flow = context.user_data.get("awaiting_model_range")
    if model_flow:
        sort_labels = {
            "newest": "Newest",
            "most_viewed": "Most Viewed",
            "most_liked": "Most Liked",
            "oldest": "Oldest",
        }
        if text.lower() in ["stop", "cancel", "/stop", "/cancel", "halt"]:
            context.user_data.pop("awaiting_model_range", None)
            try:
                await update.effective_message.delete()
            except Exception:
                pass
            try:
                await context.bot.edit_message_text(
                    chat_id=model_flow["chat_id"],
                    message_id=model_flow["message_id"],
                    text="<blockquote>❌ Model extraction cancelled.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return

        start_idx, end_idx, page_num = parse_model_range_input(text)
        if start_idx is None and end_idx is None and page_num is None:
            try:
                await update.effective_message.delete()
            except Exception:
                pass
            sort_label = sort_labels.get(model_flow.get("sort_by", "newest"), "Newest")
            invalid_text = (
                "<blockquote>"
                f"📹 <b>{html.escape(model_flow.get('model_name', 'Model'))}</b>\n"
                f"📊 <b>Total Videos:</b> {model_flow.get('total_str', 'Available')}\n"
                f"🎯 <b>Sort:</b> {sort_label}\n\n"
                f"⚠️ <b>Invalid format:</b> <code>{html.escape(text)}</code>\n"
                "Please enter a valid count, range, or page:\n"
                "• <code>5</code> ➔ First 5 videos\n"
                "• <code>1-5</code> ➔ Videos 1 to 5\n"
                "• <code>5-10</code> ➔ Videos 5 to 10\n"
                "• <code>page 1</code> ➔ Full Page 1"
                "</blockquote>"
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔙 Back", callback_data=f"sp_mdl:{model_flow['short_id']}"),
                    InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
                ]
            ])
            try:
                await context.bot.edit_message_text(
                    chat_id=model_flow["chat_id"],
                    message_id=model_flow["message_id"],
                    text=invalid_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            except Exception:
                pass
            return

        # Valid input provided: clean up state and user message
        context.user_data.pop("awaiting_model_range", None)
        try:
            await update.effective_message.delete()
        except Exception:
            pass

        sort_label = sort_labels.get(model_flow.get("sort_by", "newest"), "Newest")
        if page_num is not None:
            range_label = f"Page {page_num}"
        elif end_idx is not None:
            range_label = f"{start_idx} to {end_idx}"
        else:
            range_label = "Top 50"

        loading_text = (
            "<blockquote>"
            f"📹 <b>{html.escape(model_flow.get('model_name', 'Model'))}</b>\n"
            f"🎯 <b>Sort:</b> {sort_label}\n"
            f"🔢 <b>Range:</b> {range_label}\n"
            "⏳ <b>Status:</b> Scanning model page...</blockquote>"
        )
        stop_markup = build_stop_keyboard()

        try:
            status_msg = await context.bot.edit_message_text(
                chat_id=model_flow["chat_id"],
                message_id=model_flow["message_id"],
                text=loading_text,
                parse_mode=ParseMode.HTML,
                reply_markup=stop_markup,
            )
        except Exception:
            status_msg = None

        await run_livecam_model_scrape(
            bot=context.bot,
            chat_id=model_flow["chat_id"],
            target_url=model_flow["url"],
            sort_by=model_flow.get("sort_by", "newest"),
            start_idx=start_idx or 1,
            end_idx=end_idx,
            page_num=page_num,
            status_msg=status_msg,
            user_id=update.effective_user.id if update.effective_user else None,
        )
        return

    # 2. Interactive Category Range Input Flow
    cat_flow = context.user_data.get("awaiting_category_range")
    if cat_flow:
        if text.lower() in ["stop", "cancel", "/stop", "/cancel", "halt"]:
            context.user_data.pop("awaiting_category_range", None)
            try:
                await update.effective_message.delete()
            except Exception:
                pass
            try:
                await context.bot.edit_message_text(
                    chat_id=cat_flow["chat_id"],
                    message_id=cat_flow["message_id"],
                    text="<blockquote>❌ Category extraction cancelled.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return

        lower_t = text.lower().strip()
        date_mode = None
        if lower_t in ["today", "aaj"]:
            date_mode = "today"
        elif lower_t in ["yesterday", "kal"]:
            date_mode = "yesterday"

        start_idx, end_idx, page_num = (None, None, None)
        if not date_mode:
            start_idx, end_idx, page_num = parse_model_range_input(text)

        if not date_mode and start_idx is None and end_idx is None and page_num is None:
            try:
                await update.effective_message.delete()
            except Exception:
                pass
            sort_val = cat_flow.get("sort_by", "start_date")
            invalid_text = (
                "<blockquote>"
                f"💬 <b>{html.escape(cat_flow.get('cat_title', 'Forum Category'))}</b>\n"
                f"🔗 <code>{html.escape(cat_flow.get('url', ''))}</code>\n\n"
                f"⚠️ <b>Invalid format:</b> <code>{html.escape(text)}</code>\n\n"
                "⚡ <b>Quick Filter by Date (IST):</b>\n"
                "Tap a button below or type:\n"
                "• <code>today</code> ➔ Today's uploads\n"
                "• <code>yesterday</code> ➔ Yesterday & Today\n\n"
                "✏️ <b>Or Enter Custom Range, Count or Page:</b>\n"
                "• <code>10</code> ➔ First 10 topics\n"
                "• <code>1-10</code> ➔ Topics 1 to 10\n"
                "• <code>10-20</code> ➔ Topics 10 to 20\n"
                "• <code>page 2</code> ➔ Full Page 2"
                "</blockquote>"
            )
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⚡ Today's Posts", callback_data=f"sp_cdate:{cat_flow['short_id']}:{sort_val}:today"),
                    InlineKeyboardButton("📆 Yesterday & Today", callback_data=f"sp_cdate:{cat_flow['short_id']}:{sort_val}:yesterday"),
                ],
                [
                    InlineKeyboardButton("🔙 Back", callback_data=f"sp_cat:{cat_flow['short_id']}"),
                    InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
                ]
            ])
            try:
                await context.bot.edit_message_text(
                    chat_id=cat_flow["chat_id"],
                    message_id=cat_flow["message_id"],
                    text=invalid_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            except Exception:
                pass
            return

        # Valid input provided: clean up state and user message
        context.user_data.pop("awaiting_category_range", None)
        try:
            await update.effective_message.delete()
        except Exception:
            pass

        if date_mode:
            range_label = "Today's Uploads (IST)" if date_mode == "today" else "Yesterday & Today (IST)"
        elif page_num is not None:
            range_label = f"Page {page_num}"
        elif end_idx is not None:
            range_label = f"{start_idx} to {end_idx}"
        else:
            range_label = "Top 25"

        sort_val = cat_flow.get("sort_by", "start_date")
        sort_label = "Upload Date (Start Date)" if sort_val == "start_date" else "Recently Updated"

        loading_text = (
            "<blockquote>"
            f"💬 <b>{html.escape(cat_flow.get('cat_title', 'Forum Category'))}</b>\n"
            f"🎯 <b>Sort:</b> {sort_label}\n"
            f"🔢 <b>Range:</b> {range_label}\n"
            "⏳ <b>Status:</b> Scanning forum category...</blockquote>"
        )
        stop_markup = build_stop_keyboard()

        try:
            status_msg = await context.bot.edit_message_text(
                chat_id=cat_flow["chat_id"],
                message_id=cat_flow["message_id"],
                text=loading_text,
                parse_mode=ParseMode.HTML,
                reply_markup=stop_markup,
            )
        except Exception:
            status_msg = None

        await run_forum_category_scrape(
            bot=context.bot,
            chat_id=cat_flow["chat_id"],
            target_url=cat_flow["url"],
            only_today=(date_mode == "today"),
            date_filter=date_mode,
            sort_by=sort_val,
            start_idx=start_idx if not date_mode else 1,
            end_idx=end_idx if not date_mode else None,
            page_num=page_num if not date_mode else None,
            status_msg=status_msg,
            user_id=update.effective_user.id if update.effective_user else None,
            cat_title=cat_flow.get("cat_title"),
        )
        return

    # 3. Interactive MMSVibex Range Input Flow
    vibex_flow = context.user_data.get("awaiting_vibex_range")
    if vibex_flow:
        if text.lower() in ["stop", "cancel", "/stop", "/cancel", "halt"]:
            context.user_data.pop("awaiting_vibex_range", None)
            try:
                await update.effective_message.delete()
            except Exception:
                pass
            if vibex_flow.get("message_id"):
                try:
                    await context.bot.edit_message_text(
                        chat_id=vibex_flow["chat_id"],
                        message_id=vibex_flow["message_id"],
                        text="<blockquote>❌ MMSVibex extraction cancelled.</blockquote>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            return

        start_idx, end_idx, page_num = parse_model_range_input(text)
        if start_idx is None and end_idx is None and page_num is None:
            try:
                await update.effective_message.delete()
            except Exception:
                pass
            invalid_text = (
                "<blockquote>"
                f"⚡ <b>{html.escape(vibex_flow.get('sort_label', 'MMSVibex'))}</b>\n\n"
                f"⚠️ <b>Invalid format:</b> <code>{html.escape(text)}</code>\n\n"
                "Please enter a valid count, range, or page:\n"
                "• <code>5</code> ➔ First 5 items\n"
                "• <code>1-10</code> ➔ Items 1 to 10\n"
                "• <code>page 2</code> ➔ Full Page 2"
                "</blockquote>"
            )
            if vibex_flow.get("message_id"):
                try:
                    await context.bot.edit_message_text(
                        chat_id=vibex_flow["chat_id"],
                        message_id=vibex_flow["message_id"],
                        text=invalid_text,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            return

        context.user_data.pop("awaiting_vibex_range", None)
        try:
            await update.effective_message.delete()
        except Exception:
            pass

        status_msg = None
        if vibex_flow.get("message_id"):
            try:
                status_msg = await context.bot.edit_message_text(
                    chat_id=vibex_flow["chat_id"],
                    message_id=vibex_flow["message_id"],
                    text=f"<blockquote>⚡ <b>{html.escape(vibex_flow.get('sort_label', 'MMSVibex'))}</b>\n⏳ <b>Status:</b> Scanning items...</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        await run_mmsvibex_listing_scrape(
            bot=context.bot,
            chat_id=vibex_flow["chat_id"],
            target_url=vibex_flow["url"],
            start_idx=start_idx or 1,
            end_idx=end_idx,
            status_msg=status_msg,
            user_id=update.effective_user.id if update.effective_user else None,
            listing_title=vibex_flow.get("sort_label", "MMSVibex Videos"),
        )
        return

    # 4. Interactive WordPress Locker Range Input Flow
    wp_flow = context.user_data.get("awaiting_wp_range")
    if wp_flow:
        if text.lower() in ["stop", "cancel", "/stop", "/cancel", "halt"]:
            context.user_data.pop("awaiting_wp_range", None)
            try:
                await update.effective_message.delete()
            except Exception:
                pass
            if wp_flow.get("message_id"):
                try:
                    await context.bot.edit_message_text(
                        chat_id=wp_flow["chat_id"],
                        message_id=wp_flow["message_id"],
                        text="<blockquote>❌ Extraction cancelled.</blockquote>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            return

        start_idx, end_idx, page_num = parse_model_range_input(text)
        if start_idx is None and end_idx is None and page_num is None:
            try:
                await update.effective_message.delete()
            except Exception:
                pass
            invalid_text = (
                "<blockquote>"
                f"🌐 <b>{html.escape(wp_flow.get('site_name', 'Archive'))}</b>\n\n"
                f"⚠️ <b>Invalid format:</b> <code>{html.escape(text)}</code>\n\n"
                "Please enter a valid count, range, or page:\n"
                "• <code>5</code> ➔ First 5 posts\n"
                "• <code>1-10</code> ➔ Posts 1 to 10\n"
                "• <code>page 2</code> ➔ Full Page 2"
                "</blockquote>"
            )
            if wp_flow.get("message_id"):
                try:
                    await context.bot.edit_message_text(
                        chat_id=wp_flow["chat_id"],
                        message_id=wp_flow["message_id"],
                        text=invalid_text,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            return

        context.user_data.pop("awaiting_wp_range", None)
        try:
            await update.effective_message.delete()
        except Exception:
            pass

        status_msg = None
        if wp_flow.get("message_id"):
            try:
                status_msg = await context.bot.edit_message_text(
                    chat_id=wp_flow["chat_id"],
                    message_id=wp_flow["message_id"],
                    text=f"<blockquote>🌐 <b>{html.escape(wp_flow.get('site_name', 'Archive'))}</b>\n⏳ <b>Status:</b> Scanning posts...</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        await run_wp_listing_scrape(
            bot=context.bot,
            chat_id=wp_flow["chat_id"],
            target_url=wp_flow["url"],
            start_idx=start_idx or 1,
            end_idx=end_idx,
            status_msg=status_msg,
            user_id=update.effective_user.id if update.effective_user else None,
            listing_title=wp_flow.get("site_name", "Archive Posts"),
        )
        return

    # Allow users to stop simply by typing 'stop' or 'cancel' without slash
    if text.lower() in ["stop", "cancel", "/stop", "/cancel", "halt"]:
        await stop_command(update, context)
        return

    # Check if user is in an interactive search flow
    awaiting_plat = context.user_data.pop("awaiting_search", None)
    if awaiting_plat:
        clean_text = text.strip()
        if awaiting_plat == "prompt":
            context.user_data["search_query"] = clean_text
            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💬 DropMMS", callback_data="sp_do:fm"),
                    InlineKeyboardButton("💬 MMSTown", callback_data="sp_do:mmst"),
                ],
                [
                    InlineKeyboardButton("⚡ MMSVibex", callback_data="sp_do:vibex"),
                    InlineKeyboardButton("📹 LiveCam", callback_data="sp_do:lc"),
                ],
                [
                    InlineKeyboardButton("🌐 WordPress Lockers", callback_data="sp_do:wplock"),
                ],
                [
                    InlineKeyboardButton("🏛️ Main Menu", callback_data="cb_main_menu"),
                    InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
                ],
            ])
            await update.effective_message.reply_text(
                f"🔍 <b>Search Query:</b> <code>{html.escape(clean_text)}</code>\n\n"
                "Choose a platform to search:",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return
        await execute_platform_search(update, context, awaiting_plat, clean_text)
        return

    if text.startswith("http://") or text.startswith("https://") or any(
        d in text.lower()
        for d in [
            "dropmms.com",
            "mmstown.com",
            "mmsvibex.life",
            "gulabihub.com",
            "omaal63.net",
            "desijugar.me",
            "livecamrips.to",
        ]
    ):
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
        await search_command(update, context)
    elif data in ("cb_main_menu", "cb_start"):
        await start_command(update, context)
    elif data.startswith("sp_choose:"):
        plat = data.split(":")[1]
        if plat == "fm":
            try:
                await query.edit_message_text(
                    "<blockquote>💬 <b>DropMMS Forums</b>\n⏳ <i>Fetching forum categories...</i></blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

            forums = await asyncio.to_thread(get_dropmms_forums)
            buttons = []
            for i in range(0, len(forums), 2):
                row = []
                f1 = forums[i]
                sid1 = db.get_or_create_short_id(f1["url"])
                context.user_data[f"cat_info_{sid1}"] = {"title": f1["title"], "url": f1["url"]}
                row.append(InlineKeyboardButton(f"📁 {f1['title']}", callback_data=f"sp_cat:{sid1}"))

                if i + 1 < len(forums):
                    f2 = forums[i + 1]
                    sid2 = db.get_or_create_short_id(f2["url"])
                    context.user_data[f"cat_info_{sid2}"] = {"title": f2["title"], "url": f2["url"]}
                    row.append(InlineKeyboardButton(f"📁 {f2['title']}", callback_data=f"sp_cat:{sid2}"))

                buttons.append(row)

            buttons.append([InlineKeyboardButton("🔍 Search Topics by Keyword", callback_data="sp_choose_kw:fm")])
            buttons.append([
                InlineKeyboardButton("🔙 Back", callback_data="cb_search"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ])

            card_text = (
                "<blockquote>"
                "💬 <b>DropMMS Forums</b>\n"
                "Select a forum category to browse or scrape:"
                "</blockquote>"
            )
            await query.edit_message_text(
                card_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

        elif plat == "mmst":
            try:
                await query.edit_message_text(
                    "<blockquote>💬 <b>MMSTown Forums</b>\n⏳ <i>Fetching forum categories...</i></blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

            forums = await asyncio.to_thread(get_mmstown_forums)
            buttons = []
            for i in range(0, len(forums), 2):
                row = []
                f1 = forums[i]
                sid1 = db.get_or_create_short_id(f1["url"])
                context.user_data[f"cat_info_{sid1}"] = {"title": f1["title"], "url": f1["url"]}
                row.append(InlineKeyboardButton(f"📁 {f1['title']}", callback_data=f"sp_cat:{sid1}"))

                if i + 1 < len(forums):
                    f2 = forums[i + 1]
                    sid2 = db.get_or_create_short_id(f2["url"])
                    context.user_data[f"cat_info_{sid2}"] = {"title": f2["title"], "url": f2["url"]}
                    row.append(InlineKeyboardButton(f"📁 {f2['title']}", callback_data=f"sp_cat:{sid2}"))

                buttons.append(row)

            buttons.append([InlineKeyboardButton("🔍 Search MMSTown Topics", callback_data="sp_choose_kw:mmst")])
            buttons.append([
                InlineKeyboardButton("🔙 Back", callback_data="cb_search"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ])

            card_text = (
                "<blockquote>"
                "💬 <b>MMSTown Forums</b>\n"
                "Select a forum category to browse or scrape:"
                "</blockquote>"
            )
            await query.edit_message_text(
                card_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

        elif plat == "vibex":
            buttons = [
                [
                    InlineKeyboardButton("⚡ Newest Videos", callback_data="sp_vsort:latest"),
                    InlineKeyboardButton("🔥 Most Viewed", callback_data="sp_vsort:most-viewed"),
                ],
                [
                    InlineKeyboardButton("⭐ Popular", callback_data="sp_vsort:popular"),
                    InlineKeyboardButton("⏱️ Longest", callback_data="sp_vsort:longest"),
                ],
                [
                    InlineKeyboardButton("📸 Photo Albums", callback_data="sp_vsort:photos"),
                    InlineKeyboardButton("🔍 Search Videos", callback_data="sp_choose_kw:vibex"),
                ],
                [
                    InlineKeyboardButton("🔙 Back", callback_data="cb_search"),
                    InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
                ],
            ]
            await query.edit_message_text(
                "<blockquote>⚡ <b>MMSVibex Hub</b>\nSelect sorting or browse category:</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

        elif plat == "wplock":
            buttons = [
                [
                    InlineKeyboardButton("📁 Omaal63", callback_data="sp_wpsite:omaal"),
                    InlineKeyboardButton("📁 DesiJugar", callback_data="sp_wpsite:desijugar"),
                ],
                [
                    InlineKeyboardButton("📁 GulabiHub", callback_data="sp_wpsite:gulabi"),
                ],
                [
                    InlineKeyboardButton("🔙 Back", callback_data="cb_search"),
                    InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
                ],
            ]
            await query.edit_message_text(
                "<blockquote>🌐 <b>WordPress Locker Hub</b>\nSelect a site to browse or scrape:</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

        plat_label = "📹 LiveCam Models"
        example_q = "GoddessAnna"
        context.user_data["awaiting_search"] = plat
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="cb_search"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            f"<blockquote>🔍 <b>Searching:</b> {plat_label}\n\n"
            f"✏️ <i>Please send the keyword or name in your next message (e.g. <code>{example_q}</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data == "sp_choose_kw:fm":
        context.user_data["awaiting_search"] = "fm"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:fm"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            "<blockquote>🔍 <b>Searching:</b> 💬 DropMMS Forum\n\n"
            "✏️ <i>Please send the keyword or title in your next message (e.g. <code>1080p video</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data == "sp_choose_kw:mmst":
        context.user_data["awaiting_search"] = "mmst"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:mmst"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            "<blockquote>🔍 <b>Searching:</b> 💬 MMSTown Forum\n\n"
            "✏️ <i>Please send the keyword or title in your next message (e.g. <code>desi video</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data == "sp_choose_kw:vibex":
        context.user_data["awaiting_search"] = "vibex"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:vibex"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            "<blockquote>🔍 <b>Searching:</b> ⚡ MMSVibex Videos\n\n"
            "✏️ <i>Please send the keyword or model name in your next message (e.g. <code>baddie</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data.startswith("sp_vsort:"):
        _, sort_key = data.split(":")
        v_sort_labels = {
            "latest": "Newest Videos",
            "most-viewed": "Most Viewed",
            "popular": "Popular",
            "longest": "Longest",
            "photos": "Photo Albums",
        }
        sort_label = v_sort_labels.get(sort_key, "Videos")
        target_url = "https://mmsvibex.life/photos/" if sort_key == "photos" else f"https://mmsvibex.life/?filter={sort_key}"
        context.user_data["awaiting_vibex_range"] = {
            "url": target_url,
            "sort_key": sort_key,
            "sort_label": f"MMSVibex: {sort_label}",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔝 Top 5", callback_data=f"sp_vapply:{sort_key}:1-5"),
                InlineKeyboardButton("🔝 Top 10", callback_data=f"sp_vapply:{sort_key}:1-10"),
                InlineKeyboardButton("🔝 Top 20", callback_data=f"sp_vapply:{sort_key}:1-20"),
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data="sp_choose:vibex"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ],
        ])
        card_text = (
            "<blockquote>"
            f"⚡ <b>MMSVibex: {sort_label}</b>\n\n"
            "Select quick count above or reply in chat with a custom range:\n"
            "• <code>5</code> ➔ First 5 items\n"
            "• <code>1-15</code> ➔ Items 1 to 15\n"
            "• <code>page 2</code> ➔ Full Page 2"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data.startswith("sp_vapply:"):
        _, sort_key, r_str = data.split(":")
        target_url = "https://mmsvibex.life/photos/" if sort_key == "photos" else f"https://mmsvibex.life/?filter={sort_key}"
        start_idx, end_idx, page_num = parse_model_range_input(r_str)
        context.user_data.pop("awaiting_vibex_range", None)
        await run_mmsvibex_listing_scrape(
            bot=context.bot,
            chat_id=query.message.chat_id,
            target_url=target_url,
            start_idx=start_idx or 1,
            end_idx=end_idx,
            status_msg=query.message,
            user_id=query.from_user.id,
            listing_title=f"MMSVibex ({sort_key})",
        )
        return

    elif data.startswith("sp_vrun:"):
        _, sid_str, lim_str = data.split(":")
        sid = int(sid_str)
        lim = int(lim_str)
        vurl = context.user_data.get(f"vibex_url_{sid}") or db.get_url_from_short_id(sid) or "https://mmsvibex.life/?filter=latest"
        context.user_data.pop("awaiting_vibex_range", None)
        await run_mmsvibex_listing_scrape(
            bot=context.bot,
            chat_id=query.message.chat_id,
            target_url=vurl,
            start_idx=1,
            end_idx=lim,
            status_msg=query.message,
            user_id=query.from_user.id,
        )
        return

    elif data.startswith("sp_wpsite:"):
        _, site_key = data.split(":")
        site_map = {
            "omaal": ("Omaal63", "https://omaal63.net/"),
            "desijugar": ("DesiJugar", "https://desijugar.me/"),
            "gulabi": ("GulabiHub", "https://gulabihub.com/"),
        }
        s_info = site_map.get(site_key, ("Archive", "https://desijugar.me/"))
        site_name, target_url = s_info
        context.user_data["awaiting_wp_range"] = {
            "url": target_url,
            "site_key": site_key,
            "site_name": site_name,
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔝 Top 5", callback_data=f"sp_wpapply:{site_key}:1-5"),
                InlineKeyboardButton("🔝 Top 10", callback_data=f"sp_wpapply:{site_key}:1-10"),
                InlineKeyboardButton("🔝 Top 20", callback_data=f"sp_wpapply:{site_key}:1-20"),
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data="sp_choose:wplock"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ],
        ])
        card_text = (
            "<blockquote>"
            f"🌐 <b>{site_name} Latest Drops</b>\n\n"
            "Select quick count above or reply in chat with a custom range:\n"
            "• <code>5</code> ➔ First 5 posts\n"
            "• <code>1-15</code> ➔ Posts 1 to 15\n"
            "• <code>page 2</code> ➔ Full Page 2"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data.startswith("sp_wpapply:"):
        _, site_key, r_str = data.split(":")
        site_map = {
            "omaal": ("Omaal63", "https://omaal63.net/"),
            "desijugar": ("DesiJugar", "https://desijugar.me/"),
            "gulabi": ("GulabiHub", "https://gulabihub.com/"),
        }
        site_name, target_url = site_map.get(site_key, ("Archive", "https://desijugar.me/"))
        start_idx, end_idx, page_num = parse_model_range_input(r_str)
        context.user_data.pop("awaiting_wp_range", None)
        await run_wp_listing_scrape(
            bot=context.bot,
            chat_id=query.message.chat_id,
            target_url=target_url,
            start_idx=start_idx or 1,
            end_idx=end_idx,
            status_msg=query.message,
            user_id=query.from_user.id,
            listing_title=f"{site_name} Latest",
        )
        return

    elif data.startswith("sp_wprun_id:"):
        _, sid_str, lim_str = data.split(":")
        sid = int(sid_str)
        lim = int(lim_str)
        wpurl = context.user_data.get(f"wp_url_{sid}") or db.get_url_from_short_id(sid) or "https://desijugar.me/"
        context.user_data.pop("awaiting_wp_range", None)
        await run_wp_listing_scrape(
            bot=context.bot,
            chat_id=query.message.chat_id,
            target_url=wpurl,
            start_idx=1,
            end_idx=lim,
            status_msg=query.message,
            user_id=query.from_user.id,
        )
        return

    elif data.startswith("mv_opt:"):
        _, sid_str, mode = data.split(":")
        sid = int(sid_str)
        target_url = db.get_url_from_short_id(sid)
        details = context.user_data.get(f"mv_dt_{sid}")
        if not details and target_url:
            details = await asyncio.to_thread(get_mmsvibex_video_details, target_url)

        if not details:
            await query.edit_message_text("❌ Session expired. Please send the link again.")
            return

        if mode == "norm":
            col_markup = None
            if details.get("collection_url"):
                col_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📦 Extract All Collection Parts", callback_data=f"mv_all:{sid}")
                ]])
            await send_post_card(
                context.bot,
                query.message.chat_id,
                details,
                user_id=query.from_user.id,
                reply_markup=col_markup,
            )
            try:
                await query.message.delete()
            except Exception:
                pass
            return
        else:
            # Advance mode: proceed to mv_all
            data = f"mv_all:{sid}"

    if data.startswith("mv_all:"):
        _, sid_str = data.split(":")
        sid = int(sid_str)
        target_url = db.get_url_from_short_id(sid)
        details = context.user_data.get(f"mv_dt_{sid}")
        if not details and target_url:
            details = await asyncio.to_thread(get_mmsvibex_video_details, target_url)

        col_url = details.get("collection_url") if details else None
        if not col_url and target_url:
            col_url = target_url

        chat_id = query.message.chat_id
        start_scrape_for_chat(chat_id)
        status_msg = await query.message.reply_text("🚀 <i>Extracting all collection parts...</i>", parse_mode=ParseMode.HTML)
        try:
            col_items = await asyncio.to_thread(get_mmsvibex_actor_videos, col_url) if col_url else []
            if not col_items and details:
                col_items = [{"title": details.get("title", "Video"), "url": target_url}]

            await status_msg.edit_text(
                f"<blockquote>📦 <b>Found {len(col_items)} part(s) in collection!</b>\n<i>Extracting direct MP4s...</i></blockquote>",
                parse_mode=ParseMode.HTML,
            )

            for idx, item in enumerate(col_items, 1):
                if is_scrape_cancelled(chat_id):
                    break
                p_details = await asyncio.to_thread(get_mmsvibex_video_details, item["url"])
                p_details["hide_collection_link"] = True
                await send_post_card(context.bot, chat_id, p_details, user_id=query.from_user.id)
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
    elif data.startswith("sp_wprun_id:"):
        _, sid_str, lim_str = data.split(":")
        sid = int(sid_str)
        lim = int(lim_str)
        wpurl = context.user_data.get(f"wp_url_{sid}") or db.get_url_from_short_id(sid) or "https://desijugar.me/"
        await run_wp_listing_scrape(
            bot=context.bot,
            chat_id=query.message.chat_id,
            target_url=wpurl,
            start_idx=1,
            end_idx=lim,
            status_msg=query.message,
            user_id=query.from_user.id,
        )
    elif data.startswith("sp_cat:"):
        context.user_data.pop("awaiting_category_range", None)
        short_id = int(data.split(":")[1])
        url = db.get_url_from_short_id(short_id)
        if not url:
            await query.edit_message_text("<blockquote>⚠️ Forum category link expired. Please search again.</blockquote>", parse_mode=ParseMode.HTML)
            return

        cat_info = context.user_data.get(f"cat_info_{short_id}", {})
        cat_title = cat_info.get("title")
        if not cat_title:
            parts = [p for p in url.split("?")[0].rstrip("/").split("/") if p]
            raw_slug = parts[-1] if parts else "Forum"
            cat_title = re.sub(r"^\d+-", "", raw_slug).replace("-", " ").title() or "Forum Category"

        try:
            await query.edit_message_text(
                f"<blockquote>💬 <b>{html.escape(cat_title)}</b>\n⏳ <i>Fetching category stats...</i></blockquote>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        stats = await asyncio.to_thread(get_dropmms_category_stats, url)
        cat_title = stats.get("title") or cat_title
        total_str = stats.get("total_topics_str") or "Available"

        context.user_data[f"cat_stats_{short_id}"] = {
            "title": cat_title,
            "total_str": total_str,
            "url": stats.get("url") or url,
        }

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🆕 Upload Date (Start Date)", callback_data=f"sp_csort:{short_id}:start_date"),
                InlineKeyboardButton("🔄 Recently Updated", callback_data=f"sp_csort:{short_id}:updated"),
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data="sp_choose:fm"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ],
        ])

        card_text = (
            "<blockquote>"
            f"💬 <b>{html.escape(cat_title)}</b>\n"
            f"📊 <b>Total Topics:</b> {total_str}"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
    elif data.startswith("sp_csort:"):
        _, short_id_str, sort_val = data.split(":")
        short_id = int(short_id_str)
        url = db.get_url_from_short_id(short_id)
        if not url:
            await query.edit_message_text("<blockquote>⚠️ Forum category link expired. Please search again.</blockquote>", parse_mode=ParseMode.HTML)
            return

        cached_stats = context.user_data.get(f"cat_stats_{short_id}", {})
        cat_title = cached_stats.get("title")
        total_str = cached_stats.get("total_str")
        if not cat_title or not total_str:
            parts = [p for p in url.split("?")[0].rstrip("/").split("/") if p]
            raw_slug = parts[-1] if parts else "Forum"
            cat_title = re.sub(r"^\d+-", "", raw_slug).replace("-", " ").title() or "Forum Category"
            total_str = "Available"

        sort_label = "Upload Date (Start Date)" if sort_val == "start_date" else "Recently Updated"

        context.user_data["awaiting_category_range"] = {
            "short_id": short_id,
            "url": url,
            "cat_title": cat_title,
            "total_str": total_str,
            "sort_by": sort_val,
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡ Today's Posts", callback_data=f"sp_cdate:{short_id}:{sort_val}:today"),
                InlineKeyboardButton("📆 Yesterday & Today", callback_data=f"sp_cdate:{short_id}:{sort_val}:yesterday"),
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data=f"sp_cat:{short_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ],
        ])

        prompt_text = (
            "<blockquote>"
            f"💬 <b>{html.escape(cat_title)}</b>\n"
            f"📊 <b>Total Topics:</b> {total_str}\n"
            f"🎯 <b>Sort:</b> {sort_label}\n\n"
            "⚡ <b>Quick Filter by Date (IST):</b>\n"
            "Tap a button above for instant extraction.\n\n"
            "✏️ <b>Or Enter Custom Range, Count or Page:</b>\n"
            "• <code>10</code> ➔ First 10 topics\n"
            "• <code>1-10</code> ➔ Topics 1 to 10\n"
            "• <code>10-20</code> ➔ Topics 10 to 20\n"
            "• <code>page 2</code> ➔ Full Page 2 (25 topics)\n"
            "• <code>today</code> ➔ Today's uploads\n"
            "• <code>yesterday</code> ➔ Yesterday & Today"
            "</blockquote>"
        )
        await query.edit_message_text(prompt_text, parse_mode=ParseMode.HTML, reply_markup=markup)
    elif data.startswith("sp_cdate:"):
        _, short_id_str, sort_val, date_mode = data.split(":")
        short_id = int(short_id_str)
        url = db.get_url_from_short_id(short_id)
        if not url:
            await query.edit_message_text("<blockquote>⚠️ Forum category link expired. Please search again.</blockquote>", parse_mode=ParseMode.HTML)
            return

        context.user_data.pop("awaiting_category_range", None)
        cached_stats = context.user_data.get(f"cat_stats_{short_id}", {})
        cat_title = cached_stats.get("title")
        if not cat_title:
            cat_info = context.user_data.get(f"cat_info_{short_id}", {})
            cat_title = cat_info.get("title") or "Forum Category"

        range_label = "Today's Uploads (IST)" if date_mode == "today" else "Yesterday & Today (IST)"
        sort_label = "Upload Date (Start Date)" if sort_val == "start_date" else "Recently Updated"

        stop_markup = build_stop_keyboard()
        loading_text = (
            "<blockquote>"
            f"💬 <b>{html.escape(cat_title)}</b>\n"
            f"🎯 <b>Sort:</b> {sort_label}\n"
            f"🔢 <b>Range:</b> {range_label}\n"
            "⏳ <b>Status:</b> Scanning forum category...</blockquote>"
        )
        await query.edit_message_text(loading_text, parse_mode=ParseMode.HTML, reply_markup=stop_markup)

        await run_forum_category_scrape(
            bot=context.bot,
            chat_id=query.message.chat_id,
            target_url=url,
            only_today=(date_mode == "today"),
            date_filter=date_mode,
            sort_by=sort_val,
            status_msg=query.message,
            user_id=query.from_user.id,
            cat_title=cat_title,
        )
    elif data.startswith("sp_cstm:"):
        short_id = int(data.split(":")[1])
        url = db.get_url_from_short_id(short_id)
        if not url:
            await query.edit_message_text("<blockquote>⚠️ Forum category link expired. Please search again.</blockquote>", parse_mode=ParseMode.HTML)
            return

        cat_info = context.user_data.get(f"cat_info_{short_id}", {})
        cat_title = cat_info.get("title")
        if not cat_title:
            parts = [p for p in url.split("?")[0].rstrip("/").split("/") if p]
            raw_slug = parts[-1] if parts else "Forum"
            cat_title = re.sub(r"^\d+-", "", raw_slug).replace("-", " ").title() or "Forum Category"

        context.user_data["awaiting_category_range"] = {
            "short_id": short_id,
            "url": url,
            "cat_title": cat_title,
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data=f"sp_cat:{short_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ]
        ])

        prompt_text = (
            "<blockquote>"
            f"💬 <b>{html.escape(cat_title)}</b>\n"
            f"🔗 <code>{html.escape(url)}</code>\n\n"
            "✏️ <b>Enter Range, Count or Page:</b>\n"
            "• <code>5</code> ➔ First 5 topics\n"
            "• <code>1-5</code> ➔ Topics 1 to 5\n"
            "• <code>5-10</code> ➔ Topics 5 to 10\n"
            "• <code>page 2</code> ➔ Full Page 2"
            "</blockquote>"
        )
        await query.edit_message_text(prompt_text, parse_mode=ParseMode.HTML, reply_markup=markup)
    elif data.startswith("sp_crun:"):
        _, short_id_str, mode = data.split(":")
        short_id = int(short_id_str)
        url = db.get_url_from_short_id(short_id)
        if not url:
            await query.edit_message_text("<blockquote>⚠️ Forum category link expired. Please search again.</blockquote>", parse_mode=ParseMode.HTML)
            return

        chat_id = query.message.chat_id
        only_today = (mode == "today")
        req_limit = 10 if mode == "10" else (25 if mode == "25" else 50)
        cat_info = context.user_data.get(f"cat_info_{short_id}", {})
        cat_title = cat_info.get("title")

        await run_forum_category_scrape(
            bot=context.bot,
            chat_id=chat_id,
            target_url=url,
            only_today=only_today,
            req_limit=req_limit,
            status_msg=query.message,
            user_id=query.from_user.id,
            cat_title=cat_title,
        )
    elif data == "noop":
        await query.answer()
        return
    elif data.startswith("sp_p:"):
        _, plat, page_str = data.split(":")
        page = int(page_str)
        query_text = context.user_data.get("search_query", "").strip()
        if not query_text:
            await query.edit_message_text("⚠️ Search query expired. Please run <code>/search</code> again.", parse_mode=ParseMode.HTML)
            return
        await execute_platform_search(update, context, plat, query_text, edit_msg=query.message, page=page)
    elif data.startswith("sp_do:"):
        plat = data.split(":")[1]
        query_text = context.user_data.get("search_query", "").strip()
        if not query_text:
            await query.edit_message_text("⚠️ Search query expired. Please run <code>/search</code> again.", parse_mode=ParseMode.HTML)
            return
        await execute_platform_search(update, context, plat, query_text, edit_msg=query.message, page=1)
    elif data.startswith("sp_switch:"):
        plat = data.split(":")[1]
        query_text = context.user_data.get("search_query", "").strip()
        if not query_text:
            await query.edit_message_text("⚠️ Search query expired. Please run <code>/search</code> again.", parse_mode=ParseMode.HTML)
            return
        await execute_platform_search(update, context, plat, query_text, edit_msg=query.message, page=1)
    elif data.startswith("sp_mdl:"):
        context.user_data.pop("awaiting_model_range", None)
        short_id = int(data.split(":")[1])
        url = db.get_url_from_short_id(short_id)
        if not url:
            await query.edit_message_text("<blockquote>⚠️ Model link expired. Please search again.</blockquote>", parse_mode=ParseMode.HTML)
            return

        parts = url.rstrip("/").split("/")
        model_name = clean_livecam_title(parts[-1] if len(parts) >= 3 else "Model")

        # Give immediate feedback while stats are fetched
        try:
            await query.edit_message_text(
                f"<blockquote>📹 <b>{html.escape(model_name)}</b>\n⏳ <i>Fetching model stats...</i></blockquote>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        stats = await asyncio.to_thread(get_livecam_model_stats, url)
        model_name = stats.get("name") or model_name
        total_str = stats.get("total_videos_str") or "Available"

        context.user_data[f"model_stats_{short_id}"] = {
            "name": model_name,
            "total_str": total_str,
            "url": stats.get("url") or url,
        }

        markup = build_model_sort_keyboard(short_id)
        card_text = (
            "<blockquote>"
            f"📹 <b>{html.escape(model_name)}</b>\n"
            f"📊 <b>Total Videos:</b> {total_str}"
            "</blockquote>"
        )
        await query.edit_message_text(
            card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data.startswith("sp_sort:"):
        _, short_id_str, sort_val = data.split(":")
        short_id = int(short_id_str)
        url = db.get_url_from_short_id(short_id)
        if not url:
            await query.edit_message_text("<blockquote>⚠️ Model link expired. Please search again.</blockquote>", parse_mode=ParseMode.HTML)
            return

        cached_stats = context.user_data.get(f"model_stats_{short_id}", {})
        model_name = cached_stats.get("name")
        total_str = cached_stats.get("total_str")
        if not model_name or not total_str:
            parts = url.rstrip("/").split("/")
            model_name = clean_livecam_title(parts[-1] if len(parts) >= 3 else "Model")
            total_str = "Available"

        sort_labels = {
            "newest": "Newest",
            "most_viewed": "Most Viewed",
            "most_liked": "Most Liked",
            "oldest": "Oldest",
        }
        sort_label = sort_labels.get(sort_val, "Newest")

        context.user_data["awaiting_model_range"] = {
            "short_id": short_id,
            "url": url,
            "model_name": model_name,
            "total_str": total_str,
            "sort_by": sort_val,
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data=f"sp_mdl:{short_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ]
        ])

        prompt_text = (
            "<blockquote>"
            f"📹 <b>{html.escape(model_name)}</b>\n"
            f"📊 <b>Total Videos:</b> {total_str}\n"
            f"🎯 <b>Sort:</b> {sort_label}\n\n"
            "✏️ <b>Enter Range, Count or Page:</b>\n"
            "• <code>5</code> ➔ First 5 videos\n"
            "• <code>1-5</code> ➔ Videos 1 to 5\n"
            "• <code>5-10</code> ➔ Videos 5 to 10\n"
            "• <code>page 1</code> ➔ Full Page 1 (16 videos)"
            "</blockquote>"
        )
        await query.edit_message_text(
            prompt_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data.startswith("sp_run:"):
        _, short_id_str, mode = data.split(":")
        short_id = int(short_id_str)
        url = db.get_url_from_short_id(short_id)
        if not url:
            await query.edit_message_text("⚠️ Model link expired. Please search again.")
            return

        chat_id = query.message.chat_id
        only_today = (mode == "today")
        req_limit = 10 if mode == "10" else (25 if mode == "25" else 50)

        await run_livecam_model_scrape(
            bot=context.bot,
            chat_id=chat_id,
            target_url=url,
            only_today=only_today,
            req_limit=req_limit,
            status_msg=query.message,
            user_id=query.from_user.id,
        )
    elif data == "sp_cancel":
        context.user_data.pop("awaiting_search", None)
        context.user_data.pop("search_query", None)
        context.user_data.pop("awaiting_model_range", None)
        context.user_data.pop("awaiting_category_range", None)
        try:
            await query.edit_message_text("<blockquote>❌ Cancelled.</blockquote>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    elif data == "cb_help":
        await help_command(update, context)
    elif data == "cb_domains":
        await domains_command(update, context)
    elif data == "cb_channel_help":
        await setchannel_command(update, context)
    elif data == "cb_sethost":
        await sethost_command(update, context)
    elif data == "cb_setlink":
        await setlink_command(update, context)
    elif data.startswith("setlink_"):
        new_mode = data[8:]
        user_id = query.from_user.id
        db.set_user_link_mode(user_id, new_mode)
        label = "🍿 Streaming Only (Default)" if new_mode == "streaming" else ("🔗 Both (Page + Stream)" if new_mode == "both" else "🌐 Video Page Only")
        try:
            await query.edit_message_text(
                f"✅ <b>LiveCam Link Mode Updated to {label}!</b>\n\n"
                "All future LiveCam video cards will use this link format.\n\n"
                "You can change your selection anytime below:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_link_mode_keyboard(new_mode),
            )
        except Exception:
            pass
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
            re_sent = False
            active = context.user_data.get("active_listing")
            if active:
                if target_id.isdigit():
                    active.setdefault("delivered_ids", set()).add(int(target_id))
                re_sent = await send_resurfaced_active_listing(context.bot, query.message.chat_id, context)

            if not re_sent:
                try:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="<i>⚡ What would you like to do next?</i>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_navigation_keyboard(),
                    )
                except Exception:
                    pass
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
    if isinstance(context.error, Conflict):
        logger.warning("⚠️ [Conflict] Another bot instance was running; this instance has taken over polling.")
        return
    if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
        return

    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
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
        BotCommand("setlink", "LiveCam link mode (streaming/both/page)"),
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
    app.add_handler(CommandHandler("setlink", setlink_command))
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
