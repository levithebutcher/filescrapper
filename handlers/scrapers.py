# handlers/scrapers.py
"""
Scraper execution runners for models, categories, listings, and individual topics.
"""

import re
import html
import logging
import asyncio
from urllib.parse import urlparse
import sys

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db
from config import POST_SEND_DELAY
from handlers.session import (
    start_scrape_for_chat,
    end_scrape_for_chat,
    is_scrape_cancelled,
    is_chat_busy,
    cancellable_sleep,
)
from handlers.delivery import send_post_card, send_livecam_card

from keyboards import (
    build_stop_keyboard,
    build_category_options_keyboard,
    build_mmsvibex_options_keyboard,
)
from ui import format_category_completion_card

from scraper import (
    clean_livecam_title,
    apply_slice,
    get_forum_topics,
    get_post_details,
    get_livecam_model_videos,
    get_livecam_video_details,
    is_mmsvibex_photo_url,
    is_mmsvibex_video_url,
    get_mmsvibex_photo_details,
    get_mmsvibex_video_details,
    get_mmsvibex_listing_items,
    is_wp_locker_post_url,
    get_wp_post_details,
    get_wp_listing_posts,
    is_leakedzone_video_url,
    get_leakedzone_video_details,
    is_kvs_video_url,
    get_kvs_video_details,
    is_thotchicks_video_url,
    get_thotchicks_video_details,
    is_mmsdesi_video_url,
    get_mmsdesi_video_details,
)

logger = logging.getLogger(__name__)


def _get_target_func(name: str, fallback):
    """Retrieve function from bot module if patched in tests, else fallback."""
    bot_mod = sys.modules.get("bot")
    if bot_mod and hasattr(bot_mod, name):
        return getattr(bot_mod, name)
    return fallback


