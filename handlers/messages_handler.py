# handlers/messages_handler.py
"""
Handler for incoming plain text messages: interactive search queries, range entries, and raw URLs.
"""

import html
import logging
import asyncio
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import POST_SEND_DELAY
from handlers.session import (
    start_scrape_for_chat,
    end_scrape_for_chat,
    is_scrape_cancelled,
    cancellable_sleep,
)
from handlers.commands import stop_command
from handlers.delivery import send_post_card
from handlers.scrapers import (
    process_topic_scrape,
    run_livecam_model_scrape,
    run_forum_category_scrape,
    run_mmsvibex_listing_scrape,
    run_wp_listing_scrape,
)
from handlers.search_flow import execute_platform_search
from handlers.raw_url import handle_raw_url

from keyboards import (
    build_stop_keyboard,
    build_search_results_clean_keyboard,
    build_search_execute_platform_keyboard,
)
from ui import (
    parse_search_selection,
    format_category_browse_completion_card,
    format_search_completion_card,
)
from scraper import (
    parse_model_range_input,
    is_mmsvibex_photo_url,
    get_mmsvibex_photo_details,
    get_mmsvibex_video_details,
    get_leakedzone_video_details,
    get_kvs_video_details,
    get_thotchicks_video_details,
    get_mmsdesi_video_details,
    get_wp_post_details,
)

logger = logging.getLogger(__name__)


