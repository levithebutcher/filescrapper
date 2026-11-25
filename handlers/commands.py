# handlers/commands.py
"""
Bot command handlers (/start, /help, /search, /mode, /stop, /cancel, /sethost, /setlink, /channels).
"""

import html
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import db
import messages
from config import BOT_NAME, OWNER_ID, DEFAULT_SEARCH_MODE
from handlers.session import (
    get_search_mode,
    set_search_mode,
    cancel_scrape_for_chat,
)
from keyboards import (
    build_main_menu_keyboard,
    build_search_platform_keyboard,
    build_search_execute_platform_keyboard,
    get_host_settings_keyboard,
    get_link_mode_keyboard,
    build_channel_management_keyboard,
)

logger = logging.getLogger(__name__)


async def cleanup_ephemeral_progress(context: ContextTypes.DEFAULT_TYPE, chat_id: int | str):
    """Clean up any ephemeral progress messages for the chat."""
    if not context:
        return
    key = f"active_progress_msg_{chat_id}"
    old_msg = context.user_data.pop(key, None)
    if old_msg:
        try:
            await old_msg.delete()
        except Exception:
            pass


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Minimal, elegant greeting."""
    if update.effective_chat:
        await cleanup_ephemeral_progress(context, update.effective_chat.id)
    user_name = update.effective_user.first_name if update.effective_user else "Friend"
    text = messages.get_welcome_message(user_name=user_name, bot_name=BOT_NAME)
    markup = build_main_menu_keyboard()
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clean usage guide."""
    if update.effective_chat:
        await cleanup_ephemeral_progress(context, update.effective_chat.id)
    await update.effective_message.reply_text(messages.get_help_message(), parse_mode=ParseMode.HTML)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Immediately stop any active topic, model, or category scraping in this chat."""
    chat = update.effective_chat
    chat_id = chat.id if chat else None
    if not chat_id:
        return

    await cleanup_ephemeral_progress(context, chat_id)
    logger.info(f"🛑 [/stop] Stop requested by user in chat {chat_id}")
    cancel_scrape_for_chat(chat_id)
    await update.effective_message.reply_text(
        "🛑 <b>Scraping stopped.</b>\n\n"
        "Active extraction has been cancelled. Remaining posts will not be sent.",
        parse_mode=ParseMode.HTML,
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for /stop to cancel active operations."""
    await stop_command(update, context)


async def sethost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configure preferred streaming host."""
    uid = update.effective_user.id if update.effective_user else 0
    if context.args:
        chosen = context.args[0].lower().strip()
        db.set_user_host_preference(uid, chosen)
        await update.effective_message.reply_text(
            f"✅ Preferred streaming host set to: <code>{html.escape(chosen)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_host_settings_keyboard(chosen),
        )
        return

    current = db.get_user_host_preference(uid) or "streamtape"
    text = (
        "<blockquote>"
        "⚙️ <b>Preferred Video Host Settings</b>\n\n"
        f"• <b>Current Selection:</b> <code>{html.escape(current)}</code>\n\n"
        "Choose which streaming provider should appear at the top of your post cards:"
        "</blockquote>"
    )
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_host_settings_keyboard(current),
    )


async def setlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configure LiveCam card link mode (streaming vs page vs both)."""
    uid = update.effective_user.id if update.effective_user else 0
    if context.args:
        chosen = context.args[0].lower().strip()
        if chosen in ("streaming", "both", "page"):
            db.set_user_link_mode(uid, chosen)
            await update.effective_message.reply_text(
                f"✅ LiveCam link format updated to: <code>{chosen}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_link_mode_keyboard(chosen),
            )
            return

    current = db.get_user_link_mode(uid) or "streaming"
    text = (
        "<blockquote>"
        "⚙️ <b>LiveCam Link Display Settings</b>\n\n"
        f"• <b>Current Format:</b> <code>{current}</code>\n\n"
        "Select the link display format for LiveCam video cards:"
        "</blockquote>"
    )
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_link_mode_keyboard(current),
    )


