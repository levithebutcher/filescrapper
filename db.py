# db.py
"""
Lightweight SQLite database manager for FileScrapper bot.
Handles persistent channel links, auto-feed settings, and seen posts tracking.
Uses Python's standard sqlite3 library (zero external dependencies).
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent / "filescrapper.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables with indexes."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Connected Channels / Groups table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY,
                title TEXT,
                username TEXT,
                category_url TEXT,
                is_active INTEGER DEFAULT 1,
                added_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 2. Seen Posts (to prevent duplicate auto-posting to channels)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_posts (
                post_url TEXT PRIMARY KEY,
                title TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 3. Key-Value Bot Settings
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

        conn.commit()
        logger.info("✅ Database initialized successfully at %s", DB_PATH)


# --- Channel Management ---

def add_or_update_channel(channel_id: int, title: str, username: str = None, category_url: str = None, added_by: int = None) -> bool:
    """Link a channel with a target category URL."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO channels (channel_id, title, username, category_url, is_active, added_by, created_at)
                VALUES (?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id) DO UPDATE SET
                    title = excluded.title,
                    username = COALESCE(excluded.username, channels.username),
                    category_url = COALESCE(excluded.category_url, channels.category_url),
                    is_active = 1
                """,
                (channel_id, title, username, category_url, added_by),
            )
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error adding channel {channel_id}: {e}")
        return False


def get_channel(channel_id: int):
    """Fetch single channel configuration."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM channels WHERE channel_id = ?", (channel_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_active_channels() -> list[dict]:
    """Retrieve all active channels configured for auto-feed."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM channels WHERE is_active = 1")
        return [dict(row) for row in cursor.fetchall()]


def remove_channel(channel_id: int) -> bool:
    """Unlink and delete a channel from auto-feed."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing channel {channel_id}: {e}")
        return False


def set_channel_active(channel_id: int, is_active: bool) -> bool:
    """Pause or resume auto-posting for a specific channel."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE channels SET is_active = ? WHERE channel_id = ?", (1 if is_active else 0, channel_id))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error updating channel {channel_id} status: {e}")
        return False


# --- Seen Posts Tracker ---

def is_post_seen(post_url: str) -> bool:
    """Check if a post has already been posted to channels."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM seen_posts WHERE post_url = ?", (post_url,))
        return cursor.fetchone() is not None


def mark_post_seen(post_url: str, title: str = ""):
    """Record a post as posted to avoid duplicates."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO seen_posts (post_url, title, first_seen) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (post_url, title),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error marking post as seen: {e}")


# --- Bot Settings (Key-Value) ---

def get_setting(key: str, default: str = None) -> str:
    """Fetch setting value."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    """Persist setting value."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
