# handlers/callbacks.py
"""
Interactive inline button callback router for search, browsing, options, sorting, and pagination.
"""

import re
import html
import logging
import asyncio
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db
from config import POST_SEND_DELAY
from handlers.session import (
    start_scrape_for_chat,
    end_scrape_for_chat,
    cancel_scrape_for_chat,
    is_scrape_cancelled,
    cancellable_sleep,
    get_search_mode,
    set_search_mode,
)
from handlers.commands import (
    start_command,
    help_command,
    search_command,
    sethost_command,
    setlink_command,
)
from handlers.feed import (
    today_command,
    latest_command,
    domains_command,
    setchannel_command,
)
from handlers.delivery import send_post_card, send_resurfaced_active_listing
from handlers.search_flow import execute_platform_search
from handlers.scrapers import (
    run_livecam_model_scrape,
    run_forum_category_scrape,
    run_mmsvibex_listing_scrape,
    run_wp_listing_scrape,
    process_topic_scrape,
)

from ui import (
    format_clean_search_results_page,
    format_clean_category_posts_page,
    format_category_options_card,
)
from keyboards import (
    build_stop_keyboard,
    build_category_options_keyboard,
    build_forum_sort_keyboard,
    build_model_sort_keyboard,
    build_mmsvibex_hub_keyboard,
    build_mmsvibex_options_keyboard,
    build_wp_site_hub_keyboard,
    build_wp_categories_keyboard,
    build_leakedzone_hub_keyboard,
    build_xvideo_hub_keyboard,
    build_hornysapiens_hub_keyboard,
    build_thotchicks_hub_keyboard,
    build_mmsdesi_hub_keyboard,
    build_mmsmaza_hub_keyboard,
    build_search_results_clean_keyboard,
    get_host_settings_keyboard,
    get_link_mode_keyboard,
    get_navigation_keyboard,
)
from scraper import (
    clean_livecam_title,
    parse_model_range_input,
    get_dropmms_forums,
    get_mmstown_forums,
    get_dropmms_category_stats,
    get_livecam_model_stats,
    get_mmsvibex_video_details,
    get_mmsvibex_actor_videos,
    get_wp_categories,
    get_wp_listing_posts,
    get_leakedzone_model_videos,
    get_kvs_listing_items,
    get_thotchicks_listing_items,
    get_mmsdesi_category_videos,
)

logger = logging.getLogger(__name__)