def _get_target_func(name: str, fallback):
    """Retrieve function from bot module if patched in tests, else fallback."""
    bot_mod = sys.modules.get("bot")
    if bot_mod and hasattr(bot_mod, name):
        return getattr(bot_mod, name)
    return fallback


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

    # 0. Interactive Search Keyword Input Flow (HIGHEST PRIORITY)
    search_flow = context.user_data.pop("awaiting_search_flow", None)
    if search_flow:
        clean_kw = text.strip()
        try:
            await update.effective_message.delete()
        except Exception:
            pass

        # Clear any lingering range flows to avoid state conflicts
        context.user_data.pop("awaiting_model_range", None)
        context.user_data.pop("awaiting_category_range", None)
        context.user_data.pop("awaiting_vibex_range", None)
        context.user_data.pop("awaiting_wp_range", None)

        # Ephemeral cleanup: Delete prompt message ("Please send keyword...")
        prompt_msg_id = search_flow.get("message_id")
        if prompt_msg_id:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_msg_id)
            except Exception:
                pass

        # Also cleanup any previous active category card
        old_card_id = context.user_data.pop("active_card_msg_id", None)
        if old_card_id and old_card_id != prompt_msg_id:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=old_card_id)
            except Exception:
                pass

        target_exec_search = _get_target_func("execute_platform_search", execute_platform_search)
        await target_exec_search(
            update=update,
            context=context,
            plat=search_flow["plat"],
            query=clean_kw,
            forum_id=search_flow.get("forum_id"),
            scope_name=search_flow.get("scope_name"),
            back_callback=search_flow.get("back_callback"),
        )
        return

    # 1. Number selection from active search results (HIGHEST PRIORITY AFTER KEYWORD FLOW)
    search_state = context.user_data.get("active_search_results")
    if search_state and search_state.get("items"):
        items = search_state["items"]
        selection_indices = parse_search_selection(text, len(items))
        if selection_indices:
            try:
                await update.effective_message.delete()
            except Exception:
                pass

            # Clear any conflicting lingering prompt states to prevent state collision
            context.user_data.pop("awaiting_search", None)
            context.user_data.pop("awaiting_model_range", None)
            context.user_data.pop("awaiting_category_range", None)
            context.user_data.pop("awaiting_vibex_range", None)
            context.user_data.pop("awaiting_wp_range", None)

            chat_id = update.effective_chat.id
            user_id = update.effective_user.id if update.effective_user else None

            start_scrape_for_chat(chat_id)
            stop_markup = build_stop_keyboard()
            status_text = (
                "<blockquote>"
                f"⏳ <b>Extracting {len(selection_indices)} selected topic(s)...</b>\n"
                "<i>Tap below if you wish to stop.</i>"
                "</blockquote>"
            )
            status_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=status_text,
                parse_mode=ParseMode.HTML,
                reply_markup=stop_markup,
            )
            context.user_data[f"active_progress_msg_{chat_id}"] = status_msg.message_id

            target_send_card = _get_target_func("send_post_card", send_post_card)
            target_proc_topic = _get_target_func("process_topic_scrape", process_topic_scrape)

            delivered_this_round = []
            try:
                for idx in selection_indices:
                    if is_scrape_cancelled(chat_id):
                        break
                    topic = items[idx - 1]
                    url = topic["url"]
                    try:
                        if search_state["plat"] == "vibex":
                            if is_mmsvibex_photo_url(url):
                                target_photo_fn = _get_target_func("get_mmsvibex_photo_details", get_mmsvibex_photo_details)
                                details = await asyncio.to_thread(target_photo_fn, url)
                            else:
                                target_vid_fn = _get_target_func("get_mmsvibex_video_details", get_mmsvibex_video_details)
                                details = await asyncio.to_thread(target_vid_fn, url)
                            await target_send_card(context.bot, chat_id, details, user_id=user_id)
                        elif search_state["plat"] == "lz":
                            target_lz_fn = _get_target_func("get_leakedzone_video_details", get_leakedzone_video_details)
                            details = await asyncio.to_thread(target_lz_fn, url)
                            await target_send_card(context.bot, chat_id, details, user_id=user_id)
                        elif search_state["plat"] in ("xvid", "xvideo", "xvideotube", "hs", "hornysapiens", "viralxxxporn"):
                            target_kvs_fn = _get_target_func("get_kvs_video_details", get_kvs_video_details)
                            details = await asyncio.to_thread(target_kvs_fn, url)
                            await target_send_card(context.bot, chat_id, details, user_id=user_id)
                        elif search_state["plat"] in ("tc", "thotchicks"):
                            target_tc_fn = _get_target_func("get_thotchicks_video_details", get_thotchicks_video_details)
                            details = await asyncio.to_thread(target_tc_fn, url)
                            await target_send_card(context.bot, chat_id, details, user_id=user_id)
                        elif search_state["plat"] in ("desi", "mmsdesi"):
                            target_desi_fn = _get_target_func("get_mmsdesi_video_details", get_mmsdesi_video_details)
                            details = await asyncio.to_thread(target_desi_fn, url)
                            await target_send_card(context.bot, chat_id, details, user_id=user_id)
                        elif search_state["plat"].startswith("wp_") or search_state["plat"] == "wplock":
                            target_wp_fn = _get_target_func("get_wp_post_details", get_wp_post_details)
                            details = await asyncio.to_thread(target_wp_fn, url)
                            await target_send_card(context.bot, chat_id, details, user_id=user_id)
                        else:
                            await target_proc_topic(
                                bot=context.bot,
                                chat_id=chat_id,
                                url=url,
                                user_id=user_id,
                                topic_meta=topic,
                            )
                        search_state.setdefault("delivered_indices", set()).add(idx)
                        delivered_this_round.append(idx)
                    except Exception as item_err:
                        logger.warning(f"Error extracting item #{idx} ({url}): {item_err}")
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=f"<blockquote>⚠️ <b>Item #{idx} ({html.escape(topic.get('title', 'Item'))}):</b>\nCould not extract details: <code>{html.escape(str(item_err))}</code></blockquote>",
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception:
                            pass
                    if is_scrape_cancelled(chat_id):
                        break
                    await cancellable_sleep(POST_SEND_DELAY, chat_id)
            finally:
                end_scrape_for_chat(chat_id)
                context.user_data.pop(f"active_progress_msg_{chat_id}", None)
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            # Resurface search results or category browse card with completion note at the bottom
            item_noun = "item(s)" if (search_state["plat"] in ("vibex", "wplock") or search_state["plat"].startswith("wp_")) else "topic(s)"
            if search_state.get("is_category_browse"):
                completion_text = format_category_browse_completion_card(
                    delivered_summary=f"{len(delivered_this_round)} {item_noun}",
                    site_name=search_state.get("site_name", "WordPress"),
                    cat_name=search_state.get("cat_name", "Category"),
                    page=search_state["page"],
                    total_pages=search_state["total_pages"],
                    items=search_state["items"],
                    delivered_indices=search_state["delivered_indices"],
                )
            else:
                completion_text = format_search_completion_card(
                    delivered_summary=f"{len(delivered_this_round)} {item_noun}",
                    query=search_state["query"],
                    scope_name=search_state["scope_name"],
                    page=search_state["page"],
                    total_pages=search_state["total_pages"],
                    total_count=search_state["total_count"],
                    items=search_state["items"],
                    delivered_indices=search_state["delivered_indices"],
                )

            if search_state.get("page_callback_prefix"):
                page_pfx = search_state["page_callback_prefix"]
            else:
                fid_str = str(search_state["forum_id"]) if search_state.get("forum_id") else "all"
                page_pfx = f"sp_fp:{search_state['plat']}:{fid_str}"

            clean_markup = build_search_results_clean_keyboard(
                page=search_state["page"],
                total_pages=search_state["total_pages"],
                page_callback_prefix=page_pfx,
                back_callback=search_state.get("back_callback", f"sp_choose:{search_state['plat']}"),
            )

            new_card_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=completion_text,
                parse_mode=ParseMode.HTML,
                reply_markup=clean_markup,
            )

            old_msg_id = search_state.get("message_id")
            if old_msg_id and old_msg_id != new_card_msg.message_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
                except Exception:
                    pass

            extra_old = context.user_data.pop("active_card_msg_id", None)
            if extra_old and extra_old != new_card_msg.message_id and extra_old != old_msg_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=extra_old)
                except Exception:
                    pass

            search_state["message_id"] = new_card_msg.message_id
            context.user_data["active_card_msg_id"] = new_card_msg.message_id
            return

    # 2. Check if user is in an interactive search flow from /search prompt
    awaiting_plat = context.user_data.pop("awaiting_search", None)
    if awaiting_plat:
        clean_text = text.strip()
        try:
            await update.effective_message.delete()
        except Exception:
            pass
        if awaiting_plat == "prompt":
            context.user_data["search_query"] = clean_text
            markup = build_search_execute_platform_keyboard()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    f"🔍 <b>Search Query:</b> <code>{html.escape(clean_text)}</code>\n\n"
                    "Choose a platform to search:"
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return
        target_exec_search = _get_target_func("execute_platform_search", execute_platform_search)
        await target_exec_search(update, context, awaiting_plat, clean_text)
        return

    # 3. Interactive Model Range Input Flow
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

        target_live_model_scrape = _get_target_func("run_livecam_model_scrape", run_livecam_model_scrape)
        await target_live_model_scrape(
            bot=context.bot,
            chat_id=model_flow["chat_id"],
            target_url=model_flow["url"],
            sort_by=model_flow.get("sort_by", "newest"),
            start_idx=start_idx or 1,
            end_idx=end_idx,
            page_num=page_num,
            status_msg=status_msg,
            user_id=update.effective_user.id if update.effective_user else None,
            context=context,
            short_id=model_flow.get("short_id"),
            total_str=model_flow.get("total_str", "Available"),
        )
        return

    # 4. Interactive Category Range Input Flow
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

        target_forum_scrape = _get_target_func("run_forum_category_scrape", run_forum_category_scrape)
        await target_forum_scrape(
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
            context=context,
        )
        return

    # 5. Interactive MMSVibex Range Input Flow
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

        target_vibex_scrape = _get_target_func("run_mmsvibex_listing_scrape", run_mmsvibex_listing_scrape)
        await target_vibex_scrape(
            bot=context.bot,
            chat_id=vibex_flow["chat_id"],
            target_url=vibex_flow["url"],
            start_idx=start_idx or 1,
            end_idx=end_idx,
            status_msg=status_msg,
            user_id=update.effective_user.id if update.effective_user else None,
            listing_title=vibex_flow.get("sort_label", "MMSVibex Videos"),
            context=context,
            sort_key=vibex_flow.get("sort_key", "latest"),
        )
        return

    # 6. Interactive WordPress Locker Range Input Flow
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

        target_wp_scrape = _get_target_func("run_wp_listing_scrape", run_wp_listing_scrape)
        await target_wp_scrape(
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

    # 7. Raw URL detection
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
        target_raw_fn = _get_target_func("handle_raw_url", handle_raw_url)
        await target_raw_fn(update, context, text)
