# tests/test_bot.py
"""
Unit tests for bot message formatting, UI buttons, and database integration.
"""

import uuid
import unittest
from unittest.mock import MagicMock, AsyncMock
from bot import format_post_card, group_links_by_host
from scraper import get_host_display_name
import db


class TestBot(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_group_links_by_host(self):
        """Test grouping of links by streaming provider."""
        links = [
            "https://vidara.to/v/part1",
            "https://vidara.to/v/part2",
            "https://streamtape.com/e/tape1",
        ]
        grouped = group_links_by_host(links)
        self.assertIn("⚡ Vidara", grouped)
        self.assertIn("🎬 Streamtape", grouped)
        self.assertEqual(len(grouped["⚡ Vidara"]), 2)
        self.assertEqual(len(grouped["🎬 Streamtape"]), 1)

    def test_format_post_card(self):
        """Test formatting of post details card with blockquote title and preferred link."""
        details = {
            "title": "Sample Movie <4K>",
            "post_url": "https://dropmms.com/topic/123-movie/",
            "tags": ["4K", "1080P"],
            "streaming_links": [
                "https://vidara.to/v/part1",
                "https://vidara.to/v/part2",
                "https://streamtape.com/e/tape1",
            ],
            "thumbnail": "https://dropmms.com/thumb.jpg",
        }
        # Preferred: vidara
        caption = format_post_card(details, user_pref="vidara")
        self.assertIn("<blockquote>🎬 <b>Sample Movie &lt;4K&gt;</b></blockquote>", caption)
        self.assertIn("#4K", caption)
        self.assertIn("⚡ Vidara Links:", caption)
        self.assertIn("1. <code>https://vidara.to/v/part1</code>", caption)
        self.assertIn("2. <code>https://vidara.to/v/part2</code>", caption)
        # Should NOT have streamtape when vidara is preferred and present
        self.assertNotIn("streamtape.com", caption)

        # Fallback test: when preferred host (e.g. doodstream) is not in post
        caption_fallback = format_post_card(details, user_pref="doodstream")
        self.assertIn("Using alternative", caption_fallback)

    def test_user_host_preference_db(self):
        """Test setting and getting user host preference in db."""
        test_uid = int(uuid.uuid4().int % 1000000000)
        # Default should be streamtape
        self.assertEqual(db.get_user_host_preference(test_uid), "streamtape")

        # Update to vidara
        db.set_user_host_preference(test_uid, "vidara")
        self.assertEqual(db.get_user_host_preference(test_uid), "vidara")

        # Update back to streamtape
        db.set_user_host_preference(test_uid, "streamtape")
        self.assertEqual(db.get_user_host_preference(test_uid), "streamtape")

    def test_database_channel_linking(self):
        """Test channel registration, retrieval, and removal in SQLite."""
        test_channel_id = -100123456789
        # Add channel
        added = db.add_or_update_channel(
            channel_id=test_channel_id,
            title="Test Movie Channel",
            username="test_movies",
            category_url="https://dropmms.com/forum/2-general/",
        )
        self.assertTrue(added)

        # Retrieve channel
        ch = db.get_channel(test_channel_id)
        self.assertIsNotNone(ch)
        self.assertEqual(ch["title"], "Test Movie Channel")
        self.assertEqual(ch["is_active"], 1)

        # Mark post seen
        test_post = f"https://dropmms.com/topic/test-{uuid.uuid4()}/"
        self.assertFalse(db.is_post_seen(test_post))
        db.mark_post_seen(test_post, "Test Post Title")
        self.assertTrue(db.is_post_seen(test_post))

        # Remove channel
        removed = db.remove_channel(test_channel_id)
        self.assertTrue(removed)
        self.assertIsNone(db.get_channel(test_channel_id))

    def test_url_cache_short_id(self):
        """Test url_cache mapping for callback_data limit."""
        url = "https://dropmms.com/topic/12345-extremely-long-title-that-exceeds-sixty-four-bytes-limit-in-telegram/"
        short_id = db.get_or_create_short_id(url)
        self.assertIsInstance(short_id, int)
        self.assertGreater(short_id, 0)

        # Retrieve back
        resolved = db.get_url_from_short_id(short_id)
        self.assertEqual(resolved, url)

    def test_cancellation_state(self):
        """Test chat scraping cancellation state machine."""
        from bot import start_scrape_for_chat, is_scrape_cancelled, cancel_scrape_for_chat, end_scrape_for_chat
        test_chat = 99887766

        start_scrape_for_chat(test_chat)
        self.assertFalse(is_scrape_cancelled(test_chat))

        cancel_scrape_for_chat(test_chat)
        self.assertTrue(is_scrape_cancelled(test_chat))

        # String chat_id should also work
        self.assertTrue(is_scrape_cancelled(str(test_chat)))

        end_scrape_for_chat(test_chat)
        self.assertFalse(is_scrape_cancelled(test_chat))

    def test_cancellable_sleep(self):
        """Test cancellable_sleep exits early when scrape is cancelled."""
        import asyncio
        import time
        from bot import cancellable_sleep, start_scrape_for_chat, cancel_scrape_for_chat
        test_chat = 55443322
        start_scrape_for_chat(test_chat)
        cancel_scrape_for_chat(test_chat)

        t0 = time.time()
        asyncio.run(cancellable_sleep(5.0, test_chat, step=0.1))
        t1 = time.time()
        self.assertLess(t1 - t0, 0.5)

    def test_group_links_by_host_priority_order(self):
        """Test that group_links_by_host orders providers strictly by PROVIDER_PRIORITY."""
        links = [
            "https://doodstream.com/d/dood1",
            "https://streamfiles.net/sf1",
            "https://vidara.to/v/vid1",
            "https://streamtape.com/e/tape1",
        ]
        grouped = group_links_by_host(links)
        badges = list(grouped.keys())
        # First must be Streamtape, then Vidara, then Streamfiles, then Doodstream
        self.assertEqual(badges[0], "🎬 Streamtape")
        self.assertEqual(badges[1], "⚡ Vidara")
        self.assertEqual(badges[2], "📥 Streamfiles")
        self.assertEqual(badges[3], "🎥 Doodstream")

    def test_slicing_args_and_apply_slice(self):
        """Test parse_slicing_args and apply_slice helper functions."""
        from scraper import parse_slicing_args, apply_slice

        # Single count
        url, start, end, is_last = parse_slicing_args(["https://dropmms.com/forum/2-general/", "4"])
        self.assertEqual(url, "https://dropmms.com/forum/2-general/")
        self.assertEqual(start, 1)
        self.assertEqual(end, 4)
        self.assertFalse(is_last)

        # Range
        url, start, end, is_last = parse_slicing_args(["https://dropmms.com/forum/2-general/", "1-5"])
        self.assertEqual(start, 1)
        self.assertEqual(end, 5)

        # Last N
        url, start, end, is_last = parse_slicing_args(["https://dropmms.com/forum/2-general/", "last", "5"])
        self.assertIsNone(start)
        self.assertEqual(end, 5)
        self.assertTrue(is_last)

        # Apply slice tests
        items = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertEqual(apply_slice(items, 1, 4, False), [1, 2, 3, 4])
        self.assertEqual(apply_slice(items, 3, 6, False), [3, 4, 5, 6])
        self.assertEqual(apply_slice(items, None, 5, True), [6, 7, 8, 9, 10])

    def test_forum_page_regex_in_bot(self):
        """Test page extraction regex in bot.py for forum URLs."""
        import re
        url1 = "https://dropmms.com/forum/4-desi/page/2/?sortby=start_date&sortdirection=desc"
        m1 = re.search(r"/page/(\d+)", url1, re.I) or re.search(r"[?&]page=(\d+)", url1, re.I)
        self.assertIsNotNone(m1)
        self.assertEqual(int(m1.group(1)), 2)

        url2 = "https://dropmms.com/forum/4-desi/?page=3"
        m2 = re.search(r"/page/(\d+)", url2, re.I) or re.search(r"[?&]page=(\d+)", url2, re.I)
        self.assertIsNotNone(m2)
        self.assertEqual(int(m2.group(1)), 3)

        url_no_page = "https://dropmms.com/forum/4-desi/"
        m_none = re.search(r"/page/(\d+)", url_no_page, re.I) or re.search(r"[?&]page=(\d+)", url_no_page, re.I)
        self.assertIsNone(m_none)

    async def test_search_command_no_args_shows_platforms(self):
        """Test /search with no args displays platform selection buttons."""
        from bot import search_command

        update = MagicMock()
        context = MagicMock()
        context.args = []
        msg = AsyncMock()
        update.effective_message = msg

        await search_command(update, context)
        msg.reply_text.assert_called_once()
        args, kwargs = msg.reply_text.call_args
        self.assertIn("Universal Search Engine", args[0])
        reply_markup = kwargs.get("reply_markup")
        self.assertIsNotNone(reply_markup)
        # Check that both buttons exist
        button_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertIn("sp_choose:lc", button_data)
        self.assertIn("sp_choose:fm", button_data)

    async def test_search_command_with_args(self):
        """Test /search with args displays platform buttons and stores search query."""
        from bot import search_command

        update = MagicMock()
        context = MagicMock()
        context.args = ["GoddessAnna"]
        context.user_data = {}
        msg = AsyncMock()
        update.effective_message = msg

        await search_command(update, context)
        self.assertEqual(context.user_data.get("search_query"), "GoddessAnna")
        msg.reply_text.assert_called_once()
        args, kwargs = msg.reply_text.call_args
        self.assertIn("GoddessAnna", args[0])
        button_data = [btn.callback_data for row in kwargs.get("reply_markup").inline_keyboard for btn in row]
        self.assertIn("sp_do:lc", button_data)
        self.assertIn("sp_do:fm", button_data)

    async def test_setlink_command_no_args(self):
        """Test /setlink command displays link mode selection keyboard."""
        from bot import setlink_command

        update = MagicMock()
        context = MagicMock()
        context.args = []
        msg = AsyncMock()
        update.effective_message = msg
        update.effective_user.id = 12345

        await setlink_command(update, context)
        msg.reply_text.assert_called_once()
        args, kwargs = msg.reply_text.call_args
        self.assertIn("LiveCam Link Display Settings", args[0])
        button_data = [btn.callback_data for row in kwargs.get("reply_markup").inline_keyboard for btn in row]
        self.assertIn("setlink_streaming", button_data)
        self.assertIn("setlink_both", button_data)
        self.assertIn("setlink_page", button_data)

    async def test_setlink_command_with_args(self):
        """Test /setlink <mode> saves user preference directly."""
        from bot import setlink_command

        update = MagicMock()
        context = MagicMock()
        msg = AsyncMock()
        update.effective_message = msg
        update.effective_user.id = 556677

        # Set to both
        context.args = ["both"]
        await setlink_command(update, context)
        self.assertEqual(db.get_user_link_mode(556677), "both")

        # Set to page
        context.args = ["page"]
        await setlink_command(update, context)
        self.assertEqual(db.get_user_link_mode(556677), "page")

        # Set to streaming
        context.args = ["streaming"]
        await setlink_command(update, context)
        self.assertEqual(db.get_user_link_mode(556677), "streaming")


if __name__ == "__main__":
    unittest.main()
