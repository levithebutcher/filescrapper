# handlers/feed.py
"""
Broadcast channels, auto-feed scheduler, and feed/digest commands (/today, /latest, /domains, /setchannel, /channels).
"""

import html
import logging
import asyncio
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus, ChatType
from telegram.ext import ContextTypes, Application

import db
from config import (
    BOT_NAME,
    DEFAULT_CATEGORY_URL,
    STREAMING_DOMAINS,
    POST_SEND_DELAY,
    FEED_CHECK_INTERVAL,
)
from handlers.session import (
    start_scrape_for_chat,
    end_scrape_for_chat,
    is_scrape_cancelled,
    cancellable_sleep,
)
from handlers.delivery import send_post_card, send_livecam_card
from handlers.scrapers import process_livecam_scrape, process_topic_scrape

from keyboards import (
    build_stop_keyboard,
    get_navigation_keyboard,
)
from scraper import (
    parse_slicing_args,
    apply_slice,
    get_forum_topics,
    get_post_details,
    is_livecam_url,
    is_livecam_video_url,
    get_livecam_video_details,
    get_livecam_model_videos,
    is_topic_url,
    get_host_display_name,
)

logger = logging.getLogger(__name__)


def _get_target_func(name: str, fallback):
    """Retrieve function from bot module if patched in tests, else fallback."""
    bot_mod = sys.modules.get("bot")
    if bot_mod and hasattr(bot_mod, name):
        return getattr(bot_mod, name)
    return fallback


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fetch and deliver today's fresh uploads.
    Supports DropMMS forum categories and LiveCam model pages.
    """
    msg = update.effective_message
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = msg.chat_id

    logger.info(f"📅 [/today] Chat {chat_id} (User: {user_id}) - context.args={context.args}")
    start_scrape_for_chat(chat_id)

    target_url, start_idx, end_idx, is_last_n = parse_slicing_args(context.args or [])
    if not target_url:
        target_url = DEFAULT_CATEGORY_URL
    elif not target_url.startswith("http://") and not target_url.startswith("https://"):
        target_url = f"https://{target_url}"

    has_slice = (start_idx is not None) or (end_idx is not None) or is_last_n
    logger.info(f"🎯 [/today] Target URL: {target_url} | Slice: start={start_idx}, end={end_idx}, is_last_n={is_last_n}")

    status_msg = await msg.reply_text("📅 <i>Scanning today's uploads...</i>", parse_mode=ParseMode.HTML)

    # 1. LiveCam URL Handling
    if is_livecam_url(target_url):
        if is_livecam_video_url(target_url):
            await status_msg.edit_text("🔍 <i>Extracting LiveCam video streaming link...</i>", parse_mode=ParseMode.HTML)
            try:
                target_v_fn = _get_target_func("get_livecam_video_details", get_livecam_video_details)
                details = await asyncio.to_thread(target_v_fn, target_url)
                target_livecam_card = _get_target_func("send_livecam_card", send_livecam_card)
                await target_livecam_card(context.bot, chat_id, details, user_id=user_id)
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

        # Model page URL
        only_today = not has_slice
        try:
            target_mvids = _get_target_func("get_livecam_model_videos", get_livecam_model_videos)
            videos = await asyncio.to_thread(target_mvids, target_url, only_today, 50)
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

        target_proc_livecam = _get_target_func("process_livecam_scrape", process_livecam_scrape)
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
                await target_proc_livecam(context.bot, chat_id, v, user_id=user_id)
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
        target_proc_topic = _get_target_func("process_topic_scrape", process_topic_scrape)
        try:
            await target_proc_topic(context.bot, chat_id, target_url, user_id=user_id)
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
        target_topics_fn = _get_target_func("get_forum_topics", get_forum_topics)
        all_today_topics = await asyncio.to_thread(target_topics_fn, target_url, "start_date", 200, True)
    except Exception as e:
        logger.error(f"Error fetching forum category: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error fetching category: {html.escape(str(e))}")
        end_scrape_for_chat(chat_id)
        return

    topics = apply_slice(all_today_topics, start_idx, end_idx, is_last_n)

    if not topics and has_slice:
        logger.info(f"No today posts found for slice in {target_url}. Fetching recent posts.")
        await status_msg.edit_text("📅 <i>No posts uploaded today. Fetching recent uploads...</i>", parse_mode=ParseMode.HTML)
        try:
            target_topics_fn = _get_target_func("get_forum_topics", get_forum_topics)
            recent_topics = await asyncio.to_thread(target_topics_fn, target_url, "start_date", 50, False)
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

    target_proc_topic = _get_target_func("process_topic_scrape", process_topic_scrape)
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
            await target_proc_topic(context.bot, chat_id, t["url"], user_id=user_id)
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
        target_topics_fn = _get_target_func("get_forum_topics", get_forum_topics)
        topics = await asyncio.to_thread(target_topics_fn, category_url, "start_date", 6)
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


async def domains_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List supported streaming providers."""
    badges = [get_host_display_name(f"https://{d}/") for d in STREAMING_DOMAINS]
    text = (
        f"🌐 <b>Supported Streaming Providers ({len(STREAMING_DOMAINS)}):</b>\n\n"
        + "\n".join([f"• {b}" for b in badges])
        + "\n\n<i>Direct video links from these providers are automatically captured.</i>"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


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
                f"📢 <b>Channel:</b> {html.escape(chat.title or 'Connected Channel')}\n"
                f"🎯 <b>Monitoring:</b> <code>{html.escape(target_category)}</code>\n"
                "⏱️ <b>Auto-Feed:</b> Active (New drops will post here automatically)",
                parse_mode=ParseMode.HTML,
            )
        return

    # Case B: Command run in private chat
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
            f"✅ <b>Linked to Channel:</b> {html.escape(chat_info.title or str(chat_info.id))}\n"
            f"🎯 <b>Category:</b> <code>{html.escape(custom_cat)}</code>\n"
            "🚀 Auto-feed activated!",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await msg.reply_text(f"❌ Failed to connect channel: {html.escape(str(e))}\nMake sure the bot is an Admin in the channel!")


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

    if new_member.status in [ChatMemberStatus.ADMINISTRATOR]:
        db.add_or_update_channel(
            channel_id=chat.id,
            title=chat.title or "Auto Channel",
            username=chat.username,
            category_url=DEFAULT_CATEGORY_URL,
            added_by=result.from_user.id if result.from_user else None,
        )
        logger.info(f"✅ Auto-linked channel: {chat.title} ({chat.id})")

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

    elif new_member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED]:
        db.remove_channel(chat.id)
        logger.info(f"Channel unlinked (bot removed): {chat.title} ({chat.id})")


