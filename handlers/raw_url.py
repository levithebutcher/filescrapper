# handlers/raw_url.py
"""
Handler for raw URLs pasted directly in chat or passed via /scrape.
Routes to single video extracts, photo albums, model profiles, category listings, or universal scraper.
"""

import re
import html
import logging
import asyncio
from urllib.parse import urlparse
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db
import messages
from handlers.session import start_scrape_for_chat, end_scrape_for_chat
from handlers.delivery import send_post_card, send_livecam_card
from handlers.scrapers import (
    run_mmsvibex_listing_scrape,
    run_wp_listing_scrape,
    run_livecam_model_scrape,
    run_forum_category_scrape,
    process_topic_scrape,
)

from ui import format_listing_menu_card
from keyboards import (
    build_mmsvibex_mode_keyboard,
    build_mmsvibex_options_keyboard,
    build_back_cancel_keyboard,
    build_mmsmaza_hub_keyboard,
    build_leakedzone_hub_keyboard,
    build_xvideo_hub_keyboard,
    build_hornysapiens_hub_keyboard,
    build_thotchicks_hub_keyboard,
    build_mmsdesi_hub_keyboard,
    build_model_sort_keyboard,
    build_forum_sort_keyboard,
)

from scraper import (
    parse_slicing_args,
    clean_livecam_title,
    get_livecam_model_stats,
    get_dropmms_category_stats,
    get_universal_post_details,
    is_mmsvibex_photo_url,
    get_mmsvibex_photo_details,
    is_mmsvibex_video_url,
    get_mmsvibex_video_details,
    is_mmsvibex_listing_url,
    is_wp_locker_post_url,
    get_wp_post_details,
    is_wp_locker_listing_url,
    is_leakedzone_video_url,
    get_leakedzone_video_details,
    is_leakedzone_model_url,
    is_kvs_video_url,
    get_kvs_video_details,
    is_kvs_listing_url,
    is_thotchicks_video_url,
    get_thotchicks_video_details,
    is_thotchicks_actor_url,
    is_mmsdesi_video_url,
    get_mmsdesi_video_details,
    is_mmsdesi_listing_url,
    is_livecam_video_url,
    get_livecam_video_details,
    is_livecam_model_url,
    is_topic_url,
    is_forum_url,
)

logger = logging.getLogger(__name__)