async def searchmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View or toggle search mode for sites 1-4 (model profile vs direct video)."""
    if context.args:
        chosen = context.args[0].lower().strip()
        if chosen in ("model", "models", "profile", "actor", "1"):
            set_search_mode("model", context=context)
        elif chosen in ("video", "videos", "direct", "2"):
            set_search_mode("video", context=context)

    current = get_search_mode(context=context)
    m_check = " ✅" if current == "model" else ""
    v_check = " ✅" if current == "video" else ""
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📹 Model Profile Search (Default){m_check}", callback_data="setmode_model")],
        [InlineKeyboardButton(f"🎬 Direct Video Search{v_check}", callback_data="setmode_video")],
        [InlineKeyboardButton("🔙 Back", callback_data="cb_search"), InlineKeyboardButton("❌ Cancel", callback_data="sp_cancel")],
    ])
    label = "Model Profile Search (Default)" if current == "model" else "Direct Video Search"
    text = (
        "<blockquote>"
        "⚙️ <b>Search Mode Settings (Websites 1-4)</b>\n\n"
        f"• <b>Current Active Mode:</b> <code>{label}</code>\n\n"
        "<b>1. Model Profile Search (Default):</b>\n"
        "Search model/actor name ➔ Profile card with sorting (Newest, Most Viewed, Longest) ➔ Videos.\n\n"
        "<b>2. Direct Video Search:</b>\n"
        "Search video keyword ➔ Directly displays matching videos list immediately.\n\n"
        "<i>Select below or launch via <code>python bot.py --search-mode model|video</code>:</i>"
        "</blockquote>"
    )
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for /searchmode."""
    await searchmode_command(update, context)


async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View and manage auto-feed target channels."""
    uid = update.effective_user.id if update.effective_user else 0
    if OWNER_ID and uid != OWNER_ID:
        await update.effective_message.reply_text("⛔ This command is restricted to the bot owner.")
        return

    channels = db.get_active_feed_channels()
    if not channels:
        text = "📢 <b>Channel Auto-Feed:</b> No active channels registered."
    else:
        text = "📢 <b>Active Auto-Feed Channels:</b>\n\n"
        for ch in channels:
            text += f"• <b>{html.escape(ch.get('title') or 'Channel')}</b> (<code>{ch['channel_id']}</code>)\n"

    markup = build_channel_management_keyboard()
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Interactive universal search engine with direct keyword prompt & platform tabs."""
    if update.effective_chat:
        cid = update.effective_chat.id
        await cleanup_ephemeral_progress(context, cid)
        context.user_data.pop("awaiting_vibex_range", None)
        context.user_data.pop("awaiting_model_range", None)
        context.user_data.pop("awaiting_category_range", None)
        context.user_data.pop("awaiting_wp_range", None)
        context.user_data.pop("active_search_results", None)
        context.user_data.pop("awaiting_search_flow", None)
        context.user_data.pop("awaiting_search", None)
        prev_card = context.user_data.pop("active_card_msg_id", None)
        if prev_card:
            try:
                await context.bot.delete_message(chat_id=cid, message_id=prev_card)
            except Exception:
                pass

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
                context.user_data["active_card_msg_id"] = update.callback_query.message.message_id
            except Exception:
                sent = await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
                context.user_data["active_card_msg_id"] = sent.message_id
        else:
            sent = await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
            context.user_data["active_card_msg_id"] = sent.message_id
        return

    context.user_data["search_query"] = query
    context.user_data["awaiting_search"] = None
    markup = build_search_execute_platform_keyboard()
    card_text = (
        "<blockquote>"
        f"🔍 <b>Universal Search:</b> <code>{html.escape(query)}</code>\n\n"
        "Choose an engine to search on or select <b>Search All Sites</b>:"
        "</blockquote>"
    )
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                card_text, parse_mode=ParseMode.HTML, reply_markup=markup
            )
            context.user_data["active_card_msg_id"] = update.callback_query.message.message_id
        except Exception:
            sent = await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
            context.user_data["active_card_msg_id"] = sent.message_id
    else:
        sent = await msg.reply_text(card_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        context.user_data["active_card_msg_id"] = sent.message_id
