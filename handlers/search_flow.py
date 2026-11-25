# handlers/search_flow.py
"""
Search execution, platform routing, model profile searches, and pagination workflows.
"""

import html
import logging
import asyncio
from urllib.parse import quote_plus

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db
import messages
from config import BASE_URL
from handlers.session import get_search_mode
from handlers.global_search import execute_global_search

from ui import format_clean_search_results_page
from keyboards import (
    build_search_results_clean_keyboard,
    build_models_keyboard,
    build_livecam_models_keyboard,
)

from scraper import (
    search_livecam_models,
    search_mmsvibex,
    search_forum_advanced,
)
from engines.wordpress import get_wp_listing_posts
from engines.leakedzone import search_leakedzone, search_leakedzone_models
from engines.kvs import search_kvs, search_kvs_models
from engines.thotchicks import search_thotchicks, search_thotchicks_actors
from engines.mmsdesi import search_mmsdesi

import sys

logger = logging.getLogger(__name__)


def _get_target_func(name: str, fallback):
    """Retrieve function from bot module if patched in tests, else fallback."""
    bot_mod = sys.modules.get("bot")
    if bot_mod and hasattr(bot_mod, name):
        return getattr(bot_mod, name)
    return fallback


async def execute_platform_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    plat: str,
    query: str,
    edit_msg=None,
    page: int = 1,
    forum_id: int | str | None = None,
    scope_name: str | None = None,
    back_callback: str | None = None,
):
    """Execute search on the selected platform with total counts and multi-page pagination."""
    clean_query = query.strip()
    if not clean_query:
        if edit_msg:
            await edit_msg.edit_text("⚠️ Search query cannot be empty.")
        else:
            await update.effective_message.reply_text("⚠️ Search query cannot be empty.")
        return

    # Clear awaiting search states now that search is actively being executed
    context.user_data.pop("awaiting_search", None)
    context.user_data.pop("awaiting_search_flow", None)

    plat_names = {
        "lc": "LiveCam Models",
        "fm": "DropMMS",
        "mmst": "MMSTown",
        "vibex": "MMSVibex Videos",
        "wplock": "WordPress Lockers",
    }
    plat_label = plat_names.get(plat, "Platform")
    display_scope = scope_name or plat_label
    status_text = f"🔍 <i>Searching {display_scope} for '<b>{html.escape(clean_query)}</b>' (Page {page})...</i>"

    chat_id = update.effective_chat.id if update.effective_chat else None
    if edit_msg:
        try:
            status_msg = await edit_msg.edit_text(status_text, parse_mode=ParseMode.HTML)
        except Exception:
            status_msg = await context.bot.send_message(chat_id=chat_id, text=status_text, parse_mode=ParseMode.HTML)
    else:
        status_msg = await context.bot.send_message(chat_id=chat_id, text=status_text, parse_mode=ParseMode.HTML)
    context.user_data["active_card_msg_id"] = status_msg.message_id

    if plat == "lc":
        try:
            results = await asyncio.to_thread(_get_target_func("search_livecam_models", search_livecam_models), clean_query, 8)
        except Exception as e:
            await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
            return

        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="cb_search"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"❌ No LiveCam models found for <b>{html.escape(clean_query)}</b>.\n\n"
                "<i>Tip: Check spelling or try a shorter name.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        models_data = []
        for idx, m in enumerate(results, start=1):
            name = m["name"]
            url = m["url"]
            short_id = db.get_or_create_short_id(url)
            models_data.append({"name": name, "short_id": short_id})

        context.user_data["last_lc_query"] = clean_query
        markup = build_livecam_models_keyboard(models_data, back_callback="cb_search")
        card_text = (
            "<blockquote>"
            "🔎 <b>Select LiveCam Model:</b>\n"
            f"<i>Matching '{html.escape(clean_query)}'</i>"
            "</blockquote>"
        )
        await status_msg.edit_text(
            card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    elif plat == "vibex":
        try:
            results = await asyncio.to_thread(_get_target_func("search_mmsvibex", search_mmsvibex), clean_query, page=page, limit=10)
        except Exception as e:
            await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
            return

        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="cb_search"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"❌ No MMSVibex videos found for <b>{html.escape(clean_query)}</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        total_pages = max(page + 1, 2) if len(results) == 10 else page
        total_count = page * 10 if len(results) == 10 else (page - 1) * 10 + len(results)

        card_text = format_clean_search_results_page(
            query=clean_query,
            scope_name="MMSVibex",
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=results,
            delivered_indices=set(),
        )

        page_pfx = "sp_fp:vibex:all"
        back_cb = "sp_choose:vibex"
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=page_pfx,
            back_callback=back_cb,
        )

        context.user_data["active_search_results"] = {
            "plat": "vibex",
            "query": clean_query,
            "scope_name": "MMSVibex",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": results,
            "delivered_indices": set(),
            "chat_id": status_msg.chat_id,
            "message_id": status_msg.message_id,
            "back_callback": back_cb,
        }

        await status_msg.edit_text(
            card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    elif plat in ("wplock", "omaal", "desijugar", "gulabi", "mmsmaza") or plat.startswith("wp_"):
        site_key = plat.replace("wp_", "") if plat != "wplock" else "desijugar"
        site_map = {
            "omaal": ("Omaal63", "https://omaal63.net"),
            "desijugar": ("DesiJugar", "https://desijugar.me"),
            "gulabi": ("GulabiHub", "https://gulabihub.com"),
            "mmsmaza": ("MMSMaza", "https://mmsmaza.im"),
        }
        site_name, base_url = site_map.get(site_key, ("Omaal63", "https://omaal63.net"))
        search_url = f"{base_url}/?s={quote_plus(clean_query)}"
        try:
            results = await asyncio.to_thread(_get_target_func("get_wp_listing_posts", get_wp_listing_posts), search_url, page, 10)
        except Exception as e:
            await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
            return

        back_cb = f"sp_wpsite:{site_key}"
        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"<blockquote>❌ No posts found on <b>{site_name}</b> for <code>{html.escape(clean_query)}</code>.</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        total_pages = max(page + 1, 2) if len(results) == 10 else page
        total_count = page * 10 if len(results) == 10 else (page - 1) * 10 + len(results)

        card_text = format_clean_search_results_page(
            query=clean_query,
            scope_name=site_name,
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=results,
            delivered_indices=set(),
        )

        page_pfx = f"sp_wppag_search:{site_key}"
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=page_pfx,
            back_callback=back_cb,
        )

        context.user_data["search_query"] = clean_query
        context.user_data["active_search_results"] = {
            "plat": f"wp_{site_key}",
            "query": clean_query,
            "scope_name": site_name,
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": results,
            "delivered_indices": set(),
            "chat_id": status_msg.chat_id,
            "message_id": status_msg.message_id,
            "back_callback": back_cb,
            "page_callback_prefix": page_pfx,
        }

        await status_msg.edit_text(
            card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    elif plat == "lz":
        mode = get_search_mode(context=context)
        back_cb = "sp_choose:lz"
        if mode == "model":
            try:
                results = await asyncio.to_thread(_get_target_func("search_leakedzone_models", search_leakedzone_models), clean_query, 8)
            except Exception as e:
                await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
                return

            if not results:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
                ])
                context.user_data["search_query"] = clean_query
                await status_msg.edit_text(
                    f"<blockquote>❌ No models found on <b>LeakedZone</b> matching <code>{html.escape(clean_query)}</code>.</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return

            models_data = []
            for idx, m in enumerate(results, start=1):
                name = m["name"]
                url = m["url"]
                short_id = db.get_or_create_short_id(url)
                models_data.append({"name": name, "short_id": short_id, "slug": m.get("slug")})

            context.user_data["last_lz_query"] = clean_query
            markup = build_models_keyboard(models_data, callback_prefix="lz_mdl", back_callback="cb_search", icon="📹")
            card_text = (
                "<blockquote>"
                "🔎 <b>Select LeakedZone Model:</b>\n"
                f"<i>Matching '{html.escape(clean_query)}'</i>"
                "</blockquote>"
            )
            try:
                await status_msg.edit_text(
                    card_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            except Exception as e:
                logger.debug(f"edit_text failed ({e}), falling back to send_message")
                if chat_id and context:
                    status_msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=card_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup,
                    )
        else:
            # Direct video search mode (Previous Github update)
            try:
                results = await asyncio.to_thread(_get_target_func("search_leakedzone", search_leakedzone), clean_query, page, 10)
            except Exception as e:
                await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
                return

            if not results:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
                ])
                context.user_data["search_query"] = clean_query
                await status_msg.edit_text(
                    f"<blockquote>❌ No videos found on <b>LeakedZone</b> for <code>{html.escape(clean_query)}</code>.</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return

            total_pages = max(page + 1, 2) if len(results) == 10 else page
            total_count = page * 10 if len(results) == 10 else (page - 1) * 10 + len(results)
            card_text = format_clean_search_results_page(
                query=clean_query,
                scope_name="LeakedZone",
                page=page,
                total_pages=total_pages,
                total_count=total_count,
                items=results,
                delivered_indices=set(),
            )
            page_pfx = "sp_fp:lz:all"
            markup = build_search_results_clean_keyboard(
                page=page,
                total_pages=total_pages,
                page_callback_prefix=page_pfx,
                back_callback=back_cb,
            )
            context.user_data["search_query"] = clean_query
            context.user_data["active_search_results"] = {
                "plat": "lz",
                "query": clean_query,
                "scope_name": "LeakedZone",
                "forum_id": None,
                "page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "items": results,
                "delivered_indices": set(),
                "chat_id": status_msg.chat_id,
                "message_id": status_msg.message_id,
                "back_callback": back_cb,
            }
            await status_msg.edit_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)

    elif plat in ("xvid", "xvideo", "xvideotube"):
        mode = get_search_mode(context=context)
        back_cb = "sp_choose:xvid"
        if mode == "model":
            try:
                results = await asyncio.to_thread(_get_target_func("search_kvs_models", search_kvs_models), "xvideotube", clean_query, 8)
            except Exception as e:
                await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
                return

            if not results:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
                ])
                context.user_data["search_query"] = clean_query
                await status_msg.edit_text(
                    f"<blockquote>❌ No models found on <b>X-Video Tube</b> matching <code>{html.escape(clean_query)}</code>.</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return

            models_data = []
            for idx, m in enumerate(results, start=1):
                name = m["name"]
                url = m["url"]
                short_id = db.get_or_create_short_id(url)
                models_data.append({"name": name, "short_id": short_id, "slug": m.get("slug")})

            context.user_data["last_xvid_query"] = clean_query
            markup = build_models_keyboard(models_data, callback_prefix="xvid_mdl", back_callback="cb_search", icon="📹")
            card_text = (
                "<blockquote>"
                "🔍 <b>Select X-Video Tube Model:</b>\n"
                f"<i>Matching '{html.escape(clean_query)}'</i>"
                "</blockquote>"
            )
            try:
                await status_msg.edit_text(
                    card_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            except Exception as e:
                logger.debug(f"edit_text failed ({e}), falling back to send_message")
                if chat_id and context:
                    status_msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=card_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup,
                    )
        else:
            # Direct video search mode (Previous Github update)
            try:
                results = await asyncio.to_thread(_get_target_func("search_kvs", search_kvs), "xvideotube", clean_query, page, 10)
            except Exception as e:
                await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
                return

            if not results:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
                ])
                context.user_data["search_query"] = clean_query
                await status_msg.edit_text(
                    f"<blockquote>❌ No videos found on <b>X-Video Tube</b> for <code>{html.escape(clean_query)}</code>.</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return

            total_pages = max(page + 1, 2) if len(results) == 10 else page
            total_count = page * 10 if len(results) == 10 else (page - 1) * 10 + len(results)
            card_text = format_clean_search_results_page(
                query=clean_query,
                scope_name="X-Video Tube",
                page=page,
                total_pages=total_pages,
                total_count=total_count,
                items=results,
                delivered_indices=set(),
            )
            page_pfx = "sp_fp:xvid:all"
            markup = build_search_results_clean_keyboard(
                page=page,
                total_pages=total_pages,
                page_callback_prefix=page_pfx,
                back_callback=back_cb,
            )
            context.user_data["search_query"] = clean_query
            context.user_data["active_search_results"] = {
                "plat": "xvid",
                "query": clean_query,
                "scope_name": "X-Video Tube",
                "forum_id": None,
                "page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "items": results,
                "delivered_indices": set(),
                "chat_id": status_msg.chat_id,
                "message_id": status_msg.message_id,
                "back_callback": back_cb,
            }
            await status_msg.edit_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)

    elif plat in ("hs", "hornysapiens", "viralxxxporn"):
        mode = get_search_mode(context=context)
        plat_label = "ViralXXXPorn" if plat == "viralxxxporn" else "HornySapiens"
        site_k = "viralxxxporn" if plat == "viralxxxporn" else "hornysapiens"
        back_cb = "sp_choose:hs"
        if mode == "model":
            try:
                results = await asyncio.to_thread(_get_target_func("search_kvs_models", search_kvs_models), site_k, clean_query, 8)
            except Exception as e:
                await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
                return

            if not results:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
                ])
                context.user_data["search_query"] = clean_query
                await status_msg.edit_text(
                    f"<blockquote>❌ No models found on <b>{plat_label}</b> matching <code>{html.escape(clean_query)}</code>.</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return

            models_data = []
            for idx, m in enumerate(results, start=1):
                name = m["name"]
                url = m["url"]
                short_id = db.get_or_create_short_id(url)
                models_data.append({"name": name, "short_id": short_id, "slug": m.get("slug")})

            context.user_data["last_hs_query"] = clean_query
            markup = build_models_keyboard(models_data, callback_prefix="hs_mdl", back_callback="cb_search", icon="📹")
            card_text = (
                "<blockquote>"
                f"🔎 <b>Select {plat_label} Model:</b>\n"
                f"<i>Matching '{html.escape(clean_query)}'</i>"
                "</blockquote>"
            )
            try:
                await status_msg.edit_text(
                    card_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            except Exception as e:
                logger.debug(f"edit_text failed ({e}), falling back to send_message")
                if chat_id and context:
                    status_msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=card_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup,
                    )
        else:
            # Direct video search mode (Previous Github update)
            try:
                results = await asyncio.to_thread(_get_target_func("search_kvs", search_kvs), site_k, clean_query, page, 10)
            except Exception as e:
                await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
                return

            if not results:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
                ])
                context.user_data["search_query"] = clean_query
                await status_msg.edit_text(
                    f"<blockquote>❌ No videos found on <b>{plat_label}</b> for <code>{html.escape(clean_query)}</code>.</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return

            total_pages = max(page + 1, 2) if len(results) == 10 else page
            total_count = page * 10 if len(results) == 10 else (page - 1) * 10 + len(results)
            card_text = format_clean_search_results_page(
                query=clean_query,
                scope_name=plat_label,
                page=page,
                total_pages=total_pages,
                total_count=total_count,
                items=results,
                delivered_indices=set(),
            )
            page_pfx = "sp_fp:hs:all"
            markup = build_search_results_clean_keyboard(
                page=page,
                total_pages=total_pages,
                page_callback_prefix=page_pfx,
                back_callback=back_cb,
            )
            context.user_data["search_query"] = clean_query
            context.user_data["active_search_results"] = {
                "plat": "hs",
                "query": clean_query,
                "scope_name": plat_label,
                "forum_id": None,
                "page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "items": results,
                "delivered_indices": set(),
                "chat_id": status_msg.chat_id,
                "message_id": status_msg.message_id,
                "back_callback": back_cb,
            }
            await status_msg.edit_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)

    elif plat in ("tc", "thotchicks"):
        mode = get_search_mode(context=context)
        back_cb = "sp_choose:tc"
        if mode == "model":
            try:
                results = await asyncio.to_thread(_get_target_func("search_thotchicks_actors", search_thotchicks_actors), clean_query, 8)
            except Exception as e:
                await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
                return

            if not results:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
                ])
                context.user_data["search_query"] = clean_query
                await status_msg.edit_text(
                    f"<blockquote>❌ No actors found on <b>ThotChicks</b> matching <code>{html.escape(clean_query)}</code>.</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return

            models_data = []
            for idx, m in enumerate(results, start=1):
                name = m["name"]
                url = m["url"]
                short_id = db.get_or_create_short_id(url)
                models_data.append({"name": name, "short_id": short_id, "slug": m.get("slug")})

            context.user_data["last_tc_query"] = clean_query
            markup = build_models_keyboard(models_data, callback_prefix="tc_mdl", back_callback="cb_search", icon="💃")
            card_text = (
                "<blockquote>"
                "🔍 <b>Select ThotChicks Actor:</b>\n"
                f"<i>Matching '{html.escape(clean_query)}'</i>"
                "</blockquote>"
            )
            try:
                await status_msg.edit_text(
                    card_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
            except Exception as e:
                logger.debug(f"edit_text failed ({e}), falling back to send_message")
                if chat_id and context:
                    status_msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=card_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup,
                    )
        else:
            # Direct video search mode (Previous Github update)
            try:
                results = await asyncio.to_thread(_get_target_func("search_thotchicks", search_thotchicks), clean_query, page, 10)
            except Exception as e:
                await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
                return

            if not results:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
                ])
                context.user_data["search_query"] = clean_query
                await status_msg.edit_text(
                    f"<blockquote>❌ No videos found on <b>ThotChicks</b> for <code>{html.escape(clean_query)}</code>.</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return

            total_pages = max(page + 1, 2) if len(results) == 10 else page
            total_count = page * 10 if len(results) == 10 else (page - 1) * 10 + len(results)
            card_text = format_clean_search_results_page(
                query=clean_query,
                scope_name="ThotChicks",
                page=page,
                total_pages=total_pages,
                total_count=total_count,
                items=results,
                delivered_indices=set(),
            )
            page_pfx = "sp_fp:tc:all"
            markup = build_search_results_clean_keyboard(
                page=page,
                total_pages=total_pages,
                page_callback_prefix=page_pfx,
                back_callback=back_cb,
            )
            context.user_data["search_query"] = clean_query
            context.user_data["active_search_results"] = {
                "plat": "tc",
                "query": clean_query,
                "scope_name": "ThotChicks",
                "forum_id": None,
                "page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "items": results,
                "delivered_indices": set(),
                "chat_id": status_msg.chat_id,
                "message_id": status_msg.message_id,
                "back_callback": back_cb,
            }
            await status_msg.edit_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)

    elif plat in ("desi", "mmsdesi"):
        try:
            results = await asyncio.to_thread(_get_target_func("search_mmsdesi", search_mmsdesi), clean_query, page, 10)
        except Exception as e:
            await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
            return

        back_cb = "sp_choose:desi"
        if not results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"<blockquote>❌ No videos found on <b>MMSDesi</b> for <code>{html.escape(clean_query)}</code>.</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        total_pages = max(page + 1, 2) if len(results) == 10 else page
        total_count = page * 10 if len(results) == 10 else (page - 1) * 10 + len(results)

        card_text = format_clean_search_results_page(
            query=clean_query,
            scope_name="MMSDesi",
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=results,
            delivered_indices=set(),
        )

        page_pfx = "sp_fp:desi:all"
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=page_pfx,
            back_callback=back_cb,
        )

        context.user_data["active_search_results"] = {
            "plat": "desi",
            "query": clean_query,
            "scope_name": "MMSDesi",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": results,
            "delivered_indices": set(),
            "chat_id": status_msg.chat_id,
            "message_id": status_msg.message_id,
            "back_callback": back_cb,
        }

        await status_msg.edit_text(
            card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    elif plat in ("all", "global"):
        try:
            all_results = await execute_global_search(clean_query, page=page, limit_per_engine=6)
        except Exception as e:
            await status_msg.edit_text(f"❌ Global Search error: {html.escape(str(e))}")
            return

        back_cb = "cb_search"
        if not all_results:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=back_cb), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"<blockquote>❌ No matching items found across all platforms for <code>{html.escape(clean_query)}</code>.</blockquote>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        total_pages = max(page + 1, 2) if len(all_results) >= 6 else page
        total_count = (page - 1) * 10 + len(all_results) + (10 if len(all_results) >= 6 else 0)
        paged_results = all_results[:10]

        card_text = format_clean_search_results_page(
            query=clean_query,
            scope_name="All Sites (Global Search)",
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=paged_results,
            delivered_indices=set(),
        )

        page_pfx = "sp_fp:all:all"
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=page_pfx,
            back_callback=back_cb,
        )

        context.user_data["search_query"] = clean_query
        context.user_data["active_search_results"] = {
            "plat": "all",
            "query": clean_query,
            "scope_name": "All Sites (Global Search)",
            "forum_id": None,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": paged_results,
            "all_items": all_results,
            "delivered_indices": set(),
            "chat_id": status_msg.chat_id,
            "message_id": status_msg.message_id,
            "back_callback": back_cb,
            "page_callback_prefix": page_pfx,
        }

        await status_msg.edit_text(
            card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    else:
        # Forum search (DropMMS or MMSTown) with clean text numbers, 10 items per page, and date sorting
        base_search_url = "https://mmstown.com" if plat == "mmst" else BASE_URL
        scope = scope_name or plat_label
        try:
            search_res = await asyncio.to_thread(
                search_forum_advanced,
                clean_query,
                page,
                10,
                "titles",
                "newest",
                base_search_url,
                forum_id,
            )
            results = search_res.get("topics", [])
            total_count = search_res.get("total_count", len(results))
            total_pages = search_res.get("total_pages", 1)
        except Exception as e:
            await status_msg.edit_text(f"❌ Search error: {html.escape(str(e))}")
            return

        if not results:
            back_cb = back_callback or (f"sp_cat:{context.user_data.get('last_short_id')}" if forum_id else f"sp_choose:{plat}")
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔄 Search {display_scope} Again", callback_data=back_cb)],
                [InlineKeyboardButton("🔙 Back to Search", callback_data="cb_search")],
                [InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
            ])
            context.user_data["search_query"] = clean_query
            await status_msg.edit_text(
                f"❌ No topics found on {html.escape(display_scope)} for <b>{html.escape(clean_query)}</b>.\n\n"
                "<i>Tip: Check spelling or try a broader keyword.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return

        # Render clean text-based search results with numbers 1 to 10
        card_text = format_clean_search_results_page(
            query=clean_query,
            scope_name=display_scope,
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            items=results,
            delivered_indices=set(),
        )

        fid_str = str(forum_id) if forum_id else "all"
        page_pfx = f"sp_fp:{plat}:{fid_str}"
        back_cb = back_callback or (f"sp_choose:{plat}" if not forum_id else f"sp_cat:{context.user_data.get('last_short_id', '')}")
        markup = build_search_results_clean_keyboard(
            page=page,
            total_pages=total_pages,
            page_callback_prefix=page_pfx,
            back_callback=back_cb,
        )

        context.user_data["active_search_results"] = {
            "plat": plat,
            "query": clean_query,
            "scope_name": display_scope,
            "forum_id": forum_id,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "items": results,
            "delivered_indices": set(),
            "chat_id": status_msg.chat_id,
            "message_id": status_msg.message_id,
            "back_callback": back_cb,
        }

        await status_msg.edit_text(
            card_text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
