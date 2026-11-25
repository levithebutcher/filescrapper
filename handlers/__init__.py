# handlers/__init__.py
"""
FileScrapper Bot Modular Handlers Package.
Provides centralized access to commands, session state, search workflows,
global federated search, and callback routers.
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
    # Search Workflows
    "execute_platform_search",
    # Global Federated Search
    "normalize_title",
    "parse_duration_seconds",
    "is_duplicate_video",
    "deduplicate_and_merge_results",
    "execute_global_search",
]