def _get_target_func(name: str, fallback):
    """Retrieve function from bot module if patched in tests, else fallback."""
    bot_mod = sys.modules.get("bot")
    if bot_mod and hasattr(bot_mod, name):
        return getattr(bot_mod, name)
    return fallback


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
        context.user_data.pop("awaiting_search", None)
        plat = data.split(":")[1]
        if plat == "all":
            context.user_data["awaiting_search_query"] = "all"
            prompt_text = (
                "<blockquote>"
                "🌐 <b>Search All Sites (Global Search)</b>\n\n"
                "Enter a search keyword or model name to search across all supported platforms simultaneously:"
                "</blockquote>"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="cb_search"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text(prompt_text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        if plat == "fm":
            try:
                await query.edit_message_text(
                    "<blockquote>💬 <b>DropMMS Forums</b>\n⏳ <i>Fetching forum categories...</i></blockquote>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

            forums = await asyncio.to_thread(_get_target_func("get_dropmms_forums", get_dropmms_forums))
            buttons = [
                [InlineKeyboardButton("🔍 Search All DropMMS Topics", callback_data="sp_search_site:fm")]
            ]
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

            forums = await asyncio.to_thread(_get_target_func("get_mmstown_forums", get_mmstown_forums))
            buttons = [
                [InlineKeyboardButton("🔍 Search All MMSTown Topics", callback_data="sp_search_site:mmst")]
            ]
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
            context.user_data.pop("awaiting_model_range", None)
            context.user_data.pop("awaiting_vibex_range", None)
            context.user_data.pop("awaiting_category_range", None)
            context.user_data.pop("awaiting_wp_range", None)
            context.user_data.pop("active_search_results", None)
            context.user_data.pop("awaiting_search", None)
            markup = build_mmsvibex_hub_keyboard(back_callback="cb_search")
            await query.edit_message_text(
                "<blockquote>⚡ <b>MMSVibex Hub</b>\nSelect sorting or browse category:</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
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
                    InlineKeyboardButton("📁 MMSMaza", callback_data="sp_wpsite:mmsmaza"),
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

        elif plat == "lc":
            plat_label = "📹 LiveCam Models"
            example_q = "GoddessAnna"
            context.user_data.pop("awaiting_model_range", None)
            context.user_data.pop("awaiting_vibex_range", None)
            context.user_data.pop("awaiting_category_range", None)
            context.user_data.pop("awaiting_wp_range", None)
            context.user_data.pop("active_search_results", None)
            context.user_data.pop("awaiting_search", None)
            context.user_data["awaiting_search_flow"] = {
                "plat": "lc",
                "scope_name": "LiveCam Models",
                "back_callback": "cb_search",
                "chat_id": query.message.chat_id,
                "message_id": query.message.message_id,
            }
            context.user_data["active_card_msg_id"] = query.message.message_id
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="cb_search"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text(
                f"<blockquote>🔍 <b>Searching:</b> {plat_label}\n\n"
                f"✏️ <i>Please send the keyword or model name to search (e.g. <code>{example_q}</code>):</i></blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        elif plat in ("lz", "xvid", "hs", "tc"):
            meta = {
                "lz": ("🔓 LeakedZone", "Jasmine Sherni"),
                "xvid": ("📺 X-Video Tube", "Jasmine Sherni"),
                "hs": ("🔞 HornySapiens", "Jasmine Sherni"),
                "tc": ("💃 ThotChicks", "Jasmine Sherni"),
            }[plat]
            plat_base, example_q = meta
            mode = get_search_mode()
            plat_label = f"{plat_base} Models" if mode == "model" else f"{plat_base} Videos"
            prompt_instruction = f"Please send the model name to search (e.g. <code>{example_q}</code>):" if mode == "model" else f"Please send the video keyword or title to search (e.g. <code>{example_q}</code>):"

            context.user_data.pop("awaiting_model_range", None)
            context.user_data.pop("awaiting_vibex_range", None)
            context.user_data.pop("awaiting_category_range", None)
            context.user_data.pop("awaiting_wp_range", None)
            context.user_data.pop("active_search_results", None)
            context.user_data.pop("awaiting_search", None)
            context.user_data["awaiting_search_flow"] = {
                "plat": plat,
                "scope_name": plat_label,
                "back_callback": "cb_search",
                "chat_id": query.message.chat_id,
                "message_id": query.message.message_id,
            }
            context.user_data["active_card_msg_id"] = query.message.message_id
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="cb_search"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text(
                f"<blockquote>🔍 <b>Searching:</b> {plat_label}\n\n"
                f"✏️ <i>{prompt_instruction}</i></blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        elif plat == "desi":
            context.user_data.pop("awaiting_model_range", None)
            context.user_data.pop("awaiting_vibex_range", None)
            context.user_data.pop("awaiting_category_range", None)
            context.user_data.pop("awaiting_wp_range", None)
            context.user_data.pop("active_search_results", None)
            context.user_data.pop("awaiting_search", None)
            markup = build_mmsdesi_hub_keyboard(back_callback="cb_search")
            await query.edit_message_text(
                "<blockquote>📹 <b>MMSDesi Hub</b>\nSelect search or browse categories:</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        elif plat == "mmsmaza":
            context.user_data.pop("awaiting_model_range", None)
            context.user_data.pop("awaiting_vibex_range", None)
            context.user_data.pop("awaiting_category_range", None)
            context.user_data.pop("awaiting_wp_range", None)
            context.user_data.pop("active_search_results", None)
            context.user_data.pop("awaiting_search", None)
            markup = build_mmsmaza_hub_keyboard(back_callback="cb_search")
            await query.edit_message_text(
                "<blockquote>📂 <b>MMSMaza Hub</b>\nSelect search or browse releases:</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return
    elif data == "sp_choose_kw:fm":
        context.user_data.pop("awaiting_model_range", None)
        context.user_data.pop("awaiting_vibex_range", None)
        context.user_data.pop("awaiting_category_range", None)
        context.user_data.pop("awaiting_wp_range", None)
        context.user_data.pop("active_search_results", None)
        context.user_data["awaiting_search_flow"] = {
            "plat": "fm",
            "scope_name": "DropMMS Topics",
            "back_callback": "sp_choose:fm",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        context.user_data["active_card_msg_id"] = query.message.message_id
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:fm"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            "<blockquote>🔍 <b>Searching:</b> 💬 DropMMS Forum\n\n"
            "✏️ <i>Please send the keyword or title to search (e.g. <code>1080p video</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data == "sp_choose_kw:mmst":
        context.user_data.pop("awaiting_model_range", None)
        context.user_data.pop("awaiting_vibex_range", None)
        context.user_data.pop("awaiting_category_range", None)
        context.user_data.pop("awaiting_wp_range", None)
        context.user_data.pop("active_search_results", None)
        context.user_data["awaiting_search_flow"] = {
            "plat": "mmst",
            "scope_name": "MMSTown Topics",
            "back_callback": "sp_choose:mmst",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        context.user_data["active_card_msg_id"] = query.message.message_id
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:mmst"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            "<blockquote>🔍 <b>Searching:</b> 💬 MMSTown Forum\n\n"
            "✏️ <i>Please send the keyword or title to search (e.g. <code>desi video</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data == "sp_choose_kw:vibex":
        context.user_data.pop("awaiting_model_range", None)
        context.user_data.pop("awaiting_vibex_range", None)
        context.user_data.pop("awaiting_category_range", None)
        context.user_data.pop("awaiting_wp_range", None)
        context.user_data.pop("active_search_results", None)
        context.user_data["awaiting_search_flow"] = {
            "plat": "vibex",
            "scope_name": "MMSVibex Videos",
            "back_callback": "sp_choose:vibex",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        context.user_data["active_card_msg_id"] = query.message.message_id
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:vibex"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            "<blockquote>🔍 <b>Searching:</b> ⚡ MMSVibex Videos\n\n"
            "✏️ <i>Please send the keyword or model name to search (e.g. <code>baddie</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data.startswith("sp_search_site:"):
        plat = data.split(":")[1]
        plat_label = "DropMMS" if plat == "fm" else "MMSTown"
        context.user_data["awaiting_search_flow"] = {
            "plat": plat,
            "forum_id": None,
            "scope_name": f"All {plat_label} Topics",
            "back_callback": f"sp_choose:{plat}",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        context.user_data["active_card_msg_id"] = query.message.message_id
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Categories", callback_data=f"sp_choose:{plat}"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            f"<blockquote>🔍 <b>Search {plat_label}</b>\n"
            "🌐 <b>Scope:</b> Entire Website (All Forums)\n"
            "🕒 <b>Sort:</b> Newest Uploads (Date Wise)\n\n"
            f"✏️ <i>Please send the keyword or title to search (e.g. <code>baddie</code> or <code>1080p</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data.startswith("sp_search_forum:"):
        short_id = int(data.split(":")[1])
        url = db.get_url_from_short_id(short_id) or ""
        cached_stats = context.user_data.get(f"cat_stats_{short_id}", {})
        cat_title = cached_stats.get("title") or "Forum Category"
        context.user_data["last_short_id"] = short_id
        m_fid = re.search(r"/forum/(\d+)-?", url)
        forum_id = m_fid.group(1) if m_fid else None
        plat = "mmst" if "mmstown" in url.lower() else "fm"

        context.user_data["awaiting_search_flow"] = {
            "plat": plat,
            "forum_id": forum_id,
            "scope_name": cat_title,
            "short_id": short_id,
            "back_callback": f"sp_cat:{short_id}",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        context.user_data["active_card_msg_id"] = query.message.message_id
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Category", callback_data=f"sp_cat:{short_id}"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            f"<blockquote>🔍 <b>Search Inside Category</b>\n"
            f"📁 <b>Forum:</b> {html.escape(cat_title)}\n"
            "🕒 <b>Sort:</b> Newest Uploads (Date Wise)\n\n"
            f"✏️ <i>Please send the keyword or title to search (e.g. <code>dance</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    elif data.startswith("sp_fp:"):
        _, plat, fid_str, page_str = data.split(":")
        page = int(page_str)
        forum_id = fid_str if fid_str != "all" else None
        search_state = context.user_data.get("active_search_results", {})
        query_text = search_state.get("query") or context.user_data.get("search_query", "")
        scope_name = search_state.get("scope_name")
        back_cb = search_state.get("back_callback", "cb_search")
        if not query_text:
            await query.edit_message_text("<blockquote>⚠️ Search query expired. Please search again.</blockquote>", parse_mode=ParseMode.HTML)
            return
        await _get_target_func("execute_platform_search", execute_platform_search)(
            update=update,
            context=context,
            plat=plat,
            query=query_text,
            edit_msg=query.message,
            page=page,
            forum_id=forum_id,
            scope_name=scope_name,
            back_callback=back_cb,
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
        markup = build_mmsvibex_options_keyboard(sort_key=sort_key, back_callback="sp_choose:vibex")
        card_text = (
            "<blockquote>"
            f"⚡ <b>MMSVibex: {sort_label}</b>\n\n"
            "Reply in chat with a custom range, count or page:\n"
            "• <code>5</code> ➔ First 5 items\n"
            "• <code>1-15</code> ➔ Items 1 to 15\n"
            "• <code>page 2</code> ➔ Full Page 2"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["active_card_msg_id"] = query.message.message_id
        return

    elif data.startswith("sp_vapply:"):
        _, sort_key, r_str = data.split(":")
        target_url = "https://mmsvibex.life/photos/" if sort_key == "photos" else f"https://mmsvibex.life/?filter={sort_key}"
        start_idx, end_idx, page_num = parse_model_range_input(r_str)
        context.user_data.pop("awaiting_vibex_range", None)
        await _get_target_func("run_mmsvibex_listing_scrape", run_mmsvibex_listing_scrape)(
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
        await _get_target_func("run_mmsvibex_listing_scrape", run_mmsvibex_listing_scrape)(
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
            "mmsmaza": ("MMSMaza", "https://mmsmaza.im/"),
        }
        s_info = site_map.get(site_key, ("Omaal63", "https://omaal63.net/"))
        site_name, target_url = s_info
        context.user_data.pop("awaiting_model_range", None)
        context.user_data.pop("awaiting_vibex_range", None)
        context.user_data.pop("awaiting_category_range", None)
        context.user_data.pop("awaiting_wp_range", None)
        context.user_data.pop("active_search_results", None)
        context.user_data.pop("awaiting_search", None)

        if site_key == "mmsmaza":
            markup = build_mmsmaza_hub_keyboard(back_callback="cb_search")
        else:
            markup = build_wp_site_hub_keyboard(site_key=site_key, back_callback="cb_search")
        card_text = (
            "<blockquote>"
            f"🌐 <b>{site_name} Hub</b>\n"
            "Select an option or search inside this website:"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["active_card_msg_id"] = query.message.message_id
        return

    elif data.startswith("sp_wpsearch:"):
        _, site_key = data.split(":")
        site_map = {
            "omaal": "Omaal63",
            "desijugar": "DesiJugar",
            "gulabi": "GulabiHub",
            "mmsmaza": "MMSMaza",
        }
        site_name = site_map.get(site_key, "Website")
        context.user_data.pop("awaiting_model_range", None)
        context.user_data.pop("awaiting_vibex_range", None)
        context.user_data.pop("awaiting_category_range", None)
        context.user_data.pop("awaiting_wp_range", None)
        context.user_data.pop("active_search_results", None)
        context.user_data.pop("awaiting_search", None)

        context.user_data["awaiting_search_flow"] = {
            "plat": f"wp_{site_key}",
            "scope_name": f"{site_name} Videos",
            "back_callback": f"sp_wpsite:{site_key}",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "site_key": site_key,
        }
        context.user_data["active_card_msg_id"] = query.message.message_id
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data=f"sp_wpsite:{site_key}"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            f"<blockquote>🔍 <b>Search {site_name}</b>\n"
            f"🌐 <b>Scope:</b> Entire Website ({site_name})\n\n"
            "✏️ <i>Please send the keyword or title to search (e.g. <code>baddie</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    elif data.startswith("sp_wplatest:"):
        _, site_key = data.split(":")
        site_map = {
            "omaal": ("Omaal63", "https://omaal63.net/"),
            "desijugar": ("DesiJugar", "https://desijugar.me/"),
            "gulabi": ("GulabiHub", "https://gulabihub.com/"),
            "mmsmaza": ("MMSMaza", "https://mmsmaza.im/"),
        }
        s_info = site_map.get(site_key, ("Omaal63", "https://omaal63.net/"))
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
                InlineKeyboardButton("🔙 Back", callback_data=f"sp_wpsite:{site_key}"),
                InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel"),
            ],
        ])
        card_text = (
            "<blockquote>"
            f"🌐 <b>{site_name}: Latest Posts</b>\n\n"
            "Reply in chat with a custom range, count or page:\n"
            "• <code>5</code> ➔ First 5 posts\n"
            "• <code>1-15</code> ➔ Posts 1 to 15\n"
            "• <code>page 2</code> ➔ Full Page 2"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["active_card_msg_id"] = query.message.message_id
        return

    elif data.startswith("sp_wpcats:"):
        _, site_key = data.split(":")
        site_map = {
            "omaal": "Omaal63",
            "desijugar": "DesiJugar",
            "gulabi": "GulabiHub",
            "mmsmaza": "MMSMaza",
        }
        site_name = site_map.get(site_key, "Website")
        try:
            await query.edit_message_text(
                f"<blockquote>📁 <b>{site_name} Categories</b>\n⏳ <i>Fetching categories...</i></blockquote>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        raw_cats = await asyncio.to_thread(_get_target_func("get_wp_categories", get_wp_categories), site_key)
        if not raw_cats:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=f"sp_wpsite:{site_key}"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text(
                f"<blockquote>📁 <b>{site_name} Categories</b>\n⚠️ <i>No categories found or site unreachable.</i></blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        cat_items = []
        for c in raw_cats:
            sid = db.get_or_create_short_id(c["url"])
            context.user_data[f"wpcat_{sid}"] = {
                "name": c["name"],
                "url": c["url"],
                "site_key": site_key,
            }
            cat_items.append({"name": c["name"], "short_id": sid})

        markup = build_wp_categories_keyboard(cat_items, site_key=site_key, back_callback=f"sp_wpsite:{site_key}")
        card_text = (
            "<blockquote>"
            f"📁 <b>{site_name} Categories</b>\n"
            "Select a category to browse:"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["active_card_msg_id"] = query.message.message_id
        return

    elif data.startswith("sp_wpcat:"):
        parts = data.split(":")
        site_key = parts[1]
        cat_sid = int(parts[2])
        page = 1

        cat_info = context.user_data.get(f"wpcat_{cat_sid}")
        cat_url = cat_info["url"] if cat_info else db.get_url_from_short_id(cat_sid)
        cat_name = cat_info.get("name", "Category") if cat_info else "Category"

        site_map = {
            "omaal": "Omaal63",
            "desijugar": "DesiJugar",
            "gulabi": "GulabiHub",
        }
        site_name = site_map.get(site_key, "WordPress")

        try:
            await query.edit_message_text(
                f"<blockquote>📁 <b>{site_name}: {cat_name}</b>\n⏳ <i>Fetching posts (Page {page})...</i></blockquote>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        results = await asyncio.to_thread(_get_target_func("get_wp_listing_posts", get_wp_listing_posts), cat_url, page, 10)
        back_cb = f"sp_wpcats:{site_key}"
        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text(
                f"<blockquote>📁 <b>{site_name}: {cat_name}</b>\n⚠️ <i>No posts found in this category.</i></blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        total_pages = max(page + 1, 2) if len(results) == 10 else page
        card_text = format_clean_category_posts_page(
            site_name=site_name,
            cat_name=cat_name,
            page=page,
            total_pages=total_pages,
            total_count=len(results),
            items=results,
            delivered_indices=set(),
        )

        page_pfx = f"sp_wppag_cat:{site_key}:{cat_sid}"
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=page_pfx,
            back_callback=back_cb,
        )

        context.user_data["active_search_results"] = {
            "plat": f"wp_{site_key}",
            "is_category_browse": True,
            "site_name": site_name,
            "cat_name": cat_name,
            "query": cat_name,
            "scope_name": f"{site_name}: {cat_name}",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": len(results),
            "items": results,
            "delivered_indices": set(),
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "back_callback": back_cb,
            "page_callback_prefix": page_pfx,
            "cat_sid": cat_sid,
            "cat_url": cat_url,
        }

        await query.edit_message_text(
            card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        context.user_data["active_card_msg_id"] = query.message.message_id
        return

    elif data.startswith("sp_wppag_cat:"):
        parts = data.split(":")
        site_key = parts[1]
        cat_sid = int(parts[2])
        page = int(parts[3])

        cat_info = context.user_data.get(f"wpcat_{cat_sid}")
        cat_url = cat_info["url"] if cat_info else db.get_url_from_short_id(cat_sid)
        cat_name = cat_info.get("name", "Category") if cat_info else "Category"

        site_map = {
            "omaal": "Omaal63",
            "desijugar": "DesiJugar",
            "gulabi": "GulabiHub",
        }
        site_name = site_map.get(site_key, "WordPress")

        try:
            await query.edit_message_text(
                f"<blockquote>📁 <b>{site_name}: {cat_name}</b>\n⏳ <i>Fetching posts (Page {page})...</i></blockquote>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        results = await asyncio.to_thread(_get_target_func("get_wp_listing_posts", get_wp_listing_posts), cat_url, page, 10)
        back_cb = f"sp_wpcats:{site_key}"
        if not results:
            page = max(1, page - 1)
            results = await asyncio.to_thread(_get_target_func("get_wp_listing_posts", get_wp_listing_posts), cat_url, page, 10)

        total_pages = max(page + 1, page) if len(results) == 10 else page
        card_text = format_clean_category_posts_page(
            site_name=site_name,
            cat_name=cat_name,
            page=page,
            total_pages=total_pages,
            total_count=len(results),
            items=results,
            delivered_indices=set(),
        )

        page_pfx = f"sp_wppag_cat:{site_key}:{cat_sid}"
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=page_pfx,
            back_callback=back_cb,
        )

        context.user_data["active_search_results"] = {
            "plat": f"wp_{site_key}",
            "is_category_browse": True,
            "site_name": site_name,
            "cat_name": cat_name,
            "query": cat_name,
            "scope_name": f"{site_name}: {cat_name}",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": len(results),
            "items": results,
            "delivered_indices": set(),
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "back_callback": back_cb,
            "page_callback_prefix": page_pfx,
            "cat_sid": cat_sid,
            "cat_url": cat_url,
        }

        await query.edit_message_text(
            card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        context.user_data["active_card_msg_id"] = query.message.message_id
        return

    elif data.startswith("sp_wppag_search:"):
        parts = data.split(":")
        site_key = parts[1]
        page = int(parts[2])
        search_state = context.user_data.get("active_search_results", {})
        s_query = search_state.get("query") or context.user_data.get("search_query", "")
        if not s_query:
            await query.edit_message_text(
                "<blockquote>⚠️ Search query expired. Please search again.</blockquote>",
                parse_mode=ParseMode.HTML,
            )
            return
        await _get_target_func("execute_platform_search", execute_platform_search)(
            update=update,
            context=context,
            plat=f"wp_{site_key}",
            query=s_query,
            edit_msg=query.message,
            page=page,
            back_callback=f"sp_wpsite:{site_key}",
        )
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
        await _get_target_func("run_wp_listing_scrape", run_wp_listing_scrape)(
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
        await _get_target_func("run_wp_listing_scrape", run_wp_listing_scrape)(
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
            details = await asyncio.to_thread(_get_target_func("get_mmsvibex_video_details", get_mmsvibex_video_details), target_url)

        if not details:
            await query.edit_message_text("❌ Session expired. Please send the link again.")
            return

        if mode == "norm":
            col_markup = None
            if details.get("collection_url"):
                col_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📦 Extract All Collection Parts", callback_data=f"mv_all:{sid}")
                ]])
            await _get_target_func("send_post_card", send_post_card)(
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
            details = await asyncio.to_thread(_get_target_func("get_mmsvibex_video_details", get_mmsvibex_video_details), target_url)

        col_url = details.get("collection_url") if details else None
        if not col_url and target_url:
            col_url = target_url

        chat_id = query.message.chat_id
        start_scrape_for_chat(chat_id)
        status_msg = await query.message.reply_text("🚀 <i>Extracting all collection parts...</i>", parse_mode=ParseMode.HTML)
        try:
            col_items = await asyncio.to_thread(_get_target_func("get_mmsvibex_actor_videos", get_mmsvibex_actor_videos), col_url) if col_url else []
            if not col_items and details:
                col_items = [{"title": details.get("title", "Video"), "url": target_url}]

            await status_msg.edit_text(
                f"<blockquote>📦 <b>Found {len(col_items)} part(s) in collection!</b>\n<i>Extracting direct MP4s...</i></blockquote>",
                parse_mode=ParseMode.HTML,
            )

            for idx, item in enumerate(col_items, 1):
                if is_scrape_cancelled(chat_id):
                    break
                p_details = await asyncio.to_thread(_get_target_func("get_mmsvibex_video_details", get_mmsvibex_video_details), item["url"])
                p_details["hide_collection_link"] = True
                await _get_target_func("send_post_card", send_post_card)(context.bot, chat_id, p_details, user_id=query.from_user.id)
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
        await _get_target_func("run_wp_listing_scrape", run_wp_listing_scrape)(
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

        stats = await asyncio.to_thread(_get_target_func("get_dropmms_category_stats", get_dropmms_category_stats), url)
        cat_title = stats.get("title") or cat_title
        total_str = stats.get("total_topics_str") or "Available"

        context.user_data[f"cat_stats_{short_id}"] = {
            "title": cat_title,
            "total_str": total_str,
            "url": stats.get("url") or url,
        }

        back_cb = "sp_choose:mmst" if "mmstown" in url.lower() else "sp_choose:fm"
        markup = build_forum_sort_keyboard(short_id, back_callback=back_cb)

        card_text = (
            "<blockquote>"
            f"💬 <b>{html.escape(cat_title)}</b>\n"
            f"📊 <b>Total Topics:</b> {total_str}\n"
            "🎯 Select a sorting order or search inside this forum:"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["active_card_msg_id"] = query.message.message_id
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

        markup = build_category_options_keyboard(short_id, sort_val)
        prompt_text = format_category_options_card(cat_title, total_str, sort_val)
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

        await _get_target_func("run_forum_category_scrape", run_forum_category_scrape)(
            bot=context.bot,
            chat_id=query.message.chat_id,
            target_url=url,
            only_today=(date_mode == "today"),
            date_filter=date_mode,
            sort_by=sort_val,
            status_msg=query.message,
            user_id=query.from_user.id,
            cat_title=cat_title,
            context=context,
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

        await _get_target_func("run_forum_category_scrape", run_forum_category_scrape)(
            bot=context.bot,
            chat_id=chat_id,
            target_url=url,
            only_today=only_today,
            req_limit=req_limit,
            status_msg=query.message,
            user_id=query.from_user.id,
            cat_title=cat_title,
            context=context,
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
        await _get_target_func("execute_platform_search", execute_platform_search)(update, context, plat, query_text, edit_msg=query.message, page=page)
    elif data.startswith("sp_do:"):
        plat = data.split(":")[1]
        query_text = context.user_data.get("search_query", "").strip()
        if not query_text:
            await query.edit_message_text("⚠️ Search query expired. Please run <code>/search</code> again.", parse_mode=ParseMode.HTML)
            return
        await _get_target_func("execute_platform_search", execute_platform_search)(update, context, plat, query_text, edit_msg=query.message, page=1)
    elif data.startswith("sp_switch:"):
        plat = data.split(":")[1]
        query_text = context.user_data.get("search_query", "").strip()
        if not query_text:
            await query.edit_message_text("⚠️ Search query expired. Please run <code>/search</code> again.", parse_mode=ParseMode.HTML)
            return
        await _get_target_func("execute_platform_search", execute_platform_search)(update, context, plat, query_text, edit_msg=query.message, page=1)
    elif data in ("sp_back_lc", "sp_back_lz", "sp_back_xvid", "sp_back_hs", "sp_back_tc"):
        plat = data.split("_")[2]
        q = context.user_data.get(f"last_{plat}_query", "").strip()
        if q:
            await _get_target_func("execute_platform_search", execute_platform_search)(update, context, plat, q, edit_msg=query.message)
        else:
            await search_command(update, context)
    elif data.startswith("lz_mdl:"):
        target = data.split(":", 1)[1]
        url = db.get_url_from_short_id(int(target)) if target.isdigit() else target
        slug = target
        if url and (url.startswith("http://") or url.startswith("https://")):
            parts_u = [p for p in url.strip("/").split("/") if p and p not in ("video", "videos")]
            slug = parts_u[-1] if parts_u else target
        model_name = slug.replace("-", " ").replace("_", " ").title()
        back_cb = "sp_back_lz" if context.user_data.get("last_lz_query") else "cb_search"
        markup = build_leakedzone_hub_keyboard(model_slug=target, back_callback=back_cb)
        card_text = (
            "<blockquote>"
            f"📹 <b>{html.escape(model_name)}</b>\n"
            "🌐 <b>Platform:</b> LeakedZone\n"
            f"🔗 <code>https://leakedzone.com/{html.escape(slug)}</code>\n\n"
            "Select sorting order to view videos:"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data.startswith("xvid_mdl:"):
        target = data.split(":", 1)[1]
        url = db.get_url_from_short_id(int(target)) if target.isdigit() else target
        slug = target
        if url and (url.startswith("http://") or url.startswith("https://")):
            parts_u = [p for p in url.strip("/").split("/") if p and p not in ("videos", "video", "tags", "models")]
            slug = parts_u[-1] if parts_u else target
        model_name = slug.replace("-", " ").replace("_", " ").title()
        back_cb = "sp_back_xvid" if context.user_data.get("last_xvid_query") else "cb_search"
        markup = build_xvideo_hub_keyboard(tag_or_slug=target, back_callback=back_cb)
        card_text = (
            "<blockquote>"
            f"📹 <b>{html.escape(model_name)}</b>\n"
            "🌐 <b>Platform:</b> X-Video Tube\n\n"
            "Select sorting order to view videos:"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data.startswith("hs_mdl:"):
        target = data.split(":", 1)[1]
        url = db.get_url_from_short_id(int(target)) if target.isdigit() else target
        slug = target
        if url and (url.startswith("http://") or url.startswith("https://")):
            parts_u = [p for p in url.strip("/").split("/") if p and p not in ("videos", "video", "models", "tags")]
            slug = parts_u[-1] if parts_u else target
        model_name = slug.replace("-", " ").replace("_", " ").title()
        back_cb = "sp_back_hs" if context.user_data.get("last_hs_query") else "cb_search"
        markup = build_hornysapiens_hub_keyboard(model_slug=target, back_callback=back_cb)
        card_text = (
            "<blockquote>"
            f"📹 <b>{html.escape(model_name)}</b>\n"
            "🌐 <b>Platform:</b> HornySapiens\n\n"
            "Select sorting order to view videos:"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data.startswith("tc_mdl:"):
        target = data.split(":", 1)[1]
        url = db.get_url_from_short_id(int(target)) if target.isdigit() else target
        slug = target
        if url and (url.startswith("http://") or url.startswith("https://")):
            parts_u = [p for p in url.strip("/").split("/") if p and p not in ("videos", "video", "actor", "actors")]
            slug = parts_u[-1] if parts_u else target
        model_name = slug.replace("-", " ").replace("_", " ").title()
        back_cb = "sp_back_tc" if context.user_data.get("last_tc_query") else "cb_search"
        markup = build_thotchicks_hub_keyboard(actor_slug=target, back_callback=back_cb)
        card_text = (
            "<blockquote>"
            f"💃 <b>{html.escape(model_name)}</b>\n"
            "🌐 <b>Platform:</b> ThotChicks\n\n"
            "Select sorting order to view videos:"
            "</blockquote>"
        )
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return
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

        stats = await asyncio.to_thread(_get_target_func("get_livecam_model_stats", get_livecam_model_stats), url)
        model_name = stats.get("name") or model_name
        total_str = stats.get("total_videos_str") or "Available"

        context.user_data[f"model_stats_{short_id}"] = {
            "name": model_name,
            "total_str": total_str,
            "url": stats.get("url") or url,
        }

        back_cb = "sp_back_lc" if context.user_data.get("last_lc_query") else "cb_search"
        markup = build_model_sort_keyboard(short_id, back_callback=back_cb)
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

        await _get_target_func("run_livecam_model_scrape", run_livecam_model_scrape)(
            bot=context.bot,
            chat_id=chat_id,
            target_url=url,
            only_today=only_today,
            req_limit=req_limit,
            status_msg=query.message,
            user_id=query.from_user.id,
        )
    elif data.startswith("lz_search"):
        model_slug = data.split(":")[1] if ":" in data else ""
        scope_name = f"LeakedZone ({model_slug.title()})" if model_slug else "LeakedZone"
        context.user_data["awaiting_search_flow"] = {
            "plat": "lz",
            "scope_name": scope_name,
            "back_callback": "sp_choose:lz",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:lz"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            f"<blockquote>🔍 <b>Search {scope_name}</b>\n\n✏️ <i>Please send the keyword or title to search (e.g. <code>jasmine</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    elif data.startswith("xvid_search"):
        slug = data.split(":")[1] if ":" in data else ""
        scope_name = f"X-Video ({slug})" if slug else "X-Video Tube"
        context.user_data["awaiting_search_flow"] = {
            "plat": "xvid",
            "scope_name": scope_name,
            "back_callback": "sp_choose:xvid",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:xvid"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            f"<blockquote>🔍 <b>Search {scope_name}</b>\n\n✏️ <i>Please send the keyword or tag to search:</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    elif data.startswith("hs_search"):
        model_slug = data.split(":")[1] if ":" in data else ""
        scope_name = f"HornySapiens ({model_slug.title()})" if model_slug else "HornySapiens"
        context.user_data["awaiting_search_flow"] = {
            "plat": "hs",
            "scope_name": scope_name,
            "back_callback": "sp_choose:hs",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:hs"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            f"<blockquote>🔍 <b>Search {scope_name}</b>\n\n✏️ <i>Please send the keyword or model name to search:</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    elif data.startswith("tc_search"):
        actor_slug = data.split(":")[1] if ":" in data else ""
        scope_name = f"ThotChicks ({actor_slug.title()})" if actor_slug else "ThotChicks"
        context.user_data["awaiting_search_flow"] = {
            "plat": "tc",
            "scope_name": scope_name,
            "back_callback": "sp_choose:tc",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:tc"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            f"<blockquote>🔍 <b>Search {scope_name}</b>\n\n✏️ <i>Please send the keyword or actor name to search:</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    elif data == "desi_search":
        context.user_data["awaiting_search_flow"] = {
            "plat": "desi",
            "scope_name": "MMSDesi",
            "back_callback": "sp_choose:desi",
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
        }
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="sp_choose:desi"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        await query.edit_message_text(
            "<blockquote>🔍 <b>Search MMSDesi</b>\n\n✏️ <i>Please send the keyword or title to search (e.g. <code>college</code>):</i></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    elif data.startswith("lz_sort:") or data.startswith("lz_pg:"):
        parts = data.split(":")
        model_slug = parts[1] if len(parts) > 1 and parts[1] else "jasminesherni"
        sort_val = parts[2] if len(parts) > 2 else "newest"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        target = model_slug
        if target.isdigit():
            real_url = db.get_url_from_short_id(int(target))
            if real_url:
                parts_u = [p for p in real_url.strip("/").split("/") if p and p not in ("video", "videos")]
                target = parts_u[-1] if parts_u else target
        try:
            results = await asyncio.to_thread(get_leakedzone_model_videos, target, sort_val, page, 10)
        except Exception as e:
            await query.edit_message_text(f"❌ Error fetching videos: {html.escape(str(e))}")
            return

        back_cb = f"lz_mdl:{model_slug}" if model_slug else "sp_choose:lz"
        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text("<blockquote>❌ No more videos found.</blockquote>", parse_mode=ParseMode.HTML, reply_markup=markup)
            return

        total_pages = max(page + 1, 2) if len(results) >= 10 else page
        total_count = (page - 1) * 10 + len(results) + (10 if len(results) >= 10 else 0)
        display_name = target.replace("-", " ").replace("_", " ").title()
        card_text = format_clean_search_results_page(
            query=f"{display_name} ({sort_val.title()})",
            scope_name="LeakedZone",
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=results,
            delivered_indices=set(),
        )
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=f"lz_pg:{model_slug}:{sort_val}",
            back_callback=back_cb,
        )
        context.user_data["active_search_results"] = {
            "plat": "lz",
            "query": target,
            "scope_name": "LeakedZone",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": results,
            "delivered_indices": set(),
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "back_callback": back_cb,
            "page_callback_prefix": f"lz_pg:{model_slug}:{sort_val}",
        }
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data.startswith("xvid_sort:") or data.startswith("xvid_pg:"):
        parts = data.split(":")
        slug = parts[1] if len(parts) > 1 and parts[1] else "jasminesherni-onlyfans-leaked"
        sort_val = parts[2] if len(parts) > 2 else "latest"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        target_url = None
        if slug.isdigit():
            target_url = db.get_url_from_short_id(int(slug))
        if not target_url:
            if "/tags/" in slug or "/models/" in slug:
                target_url = f"https://x-video.tube{slug}" if slug.startswith("/") else f"https://x-video.tube/{slug}"
            elif "-onlyfans" in slug or "leaked" in slug:
                target_url = f"https://x-video.tube/tags/{slug}/videos/"
            else:
                target_url = f"https://x-video.tube/tags/{slug}-onlyfans-leaked/videos/"
        try:
            results = await asyncio.to_thread(_get_target_func("get_kvs_listing_items", get_kvs_listing_items), target_url, sort_val, page, 10)
        except Exception as e:
            await query.edit_message_text(f"❌ Error fetching videos: {html.escape(str(e))}")
            return

        back_cb = f"xvid_mdl:{slug}" if slug else "sp_choose:xvid"
        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text("<blockquote>❌ No more videos found.</blockquote>", parse_mode=ParseMode.HTML, reply_markup=markup)
            return

        total_pages = max(page + 1, 2) if len(results) >= 10 else page
        total_count = (page - 1) * 10 + len(results) + (10 if len(results) >= 10 else 0)
        display_name = slug
        if target_url:
            parts_u = [p for p in target_url.strip("/").split("/") if p and p not in ("videos", "video", "tags", "models")]
            if parts_u:
                display_name = parts_u[-1].replace("-", " ").replace("_", " ").title()
        card_text = format_clean_search_results_page(
            query=f"{display_name} ({sort_val.title()})",
            scope_name="X-Video Tube",
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=results,
            delivered_indices=set(),
        )
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=f"xvid_pg:{slug}:{sort_val}",
            back_callback=back_cb,
        )
        context.user_data["active_search_results"] = {
            "plat": "xvid",
            "query": slug,
            "scope_name": "X-Video Tube",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": results,
            "delivered_indices": set(),
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "back_callback": back_cb,
            "page_callback_prefix": f"xvid_pg:{slug}:{sort_val}",
        }
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data.startswith("hs_sort:") or data.startswith("hs_pg:"):
        parts = data.split(":")
        slug = parts[1] if len(parts) > 1 and parts[1] else "jasmine-sherni"
        sort_val = parts[2] if len(parts) > 2 else "latest"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        target_url = None
        if slug.isdigit():
            target_url = db.get_url_from_short_id(int(slug))
        if not target_url:
            target_url = f"https://hornysapiens.com/models/{slug}/"
        try:
            results = await asyncio.to_thread(_get_target_func("get_kvs_listing_items", get_kvs_listing_items), target_url, sort_val, page, 10)
        except Exception as e:
            await query.edit_message_text(f"❌ Error fetching videos: {html.escape(str(e))}")
            return

        back_cb = f"hs_mdl:{slug}" if slug else "sp_choose:hs"
        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text("<blockquote>❌ No more videos found.</blockquote>", parse_mode=ParseMode.HTML, reply_markup=markup)
            return

        total_pages = max(page + 1, 2) if len(results) >= 10 else page
        total_count = (page - 1) * 10 + len(results) + (10 if len(results) >= 10 else 0)
        display_name = slug
        if target_url:
            parts_u = [p for p in target_url.strip("/").split("/") if p and p not in ("videos", "video", "tags", "models")]
            if parts_u:
                display_name = parts_u[-1].replace("-", " ").replace("_", " ").title()
        card_text = format_clean_search_results_page(
            query=f"{display_name} ({sort_val.title()})",
            scope_name="HornySapiens",
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=results,
            delivered_indices=set(),
        )
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=f"hs_pg:{slug}:{sort_val}",
            back_callback=back_cb,
        )
        context.user_data["active_search_results"] = {
            "plat": "hs",
            "query": slug,
            "scope_name": "HornySapiens",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": results,
            "delivered_indices": set(),
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "back_callback": back_cb,
            "page_callback_prefix": f"hs_pg:{slug}:{sort_val}",
        }
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data.startswith("tc_sort:") or data.startswith("tc_pg:"):
        parts = data.split(":")
        slug = parts[1] if len(parts) > 1 and parts[1] else "jasmine-sherni"
        sort_val = parts[2] if len(parts) > 2 else "newest"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        target_url = None
        if slug.isdigit():
            target_url = db.get_url_from_short_id(int(slug))
        if not target_url:
            target_url = f"https://thotchicks.com/actor/{slug}/"
        try:
            results = await asyncio.to_thread(get_thotchicks_listing_items, target_url, sort_val, page, 10)
        except Exception as e:
            await query.edit_message_text(f"❌ Error fetching videos: {html.escape(str(e))}")
            return

        back_cb = f"tc_mdl:{slug}" if slug else "sp_choose:tc"
        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text("<blockquote>❌ No more videos found.</blockquote>", parse_mode=ParseMode.HTML, reply_markup=markup)
            return

        total_pages = max(page + 1, 2) if len(results) >= 10 else page
        total_count = (page - 1) * 10 + len(results) + (10 if len(results) >= 10 else 0)
        display_name = slug
        if target_url:
            parts_u = [p for p in target_url.strip("/").split("/") if p and p not in ("videos", "video", "tags", "models", "actor", "actors")]
            if parts_u:
                display_name = parts_u[-1].replace("-", " ").replace("_", " ").title()
        card_text = format_clean_search_results_page(
            query=f"{display_name} ({sort_val.title()})",
            scope_name="ThotChicks",
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=results,
            delivered_indices=set(),
        )
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=f"tc_pg:{slug}:{sort_val}",
            back_callback=back_cb,
        )
        context.user_data["active_search_results"] = {
            "plat": "tc",
            "query": slug,
            "scope_name": "ThotChicks",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": results,
            "delivered_indices": set(),
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "back_callback": back_cb,
            "page_callback_prefix": f"tc_pg:{slug}:{sort_val}",
        }
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data.startswith("desi_cat:") or data.startswith("desi_pg:"):
        parts = data.split(":")
        cat_key = parts[1]
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
        cat_names = {"trending": "Trending", "desi-new": "Desi New", "desi-old": "Desi Old", "tango-strip": "Tango Strip"}
        cat_name = cat_names.get(cat_key, "Desi New")
        try:
            results = await asyncio.to_thread(get_mmsdesi_category_videos, cat_key, page, 10)
        except Exception as e:
            await query.edit_message_text(f"❌ Error fetching videos: {html.escape(str(e))}")
            return

        back_cb = "sp_choose:desi"
        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            await query.edit_message_text("<blockquote>❌ No more videos found in this category.</blockquote>", parse_mode=ParseMode.HTML, reply_markup=markup)
            return

        total_pages = max(page + 1, 2) if len(results) >= 10 else page
        total_count = (page - 1) * 10 + len(results) + (10 if len(results) >= 10 else 0)
        card_text = format_clean_search_results_page(
            query=f"Category: {cat_name}",
            scope_name="MMSDesi",
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=results,
            delivered_indices=set(),
        )
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=f"desi_pg:{cat_key}",
            back_callback=back_cb,
        )
        context.user_data["active_search_results"] = {
            "plat": "desi",
            "query": cat_name,
            "scope_name": "MMSDesi",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": results,
            "delivered_indices": set(),
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "back_callback": back_cb,
            "page_callback_prefix": f"desi_pg:{cat_key}",
        }
        await query.edit_message_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    elif data == "sp_cancel":
        context.user_data.pop("awaiting_search", None)
        context.user_data.pop("search_query", None)
        context.user_data.pop("awaiting_model_range", None)
        context.user_data.pop("awaiting_category_range", None)
        context.user_data.pop("awaiting_vibex_range", None)
        context.user_data.pop("awaiting_wp_range", None)
        context.user_data.pop("awaiting_search_flow", None)
        context.user_data.pop("active_search_results", None)
        try:
            await query.message.delete()
        except Exception:
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
    elif data.startswith("setmode_"):
        new_mode = data.split("_")[1]
        set_search_mode(new_mode)
        m_check = " ✅" if new_mode == "model" else ""
        v_check = " ✅" if new_mode == "video" else ""
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📹 Model Profile Search (Default){m_check}", callback_data="setmode_model")],
            [InlineKeyboardButton(f"🎬 Direct Video Search{v_check}", callback_data="setmode_video")],
            [InlineKeyboardButton("🔙 Back", callback_data="cb_search"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
        ])
        label = "Model Profile Search (Default)" if new_mode == "model" else "Direct Video Search"
        text = (
            "<blockquote>"
            f"✅ <b>Search Mode Updated to {label}!</b>\n\n"
            f"• <b>Active Mode:</b> <code>{new_mode.upper()}</code>\n\n"
            "All future searches on sites 1, 2, 3, 4 will use this flow.\n"
            "You can change this anytime with <code>/mode</code> or CLI flag <code>--search-mode</code>."
            "</blockquote>"
        )
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
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
            target_proc_topic = _get_target_func("process_topic_scrape", process_topic_scrape)
            await target_proc_topic(context.bot, query.message.chat_id, target_url, user_id=query.from_user.id)
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


