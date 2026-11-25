# handlers/session.py
"""
Scrape session tracking, cancellation management, and search mode configuration.
"""

import asyncio
import logging
from config import DEFAULT_SEARCH_MODE

logger = logging.getLogger(__name__)

# Search Mode Configuration for Sites 1-4 (default: "model")
ACTIVE_SEARCH_MODE = DEFAULT_SEARCH_MODE if DEFAULT_SEARCH_MODE in ("model", "video") else "model"


def get_search_mode(context=None) -> str:
    """Get active search mode for sites 1-4: 'model' (LiveCam profile search) or 'video' (direct video keyword search)."""
    global ACTIVE_SEARCH_MODE
    if context and hasattr(context, "user_data") and isinstance(context.user_data, dict):
        u_mode = context.user_data.get("search_mode")
        if u_mode in ("model", "video"):
            return u_mode
    try:
        import db
        val = db.get_setting("search_mode")
        if val in ("model", "video"):
            ACTIVE_SEARCH_MODE = val
            return val
    except Exception:
        pass
    return ACTIVE_SEARCH_MODE


def set_search_mode(mode: str, context=None):
    """Set active search mode for sites 1-4 and persist across bot restarts."""
    global ACTIVE_SEARCH_MODE
    if mode in ("model", "video"):
        ACTIVE_SEARCH_MODE = mode
        if context and hasattr(context, "user_data") and isinstance(context.user_data, dict):
            context.user_data["search_mode"] = mode
        try:
            import db
            db.set_setting("search_mode", mode)
        except Exception:
            pass


# Active scrape tracking & cancellation flags
cancelled_chats: set[int] = set()
active_scrapes: dict[int, bool] = {}


def cancel_scrape_for_chat(chat_id: int | str):
    """Mark active scraping as cancelled for the given chat."""
    try:
        cid = int(chat_id)
        cancelled_chats.add(cid)
        active_scrapes[cid] = False
        logger.info(f"🛑 [CANCELLATION] Cancel flag registered for chat {cid}")
    except Exception as e:
        logger.error(f"Error setting cancel flag for {chat_id}: {e}")


def is_scrape_cancelled(chat_id: int | str) -> bool:
    """Check if cancellation has been requested for this chat."""
    try:
        return int(chat_id) in cancelled_chats
    except Exception:
        return False


def start_scrape_for_chat(chat_id: int | str):
    """Register a scrape run for this chat."""
    try:
        cid = int(chat_id)
        cancelled_chats.discard(cid)
        active_scrapes[cid] = True
        logger.info(f"🚀 [SCRAPE_START] Registered new active scrape for chat {cid}")
    except Exception as e:
        logger.error(f"Error starting scrape for {chat_id}: {e}")


def end_scrape_for_chat(chat_id: int | str):
    """Clean up scrape state when finished or aborted."""
    try:
        cid = int(chat_id)
        cancelled_chats.discard(cid)
        active_scrapes[cid] = False
        logger.info(f"🏁 [SCRAPE_END] Cleaned up scrape state for chat {cid}")
    except Exception as e:
        logger.error(f"Error ending scrape for {chat_id}: {e}")


def is_chat_busy(chat_id: int | str) -> bool:
    """Check if an active scrape is currently running for this chat."""
    try:
        return bool(active_scrapes.get(int(chat_id), False))
    except Exception:
        return False


async def cancellable_sleep(duration: float, chat_id: int | str, step: float = 0.2):
    """Sleep for duration seconds while checking for cancellation every step seconds."""
    elapsed = 0.0
    while elapsed < duration:
        if is_scrape_cancelled(chat_id):
            return
        sleep_time = min(step, duration - elapsed)
        await asyncio.sleep(sleep_time)
        elapsed += sleep_time
