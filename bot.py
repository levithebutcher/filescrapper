# bot.py
"""
FileScrapper Bot v2.0.0
Universal Telegram Streaming & Scraper Orchestrator.
Modularized architecture: Handlers, Scrapers, Delivery, Keyboards, UI, and DB.
"""

import sys
import logging
import asyncio

from telegram import (
    Update,
    BotCommand,
    MenuButtonCommands,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Conflict
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
    BOT_TOKEN,
)

# --- Re-export all handlers for seamless modular routing & 100% test compatibility ---
from handlers import (
    get_search_mode,
    set_search_mode,
    ACTIVE_SEARCH_MODE,
    start_scrape_for_chat,
    end_scrape_for_chat,
    cancel_scrape_for_chat,
    is_scrape_cancelled,
    is_chat_busy,
    cancellable_sleep,
    cancelled_chats,
    active_scrapes,
    start_command,
    help_command,
    stop_command,
    cancel_command,
    search_command,
    searchmode_command,
    mode_command,
    sethost_command,
    setlink_command,
    channels_command,
    cleanup_ephemeral_progress,
    today_command,
    latest_command,
    domains_command,
    setchannel_command,
    chat_member_updated,
    auto_feed_loop,
    scrape_command,
    send_post_card,
    send_livecam_card,
    send_resurfaced_active_listing,
    process_livecam_scrape,
    run_livecam_model_scrape,
    run_forum_category_scrape,
    run_mmsvibex_listing_scrape,
    run_wp_listing_scrape,
    process_topic_scrape,
    execute_platform_search,
    normalize_title,
    parse_duration_seconds,
    is_duplicate_video,
    deduplicate_and_merge_results,
    execute_global_search,
    handle_raw_url,
    handle_message,
    callback_query_handler,
)

# Re-export UI formatters imported directly by existing test suites
from ui import (
    format_post_card,
    group_links_by_host,
    format_search_results_page,
    format_clean_search_results_page,
    format_listing_menu_card,
    format_category_options_card,
    format_category_completion_card,
    format_search_completion_card,
    format_clean_category_posts_page,
    format_category_browse_completion_card,
    parse_search_selection,
)

# Re-export keyboard builders and controls imported directly by existing test suites
from keyboards import (
    build_card_keyboard,
    build_stop_keyboard,
    get_navigation_keyboard,
    get_host_settings_keyboard,
    get_link_mode_keyboard,
    build_main_menu_keyboard,
    build_search_platform_keyboard,
    build_search_execute_platform_keyboard,
    build_search_results_keyboard,
    build_search_results_clean_keyboard,
    build_mmsvibex_mode_keyboard,
    build_mmsvibex_hub_keyboard,
    build_mmsvibex_options_keyboard,
    build_models_keyboard,
    build_livecam_models_keyboard,
    build_slice_selection_keyboard,
    build_category_options_keyboard,
    build_forum_options_keyboard,
    build_forum_sort_keyboard,
    build_model_options_keyboard,
    build_model_sort_keyboard,
    build_wp_site_hub_keyboard,
    build_wp_categories_keyboard,
    build_leakedzone_hub_keyboard,
    build_xvideo_hub_keyboard,
    build_hornysapiens_hub_keyboard,
    build_thotchicks_hub_keyboard,
    build_mmsdesi_hub_keyboard,
    build_mmsmaza_hub_keyboard,
    build_channel_management_keyboard,
    build_back_cancel_row,
    build_back_cancel_keyboard,
    build_standard_hub_keyboard,
)

# Re-export scraper functions patched directly on `bot` by unit test suites
from scraper import (
    get_forum_topics,
    get_post_details,
    get_livecam_model_videos,
    get_livecam_video_details,
    get_livecam_model_stats,
    get_dropmms_forums,
    get_dropmms_category_stats,
    get_mmstown_forums,
    get_mmsvibex_video_details,
    get_mmsvibex_photo_details,
    get_mmsvibex_actor_videos,
    get_mmsvibex_listing_items,
    get_wp_post_details,
    get_wp_listing_posts,
    get_wp_categories,
    get_kvs_listing_items,
    get_kvs_video_details,
    get_leakedzone_video_details,
    get_leakedzone_model_videos,
    get_thotchicks_video_details,
    get_thotchicks_listing_items,
    get_mmsdesi_video_details,
    get_mmsdesi_category_videos,
    download_image_bytes,
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
        BotCommand("mode", "Search mode for sites 1-4 (model/video)"),
        BotCommand("stop", "Stop active category extraction"),
        BotCommand("help", "Help & instructions"),
    ]
    try:
        await application.bot.set_my_commands(commands)
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
    """Application factory and polling runner."""
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("❌ ERROR: BOT_TOKEN not configured in .env file!")
        sys.exit(1)

    # CLI search-mode configuration (--search-mode model|video)
    if "--search-mode" in sys.argv:
        try:
            sm_idx = sys.argv.index("--search-mode")
            if sm_idx + 1 < len(sys.argv):
                cli_mode = sys.argv[sm_idx + 1].lower().strip()
                if cli_mode in ("model", "video"):
                    set_search_mode(cli_mode)
                    print(f"⚙️ Search Mode configured via CLI: {cli_mode}")
        except Exception as e:
            logger.debug(f"CLI search mode note: {e}")

    print(f"🤖 Initializing {BOT_NAME} v{BOT_VERSION} (Search Mode: {get_search_mode()})...")
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("latest", latest_command))
    app.add_handler(CommandHandler("sethost", sethost_command))
    app.add_handler(CommandHandler("setlink", setlink_command))
    app.add_handler(CommandHandler("mode", searchmode_command))
    app.add_handler(CommandHandler("searchmode", searchmode_command))
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

    # Plain text links & messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Global Error Handler
    app.add_error_handler(error_handler)

    logger.info("✅ Bot initialized and listening for updates...")
    print("🚀 Bot is LIVE! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
