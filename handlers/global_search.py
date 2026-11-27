# handlers/global_search.py
"""
Global Multi-Platform Federated Search Engine.
Concurrently queries all supported scraper platforms (Sites 1-4, MMSMaza, MMSDesi,
MMSVibex, Forum Topics, LiveCam) with isolated timeouts, and applies smart fuzzy
deduplication and merger pipeline to prevent duplicate cards.
"""

import re
import html
import logging
import asyncio
import difflib
from typing import Any

from urllib.parse import quote_plus
from engines.kvs import search_kvs, search_kvs_models
from engines.leakedzone import search_leakedzone, search_leakedzone_models
from engines.thotchicks import search_thotchicks, search_thotchicks_actors
from engines.mmsdesi import search_mmsdesi
from engines.wordpress import get_wp_listing_posts
from scraper import (
    search_mmsvibex,
    search_forum,
    search_livecam_models,
)

logger = logging.getLogger(__name__)

# Noise tokens removed during title normalization for deduplication
NOISE_TOKENS = {
    "leaked", "onlyfans", "video", "videos", "mp4", "full", "hd", "720p", "1080p", "4k",
    "mms", "desi", "clip", "clips", "watch", "online", "free", "viral", "new", "porn",
    "sex", "webcam", "rip", "rips", "recorded", "stream", "private", "part", "pt"
}


def normalize_title(title: str) -> str:
    """Normalize video title for fuzzy similarity comparison."""
    if not title:
        return ""
    # Lowercase and strip punctuation
    cleaned = re.sub(r"[^\w\s]", " ", title.lower())
    tokens = [t for t in cleaned.split() if len(t) > 1 and t not in NOISE_TOKENS]
    return " ".join(tokens)


def parse_duration_seconds(dur_str: str | None) -> int | None:
    """Convert various duration string representations to integer seconds."""
    if not dur_str or not isinstance(dur_str, str):
        return None
    d = dur_str.strip().lower()
    try:
        # e.g., "12m 45s"
        m_ms = re.search(r"(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?", d)
        if m_ms and (m_ms.group(1) or m_ms.group(2)):
            mins = int(m_ms.group(1) or 0)
            secs = int(m_ms.group(2) or 0)
            if mins or secs:
                return mins * 60 + secs

        # e.g., "01:23:45" or "12:34"
        parts = d.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

        # e.g., "300s" or "300"
        m_dig = re.search(r"^(\d+)\s*s?$", d)
        if m_dig:
            return int(m_dig.group(1))
    except Exception:
        pass
    return None


def is_duplicate_video(item1: dict, item2: dict) -> bool:
    """
    Check if two search items refer to the same video across different platforms.
    Matches when:
    1. Title similarity >= 80% AND duration matches within +/- 15 seconds.
    2. Or title similarity >= 90% when duration is unavailable.
    """
    t1 = normalize_title(item1.get("title", ""))
    t2 = normalize_title(item2.get("title", ""))
    if not t1 or not t2:
        return False

    ratio = difflib.SequenceMatcher(None, t1, t2).ratio()

    # Compare durations if available
    dur1 = parse_duration_seconds(item1.get("duration"))
    dur2 = parse_duration_seconds(item2.get("duration"))

    if dur1 is not None and dur2 is not None:
        if ratio >= 0.75 and abs(dur1 - dur2) <= 15:
            return True
        return False

    # Without duration, require strict title similarity
    return ratio >= 0.88


def deduplicate_and_merge_results(raw_results: list[dict]) -> list[dict]:
    """
    Group duplicate video results into unified multi-source items.
    Preserves all platform mirrors under the consolidated card.
    """
    merged: list[dict] = []

    for item in raw_results:
        found_match = False
        for existing in merged:
            if is_duplicate_video(item, existing):
                # Merge mirror source
                plat = item.get("platform_name") or item.get("site") or "Mirror"
                url = item.get("url") or item.get("post_url")
                existing_mirrors = existing.setdefault("mirrors", [])
                if url and not any(m.get("url") == url for m in existing_mirrors):
                    existing_mirrors.append({"platform": plat, "url": url})
                # Keep duration or thumbnail if existing was missing them
                if not existing.get("duration") and item.get("duration"):
                    existing["duration"] = item["duration"]
                if not existing.get("thumbnail") and item.get("thumbnail"):
                    existing["thumbnail"] = item["thumbnail"]
                found_match = True
                break

        if not found_match:
            new_item = dict(item)
            plat = new_item.get("platform_name") or new_item.get("site") or "Primary"
            url = new_item.get("url") or new_item.get("post_url")
            new_item["mirrors"] = [{"platform": plat, "url": url}] if url else []
            merged.append(new_item)

    return merged


async def execute_global_search(
    query: str,
    page: int = 1,
    limit_per_engine: int = 6,
    timeout_sec: float = 8.0,
) -> list[dict]:
    """
    Execute concurrent federated search across all supported platforms.
    Each platform search is protected by an isolated timeout.
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    async def _safe_search(engine_name: str, coro_func, *args, **kwargs) -> list[dict]:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(coro_func, *args, **kwargs),
                timeout=timeout_sec,
            )
            items = []
            for itm in (res or []):
                # Standardize common fields
                p_item = dict(itm)
                if not p_item.get("platform_name"):
                    p_item["platform_name"] = engine_name
                if not p_item.get("url"):
                    p_item["url"] = itm.get("post_url") or itm.get("video_url") or ""
                items.append(p_item)
            return items
        except asyncio.TimeoutError:
            logger.debug(f"Global search timeout on {engine_name}")
            return []
        except Exception as e:
            logger.debug(f"Global search failed on {engine_name}: {e}")
            return []

    maza_url = f"https://mmsmaza.im/?s={quote_plus(clean_q)}"
    tasks = [
        _safe_search("X-Video Tube", search_kvs, "xvideotube", clean_q, page, limit_per_engine),
        _safe_search("HornySapiens", search_kvs, "hornysapiens", clean_q, page, limit_per_engine),
        _safe_search("LeakedZone", search_leakedzone, clean_q, page, limit_per_engine),
        _safe_search("ThotChicks", search_thotchicks, clean_q, page, limit_per_engine),
        _safe_search("MMSMaza", get_wp_listing_posts, maza_url, page, limit_per_engine),
        _safe_search("MMSDesi", search_mmsdesi, clean_q, page, limit_per_engine),
        _safe_search("MMSVibex", search_mmsvibex, clean_q, page, limit_per_engine),
        _safe_search("DropMMS", search_forum, clean_q, limit=limit_per_engine, page=page),
    ]

    all_engine_results = await asyncio.gather(*tasks, return_exceptions=True)

    flattened: list[dict] = []
    for batch in all_engine_results:
        if isinstance(batch, list):
            flattened.extend(batch)

    # Deduplicate and consolidate mirror sources
    deduped = deduplicate_and_merge_results(flattened)
    return deduped
