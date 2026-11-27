# handlers/delivery.py
"""
Card formatting and delivery engine for posts, media previews, and resurfaced listings.
"""

import io
import html
import logging
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import RetryAfter
from telegram.ext import ContextTypes

import db
from ui import format_post_card
from scraper import download_image_bytes
from handlers.session import is_scrape_cancelled

logger = logging.getLogger(__name__)

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_SAFE_CHUNK = 3900


def _split_html_chunks(text: str, max_len: int = TELEGRAM_SAFE_CHUNK) -> list[str]:
    """Split a long Telegram HTML message along line boundaries under max_len."""
    if len(text) <= TELEGRAM_TEXT_LIMIT:
        return [text]

    chunks = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > max_len:
            if current:
                chunks.append(current.rstrip("\n"))
                current = ""
            while len(line) > max_len:
                chunks.append(line[:max_len])
                line = line[max_len:]
        current += line
    if current:
        chunks.append(current.rstrip("\n"))
    return chunks or [text[:max_len]]


async def _send_text_with_retry(
    bot,
    chat_id: int | str,
    text: str,
    reply_markup=None,
    disable_web_page_preview: bool = True,
    error_context: str = "card",
):
    """Send text (chunked if >4096 chars) with RetryAfter handling and cancellation checks."""
    chunks = _split_html_chunks(text)
    for idx, chunk in enumerate(chunks):
        if is_scrape_cancelled(chat_id):
            return
        chunk_markup = reply_markup if idx == len(chunks) - 1 else None
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=chunk_markup,
            )
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            if is_scrape_cancelled(chat_id):
                return
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=chunk_markup,
            )
        except Exception as e:
            logger.error(f"Failed to send {error_context} to {chat_id}: {e}")
            break


async def send_post_card(bot, chat_id: int | str, details: dict, user_id: int = None, reply_markup=None):
    """Deliver a clean post card with downloaded thumbnail bytes and copyable link(s)."""
    if is_scrape_cancelled(chat_id):
        return

    target_uid = user_id if user_id else (chat_id if isinstance(chat_id, int) and chat_id > 0 else 0)
    user_pref = db.get_user_host_preference(target_uid) if target_uid else "streamtape"
    caption = format_post_card(details, user_pref)
    # Post cards default to NO bottom buttons to avoid chat clutter (links are already in caption)

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
    await _send_text_with_retry(
        bot,
        chat_id,
        caption,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
        error_context="post card",
    )


async def send_livecam_card(bot, chat_id: int | str, details: dict, user_id: int | str = None, reply_markup=None):
    """Deliver a clean LiveCam card with uncropped HD thumbnail and copyable links using Universal Card Engine."""
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
    # Post cards default to NO bottom buttons to avoid chat clutter (links are already in caption)

    thumb_url = details_copy.get("thumbnail")

    image_bytes = None
    if thumb_url:
        try:
            image_bytes = await asyncio.to_thread(download_image_bytes, thumb_url)
        except Exception as e:
            logger.debug(f"LiveCam thumbnail download note: {e}")

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
            logger.warning(f"LiveCam photo send failed: {e}")

    if is_scrape_cancelled(chat_id):
        return

    if image_bytes and len(caption) > 1024:
        try:
            photo_file = io.BytesIO(image_bytes)
            photo_file.name = "thumb.jpg"
            short_caption = f"<blockquote>📹 <b>{html.escape(details.get('title', 'LiveCam Video'))}</b></blockquote>"
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=short_caption,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"Detached LiveCam photo send failed: {e}")

    if is_scrape_cancelled(chat_id):
        return

    await _send_text_with_retry(
        bot,
        chat_id,
        caption,
        reply_markup=reply_markup,
        disable_web_page_preview=False,
        error_context="LiveCam card",
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
        logger.warning(f"Could not re-surface active listing to {chat_id}: {e}")
        return False