def _get_target_func(name: str, fallback):
    """Retrieve function from bot module if patched in tests, else fallback."""
    bot_mod = sys.modules.get("bot")
    if bot_mod and hasattr(bot_mod, name):
        return getattr(bot_mod, name)
    return fallback


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
                "mmsmaza.im",
                "livecamrips.to",
                "leakedzone.com",
                "x-video.tube",
                "hornysapiens.com",
                "viralxxxporn.com",
                "thotchicks.com",
                "mmsdesi.me",
            ]
        ):
            target_url = f"https://{target_url}"
        else:
            return

    logger.info(f"🔗 [handle_raw_url] Chat {chat_id} (User: {user_id}) - Target URL: {target_url} | Slice: start={start_idx}, end={end_idx}, is_last_n={is_last_n}")
    start_scrape_for_chat(chat_id)

    target_send_card = _get_target_func("send_post_card", send_post_card)
    target_livecam_card = _get_target_func("send_livecam_card", send_livecam_card)

    # 1. MMSVibex Photo Album
    if is_mmsvibex_photo_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting MMSVibex photo album & ZIP download...</i>", parse_mode=ParseMode.HTML)
        try:
            target_p_fn = _get_target_func("get_mmsvibex_photo_details", get_mmsvibex_photo_details)
            details = await asyncio.to_thread(target_p_fn, target_url)
            await target_send_card(context.bot, chat_id, details, user_id=user_id)
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
            target_v_fn = _get_target_func("get_mmsvibex_video_details", get_mmsvibex_video_details)
            details = await asyncio.to_thread(target_v_fn, target_url)
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
                await target_send_card(context.bot, chat_id, details, user_id=user_id)
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
        target_listing_scrape = _get_target_func("run_mmsvibex_listing_scrape", run_mmsvibex_listing_scrape)
        if start_idx is not None or end_idx is not None or is_last_n:
            await target_listing_scrape(
                bot=context.bot,
                chat_id=chat_id,
                target_url=target_url,
                start_idx=start_idx,
                end_idx=end_idx,
                is_last_n=is_last_n,
                user_id=user_id,
                context=context,
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
        markup = build_mmsvibex_options_keyboard(sort_key="custom", back_callback="sp_choose:vibex")
        card_text = (
            "<blockquote>"
            f"⚡ <b>{html.escape(title)}</b>\n\n"
            "Reply in chat with a custom range, count or page:\n"
            "• <code>5</code> ➔ First 5 items\n"
            "• <code>1-15</code> ➔ Items 1 to 15\n"
            "• <code>page 2</code> ➔ Full Page 2"
            "</blockquote>"
        )
        s_msg = await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["awaiting_vibex_range"]["message_id"] = s_msg.message_id
        return

    # 4. WordPress Locker Post (Omaal63, DesiJugar, GulabiHub, MMSMaza)
    if is_wp_locker_post_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting streaming links...</i>", parse_mode=ParseMode.HTML)
        try:
            target_wp_post = _get_target_func("get_wp_post_details", get_wp_post_details)
            details = await asyncio.to_thread(target_wp_post, target_url)
            site_k = details.get("site", "wp")
            back_cb = f"sp_wpsite:{site_k}" if site_k in ("mmsmaza", "omaal", "desijugar", "gulabi") else "cb_search"
            await target_send_card(
                context.bot,
                chat_id,
                details,
                user_id=user_id,
                reply_markup=build_back_cancel_keyboard(back_callback=back_cb, cancel_callback="sp_cancel"),
            )
        except Exception as e:
            await status.edit_text(f"❌ Error extracting post: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 4b. MMSMaza Home / General Hub
    if target_url.rstrip("/") in ("https://mmsmaza.im", "http://mmsmaza.im"):
        end_scrape_for_chat(chat_id)
        markup = build_mmsmaza_hub_keyboard(back_callback="cb_search")
        await msg.reply_text(
            "<blockquote>📂 <b>MMSMaza Hub</b>\nSelect search or browse releases:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    # 5. WordPress Locker Listing / Archive (Omaal63, DesiJugar, GulabiHub)
    if is_wp_locker_listing_url(target_url):
        end_scrape_for_chat(chat_id)
        target_wp_listing = _get_target_func("run_wp_listing_scrape", run_wp_listing_scrape)
        if start_idx is not None or end_idx is not None or is_last_n:
            await target_wp_listing(
                bot=context.bot,
                chat_id=chat_id,
                target_url=target_url,
                start_idx=start_idx,
                end_idx=end_idx,
                is_last_n=is_last_n,
                user_id=user_id,
                context=context,
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
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="cb_main_menu"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")]
        ])
        card_text = format_listing_menu_card(title, is_category=True)
        s_msg = await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["awaiting_wp_range"]["message_id"] = s_msg.message_id
        return

    # 6. LeakedZone Single Video
    if is_leakedzone_video_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting LeakedZone video & direct stream...</i>", parse_mode=ParseMode.HTML)
        try:
            target_lz_fn = _get_target_func("get_leakedzone_video_details", get_leakedzone_video_details)
            details = await asyncio.to_thread(target_lz_fn, target_url)
            await target_send_card(context.bot, chat_id, details, user_id=user_id, reply_markup=build_back_cancel_keyboard(back_callback="sp_choose:lz", cancel_callback="sp_cancel"))
        except Exception as e:
            await status.edit_text(f"❌ Error extracting LeakedZone video: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 7. LeakedZone Model Page
    if is_leakedzone_model_url(target_url):
        end_scrape_for_chat(chat_id)
        model_slug = target_url.rstrip("/").split("/")[-1]
        markup = build_leakedzone_hub_keyboard(model_slug=model_slug, back_callback="cb_search")
        await msg.reply_text(
            f"<blockquote>🔓 <b>LeakedZone: {html.escape(model_slug.title())}</b>\nSelect search or sorting:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    # 8. KVS Video (X-Video, HornySapiens, ViralXXXPorn)
    if is_kvs_video_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting video & direct stream...</i>", parse_mode=ParseMode.HTML)
        try:
            target_kvs_v = _get_target_func("get_kvs_video_details", get_kvs_video_details)
            details = await asyncio.to_thread(target_kvs_v, target_url)
            site_k = details.get("site", "kvs")
            back_cb = "sp_choose:xvid" if "xvideo" in site_k else "sp_choose:hs"
            await target_send_card(context.bot, chat_id, details, user_id=user_id, reply_markup=build_back_cancel_keyboard(back_callback=back_cb, cancel_callback="sp_cancel"))
        except Exception as e:
            await status.edit_text(f"❌ Error extracting video: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 9. KVS Listing (X-Video, HornySapiens, ViralXXXPorn)
    if is_kvs_listing_url(target_url):
        end_scrape_for_chat(chat_id)
        slug = target_url.rstrip("/").split("/")[-1]
        if "x-video.tube" in target_url.lower():
            markup = build_xvideo_hub_keyboard(tag_or_slug=slug, back_callback="cb_search")
            card_title = "X-Video Tube"
        else:
            markup = build_hornysapiens_hub_keyboard(model_slug=slug, back_callback="cb_search")
            card_title = "HornySapiens"
        await msg.reply_text(
            f"<blockquote>📺 <b>{card_title}: {html.escape(slug.title())}</b>\nSelect search or sorting:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    # 10. ThotChicks Video
    if is_thotchicks_video_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting ThotChicks video & stream...</i>", parse_mode=ParseMode.HTML)
        try:
            target_tc_v = _get_target_func("get_thotchicks_video_details", get_thotchicks_video_details)
            details = await asyncio.to_thread(target_tc_v, target_url)
            await target_send_card(context.bot, chat_id, details, user_id=user_id, reply_markup=build_back_cancel_keyboard(back_callback="sp_choose:tc", cancel_callback="sp_cancel"))
        except Exception as e:
            await status.edit_text(f"❌ Error extracting ThotChicks video: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 11. ThotChicks Actor Page
    if is_thotchicks_actor_url(target_url):
        end_scrape_for_chat(chat_id)
        slug = target_url.rstrip("/").split("/")[-1]
        markup = build_thotchicks_hub_keyboard(actor_slug=slug, back_callback="cb_search")
        await msg.reply_text(
            f"<blockquote>💃 <b>ThotChicks: {html.escape(slug.title())}</b>\nSelect search or sorting:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    # 12. MMSDesi Video
    if is_mmsdesi_video_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting MMSDesi video & photo album...</i>", parse_mode=ParseMode.HTML)
        try:
            target_desi_v = _get_target_func("get_mmsdesi_video_details", get_mmsdesi_video_details)
            details = await asyncio.to_thread(target_desi_v, target_url)
            await target_send_card(context.bot, chat_id, details, user_id=user_id, reply_markup=build_back_cancel_keyboard(back_callback="sp_choose:desi", cancel_callback="sp_cancel"))
        except Exception as e:
            await status.edit_text(f"❌ Error extracting MMSDesi video: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 13. MMSDesi Listing
    if is_mmsdesi_listing_url(target_url):
        end_scrape_for_chat(chat_id)
        markup = build_mmsdesi_hub_keyboard(back_callback="cb_search")
        await msg.reply_text(
            "<blockquote>📹 <b>MMSDesi Hub</b>\nSelect search or browse categories:</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    # 14. LiveCam Single Video
    if is_livecam_video_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting LiveCam video streaming link...</i>", parse_mode=ParseMode.HTML)
        try:
            target_live_v = _get_target_func("get_livecam_video_details", get_livecam_video_details)
            details = await asyncio.to_thread(target_live_v, target_url)
            await target_livecam_card(context.bot, chat_id, details, user_id=user_id)
        except Exception as e:
            await status.edit_text(f"❌ Error extracting LiveCam video: {html.escape(str(e))}")
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 15. LiveCam Model Page
    if is_livecam_model_url(target_url):
        target_live_model_scrape = _get_target_func("run_livecam_model_scrape", run_livecam_model_scrape)
        if start_idx is not None or end_idx is not None or is_last_n:
            end_scrape_for_chat(chat_id)
            await target_live_model_scrape(
                bot=context.bot,
                chat_id=chat_id,
                target_url=target_url,
                start_idx=start_idx or 1,
                end_idx=end_idx,
                req_limit=(end_idx if (start_idx is None and end_idx) else None),
                user_id=user_id,
                context=context,
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
        target_stats_fn = _get_target_func("get_livecam_model_stats", get_livecam_model_stats)
        stats = await asyncio.to_thread(target_stats_fn, clean_u)
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

    # 16. DropMMS Single Topic
    if is_topic_url(target_url):
        status = await msg.reply_text("🔍 <i>Extracting streaming links...</i>", parse_mode=ParseMode.HTML)
        try:
            target_proc_topic = _get_target_func("process_topic_scrape", process_topic_scrape)
            await target_proc_topic(context.bot, chat_id, target_url, user_id=user_id)
        finally:
            end_scrape_for_chat(chat_id)
        try:
            await status.delete()
        except Exception:
            pass
        return

    # 17. DropMMS Forum Category
    if is_forum_url(target_url):
        end_scrape_for_chat(chat_id)
        target_forum_scrape = _get_target_func("run_forum_category_scrape", run_forum_category_scrape)
        if start_idx is not None or end_idx is not None or is_last_n:
            await target_forum_scrape(
                bot=context.bot,
                chat_id=chat_id,
                target_url=target_url,
                start_idx=start_idx,
                end_idx=end_idx,
                is_last_n=is_last_n,
                user_id=user_id,
                context=context,
            )
            return

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
        target_cat_stats = _get_target_func("get_dropmms_category_stats", get_dropmms_category_stats)
        stats = await asyncio.to_thread(target_cat_stats, clean_u)
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

    # 18. Universal Fallback for any other valid HTTP/HTTPS URL
    if target_url.startswith("http://") or target_url.startswith("https://"):
        status = await msg.reply_text("🌐 <i>Analyzing webpage with Universal Scraper...</i>", parse_mode=ParseMode.HTML)
        try:
            target_univ_fn = _get_target_func("get_universal_post_details", get_universal_post_details)
            details = await asyncio.to_thread(target_univ_fn, target_url)
            if details.get("streaming_links"):
                await target_send_card(context.bot, chat_id, details, user_id=user_id)
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