async def process_livecam_scrape(bot, chat_id: int | str, video_item: dict, user_id: int | str = None):
    """Extract streaming links and deliver LiveCam card."""
    if is_scrape_cancelled(chat_id):
        return
    try:
        video_url = video_item.get("video_url") or video_item.get("url")
        target_details_fn = _get_target_func("get_livecam_video_details", get_livecam_video_details)
        details = await asyncio.to_thread(target_details_fn, video_url)
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

        target_send_card = _get_target_func("send_livecam_card", send_livecam_card)
        await target_send_card(bot, chat_id, details, user_id=user_id)
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
    context=None,
    short_id: int | str | None = None,
    total_str: str = "Available",
):
    """
    Standardized worker to scrape and deliver videos from a LiveCam model page.
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

    if context and status_msg and hasattr(status_msg, "message_id"):
        context.user_data[f"active_progress_msg_{cid}"] = status_msg.message_id

    try:
        target_vids_fn = _get_target_func("get_livecam_model_videos", get_livecam_model_videos)
        raw_videos = await asyncio.to_thread(
            target_vids_fn,
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

        target_proc_fn = _get_target_func("process_livecam_scrape", process_livecam_scrape)
        delivered_count = 0
        for v in videos:
            if is_scrape_cancelled(cid):
                logger.info(f"Model scrape cancelled by user in chat {cid}")
                break
            await target_proc_fn(bot, cid, v, user_id=uid)
            if is_scrape_cancelled(cid):
                break
            delivered_count += 1
            await cancellable_sleep(POST_SEND_DELAY, cid)

        # 1. Ephemeral cleanup: Delete progress message so it does not linger above posts
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass
        if context:
            context.user_data.pop(f"active_progress_msg_{cid}", None)

        # 2. Resurface Card 4 at bottom of chat
        stopped = is_scrape_cancelled(cid)
        status_header = (
            f"🛑 <b>Scraping stopped!</b> Delivered: <b>{delivered_count}</b> video(s)"
            if stopped
            else f"✅ <b>Extraction Complete!</b>\n📹 Delivered: <b>{delivered_count}</b> video(s)"
        )
        end_card_text = (
            f"<blockquote>{status_header}</blockquote>\n\n"
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
        sid = short_id or db.get_or_create_short_id(target_url)
        end_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data=f"sp_mdl:{sid}"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ]
        ])
        try:
            end_msg = await bot.send_message(
                chat_id=cid,
                text=end_card_text,
                parse_mode=ParseMode.HTML,
                reply_markup=end_markup,
            )
            if context:
                context.user_data["awaiting_model_range"] = {
                    "short_id": sid,
                    "url": target_url,
                    "model_name": model_name,
                    "total_str": total_str,
                    "sort_by": sort_by,
                    "chat_id": cid,
                    "message_id": end_msg.message_id,
                }
        except Exception as e:
            logger.warning(f"Could not send completion card for LiveCam: {e}")
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
    context: ContextTypes.DEFAULT_TYPE = None,
):
    """
    Standardized worker to scrape and deliver topics from a DropMMS forum category.
    Supports sorting, date filtering (today, yesterday), flexible range, direct page, stopping, and quoted status cards.
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

    if context and status_msg and hasattr(status_msg, "message_id"):
        context.user_data[f"active_progress_msg_{cid}"] = status_msg.message_id

    try:
        target_topics_fn = _get_target_func("get_forum_topics", get_forum_topics)
        raw_topics = await asyncio.to_thread(
            target_topics_fn,
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

        target_proc_topic = _get_target_func("process_topic_scrape", process_topic_scrape)
        delivered_count = 0
        for t in topics:
            if is_scrape_cancelled(cid):
                logger.info(f"Category scrape cancelled by user in chat {cid}")
                break
            await target_proc_topic(bot, cid, t["url"], user_id=uid, topic_meta=t)
            if is_scrape_cancelled(cid):
                break
            delivered_count += 1
            await cancellable_sleep(POST_SEND_DELAY, cid)

        # 1. Ephemeral cleanup: Delete top progress message so it does not clutter above posts
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass
        if context:
            context.user_data.pop(f"active_progress_msg_{cid}", None)

        # 2. Resurface the options card at the bottom of the chat after all posts are delivered
        short_id = db.get_or_create_short_id(clean_base)
        cached_stats = context.user_data.get(f"cat_stats_{short_id}", {}) if context else {}
        total_str = cached_stats.get("total_str") or "Available"
        sort_val = sort_by or "start_date"
        stopped = is_scrape_cancelled(cid)

        end_card_text = format_category_completion_card(
            delivered_count=delivered_count,
            cat_title=cat_title,
            total_str=total_str,
            sort_val=sort_val,
            stopped=stopped,
        )
        end_markup = build_category_options_keyboard(short_id, sort_val)

        try:
            end_msg = await bot.send_message(
                chat_id=cid,
                text=end_card_text,
                parse_mode=ParseMode.HTML,
                reply_markup=end_markup,
            )
            if context:
                context.user_data["awaiting_category_range"] = {
                    "short_id": short_id,
                    "url": clean_base,
                    "cat_title": cat_title,
                    "total_str": total_str,
                    "sort_by": sort_val,
                    "chat_id": cid,
                    "message_id": end_msg.message_id,
                }
        except Exception as e:
            logger.warning(f"Could not send completion options card: {e}")
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
    page_num: int | None = None,
    is_last_n: bool = False,
    status_msg=None,
    user_id: int | str = None,
    listing_title: str | None = None,
    context=None,
    sort_key: str = "latest",
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

        if context and status_msg and hasattr(status_msg, "message_id"):
            context.user_data[f"active_progress_msg_{cid}"] = status_msg.message_id

        target_items_fn = _get_target_func("get_mmsvibex_listing_items", get_mmsvibex_listing_items)
        items = await asyncio.to_thread(target_items_fn, target_url, page=page_num or 1, limit=limit)
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

        target_send_card = _get_target_func("send_post_card", send_post_card)
        delivered_count = 0
        for it in items:
            if is_scrape_cancelled(cid):
                break

            url = it["url"]
            if is_mmsvibex_photo_url(url):
                target_p_fn = _get_target_func("get_mmsvibex_photo_details", get_mmsvibex_photo_details)
                details = await asyncio.to_thread(target_p_fn, url)
            else:
                target_v_fn = _get_target_func("get_mmsvibex_video_details", get_mmsvibex_video_details)
                details = await asyncio.to_thread(target_v_fn, url)

            await target_send_card(bot, cid, details, user_id=uid)
            if is_scrape_cancelled(cid):
                break
            delivered_count += 1
            await cancellable_sleep(POST_SEND_DELAY, cid)

        # 1. Ephemeral cleanup: Delete progress message so it does not linger above posts
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass
        if context:
            context.user_data.pop(f"active_progress_msg_{cid}", None)

        # 2. Resurface Card 2 at bottom of chat
        stopped = is_scrape_cancelled(cid)
        status_header = (
            f"🛑 <b>Scraping stopped!</b> Delivered: <b>{delivered_count}</b> item(s)"
            if stopped
            else f"✅ <b>Extraction Complete!</b>\n⚡ Delivered: <b>{delivered_count}</b> item(s)"
        )
        end_card_text = (
            f"<blockquote>{status_header}</blockquote>\n\n"
            "<blockquote>"
            f"⚡ <b>{html.escape(title)}</b>\n\n"
            "Reply in chat with a custom range, count or page:\n"
            "• <code>5</code> ➔ First 5 items\n"
            "• <code>1-15</code> ➔ Items 1 to 15\n"
            "• <code>page 2</code> ➔ Full Page 2"
            "</blockquote>"
        )
        end_markup = build_mmsvibex_options_keyboard(sort_key=sort_key)
        try:
            end_msg = await bot.send_message(
                chat_id=cid,
                text=end_card_text,
                parse_mode=ParseMode.HTML,
                reply_markup=end_markup,
            )
            if context:
                context.user_data["awaiting_vibex_range"] = {
                    "url": target_url,
                    "sort_key": sort_key,
                    "sort_label": title,
                    "chat_id": cid,
                    "message_id": end_msg.message_id,
                }
        except Exception as e:
            logger.warning(f"Could not send completion card for MMSVibex: {e}")
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
    page_num: int | None = None,
    is_last_n: bool = False,
    status_msg=None,
    user_id: int | str = None,
    listing_title: str | None = None,
    context=None,
):
    """
    Worker to scrape and deliver posts from WordPress locker/tube sites (Omaal63, DesiJugar, GulabiHub, MMSMaza).
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

        if context and status_msg and hasattr(status_msg, "message_id"):
            context.user_data[f"active_progress_msg_{cid}"] = status_msg.message_id

        target_listing_fn = _get_target_func("get_wp_listing_posts", get_wp_listing_posts)
        posts = await asyncio.to_thread(target_listing_fn, target_url, page=page_num or 1, limit=limit)
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

        target_send_card = _get_target_func("send_post_card", send_post_card)
        target_details_fn = _get_target_func("get_wp_post_details", get_wp_post_details)
        for idx, p in enumerate(posts, 1):
            if is_scrape_cancelled(cid):
                await bot.send_message(
                    chat_id=cid,
                    text=f"<blockquote>🛑 <b>Scraping stopped!</b> Delivered {idx-1}/{len(posts)} posts.</blockquote>",
                    parse_mode=ParseMode.HTML,
                )
                break

            details = await asyncio.to_thread(target_details_fn, p["url"])
            await target_send_card(bot, cid, details, user_id=uid)
            if is_scrape_cancelled(cid):
                break
            await cancellable_sleep(POST_SEND_DELAY, cid)

        if context:
            context.user_data.pop(f"active_progress_msg_{cid}", None)

        if not is_scrape_cancelled(cid):
            back_cb = "cb_search"
            if "omaal63" in target_url:
                back_cb = "sp_wpsite:omaal"
            elif "desijugar" in target_url:
                back_cb = "sp_wpsite:desijugar"
            elif "gulabihub" in target_url:
                back_cb = "sp_wpsite:gulabi"
            elif "mmsmaza" in target_url:
                back_cb = "sp_wpsite:mmsmaza"

            end_card_text = (
                f"<blockquote>✅ <b>Extraction Complete!</b>\n🌐 Delivered: <b>{len(posts)}</b> posts</blockquote>\n\n"
                "<blockquote>"
                f"🌐 <b>{html.escape(title)}</b>\n\n"
                "Reply in chat with a custom range, count or page:\n"
                "• <code>5</code> ➔ First 5 posts\n"
                "• <code>1-15</code> ➔ Posts 1 to 15\n"
                "• <code>page 2</code> ➔ Full Page 2"
                "</blockquote>"
            )
            end_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔙 Back", callback_data=back_cb),
                    InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
                ],
            ])
            try:
                end_msg = await bot.send_message(
                    chat_id=cid,
                    text=end_card_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=end_markup,
                )
                if context:
                    context.user_data["awaiting_wp_range"] = {
                        "url": target_url,
                        "site_name": title,
                        "chat_id": cid,
                        "message_id": end_msg.message_id,
                    }
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"Could not send completion card for WP listing: {e}")
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


async def process_topic_scrape(bot, chat_id: int | str, url: str, user_id: int = None, topic_meta: dict = None):
    """Scrape and deliver single topic card with cancellation support across all supported sites."""
    if is_scrape_cancelled(chat_id):
        return
    try:
        if is_leakedzone_video_url(url):
            details = await asyncio.to_thread(get_leakedzone_video_details, url)
        elif is_kvs_video_url(url):
            details = await asyncio.to_thread(get_kvs_video_details, url)
        elif is_thotchicks_video_url(url):
            details = await asyncio.to_thread(get_thotchicks_video_details, url)
        elif is_mmsdesi_video_url(url):
            details = await asyncio.to_thread(get_mmsdesi_video_details, url)
        elif is_mmsvibex_photo_url(url):
            details = await asyncio.to_thread(get_mmsvibex_photo_details, url)
        elif is_mmsvibex_video_url(url):
            details = await asyncio.to_thread(get_mmsvibex_video_details, url)
        elif is_wp_locker_post_url(url):
            details = await asyncio.to_thread(get_wp_post_details, url)
        else:
            target_post_fn = _get_target_func("get_post_details", get_post_details)
            details = await asyncio.to_thread(target_post_fn, url)

        if topic_meta:
            if topic_meta.get("date_ist") and not details.get("date_ist"):
                details["date_ist"] = topic_meta["date_ist"]
            if topic_meta.get("date") and not details.get("date"):
                details["date"] = topic_meta["date"]
        if is_scrape_cancelled(chat_id):
            return

        target_send_card = _get_target_func("send_post_card", send_post_card)
        await target_send_card(bot, chat_id, details, user_id=user_id)
    except Exception as e:
        if is_scrape_cancelled(chat_id):
            return
        safe_err = html.escape(str(e))
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ <b>Could not extract:</b>\n<code>{html.escape(url)}</code>\n<i>Reason: {safe_err}</i>",
            parse_mode=ParseMode.HTML,
        )