async def auto_feed_loop(app: Application):
    """
    Background worker: monitors linked channels' categories and broadcasts new drops.
    Runs continuously without requiring external scheduler libraries.
    """
    logger.info("🚀 Background Auto-Feed Engine started.")
    await asyncio.sleep(10)

    while True:
        try:
            channels = db.get_all_active_channels()
            if channels:
                for channel in channels:
                    channel_id = channel["channel_id"]
                    cat_url = channel.get("category_url") or DEFAULT_CATEGORY_URL

                    try:
                        target_topics_fn = _get_target_func("get_forum_topics", get_forum_topics)
                        topics = await asyncio.to_thread(target_topics_fn, cat_url, "start_date", 10)
                        for t in reversed(topics):
                            t_url = t["url"]
                            if not db.is_post_seen(t_url):
                                target_details_fn = _get_target_func("get_post_details", get_post_details)
                                details = await asyncio.to_thread(target_details_fn, t_url)
                                target_send_card = _get_target_func("send_post_card", send_post_card)
                                await target_send_card(app.bot, channel_id, details)
                                db.mark_post_seen(t_url, details.get("title", ""))
                                await asyncio.sleep(POST_SEND_DELAY)
                    except Exception as err:
                        logger.warning(f"Auto-feed error for channel {channel_id}: {err}")

        except Exception as e:
            logger.error(f"Unexpected error in auto_feed_loop: {e}")

        await asyncio.sleep(FEED_CHECK_INTERVAL)


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
    bot_mod = sys.modules.get("bot")
    target_raw_fn = getattr(bot_mod, "handle_raw_url", None)
    if not target_raw_fn:
        from handlers.raw_url import handle_raw_url
        target_raw_fn = handle_raw_url
    await target_raw_fn(update, context, raw_input)
