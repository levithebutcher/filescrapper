# handlers/__init__.py
"""
FileScrapper Bot Modular Handlers Package.
Provides centralized access to commands, session state, search workflows,
global federated search, delivery, scrapers, feeds, raw URLs, and callback routers.
"""

from handlers.session import (
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
)

from handlers.commands import (
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
)

from handlers.global_search import (
    normalize_title,
    parse_duration_seconds,
    is_duplicate_video,
    deduplicate_and_merge_results,
    execute_global_search,
)

from handlers.search_flow import execute_platform_search

from handlers.delivery import (
    send_post_card,
    send_livecam_card,
    send_resurfaced_active_listing,
)

from handlers.scrapers import (
    process_livecam_scrape,
    run_livecam_model_scrape,
    run_forum_category_scrape,
    run_mmsvibex_listing_scrape,
    run_wp_listing_scrape,
    process_topic_scrape,
)

from handlers.feed import (
    today_command,
    latest_command,
    domains_command,
    setchannel_command,
    chat_member_updated,
    auto_feed_loop,
    scrape_command,
)

from handlers.raw_url import handle_raw_url
from handlers.messages_handler import handle_message
from handlers.callbacks import callback_query_handler

__all__ = [
    # Session & Config
    "get_search_mode",
    "set_search_mode",
    "ACTIVE_SEARCH_MODE",
    "start_scrape_for_chat",
    "end_scrape_for_chat",
    "cancel_scrape_for_chat",
    "is_scrape_cancelled",
    "is_chat_busy",
    "cancellable_sleep",
    "cancelled_chats",
    "active_scrapes",
    # Commands
    "start_command",
    "help_command",
    "stop_command",
    "cancel_command",
    "search_command",
    "searchmode_command",
    "mode_command",
    "sethost_command",
    "setlink_command",
    "channels_command",
    "cleanup_ephemeral_progress",
    # Feed & Broadcast Commands
    "today_command",
    "latest_command",
    "domains_command",
    "setchannel_command",
    "chat_member_updated",
    "auto_feed_loop",
    "scrape_command",
    # Delivery Engine
    "send_post_card",
    "send_livecam_card",
    "send_resurfaced_active_listing",
    # Scraper Runners
    "process_livecam_scrape",
    "run_livecam_model_scrape",
    "run_forum_category_scrape",
    "run_mmsvibex_listing_scrape",
    "run_wp_listing_scrape",
    "process_topic_scrape",
    # Search Workflows
    "execute_platform_search",
    # Global Federated Search
    "normalize_title",
    "parse_duration_seconds",
    "is_duplicate_video",
    "deduplicate_and_merge_results",
    "execute_global_search",
    # Message & URL Routing
    "handle_raw_url",
    "handle_message",
    "callback_query_handler",
]
