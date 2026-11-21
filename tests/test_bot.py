# tests/test_bot.py
"""
Unit tests for bot message formatting, UI buttons, and database integration.
"""

import uuid
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
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

    def test_get_host_settings_keyboard_includes_cloudfam(self):
        """Test that get_host_settings_keyboard includes cloudfam button."""
        from bot import get_host_settings_keyboard
        kb = get_host_settings_keyboard(current_pref="cloudfam")
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("sethost_cloudfam", callbacks)
        # Verify checkmark appears on active host
        cloudfam_btn = [btn for row in kb.inline_keyboard for btn in row if btn.callback_data == "sethost_cloudfam"][0]
        self.assertIn("✅", cloudfam_btn.text)
        self.assertIn("Cloudfam", cloudfam_btn.text)

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

    @patch("bot.get_livecam_model_stats")
    async def test_callback_query_sp_mdl(self, mock_stats):
        """Test callback_query_handler for model button (sp_mdl:) displays sorting options in blockquote."""
        from bot import callback_query_handler

        test_url = "https://livecamrips.to/model/36773/GoddessAnna"
        short_id = db.get_or_create_short_id(test_url)
        mock_stats.return_value = {
            "name": "GoddessAnna",
            "total_pages": 19,
            "total_videos_str": "304 (19 Pages)",
            "url": test_url,
        }

        update = MagicMock()
        context = MagicMock()
        context.user_data = {}
        query = AsyncMock()
        query.data = f"sp_mdl:{short_id}"
        query.message.chat_id = 12345
        update.callback_query = query

        await callback_query_handler(update, context)
        self.assertEqual(query.edit_message_text.call_count, 2)
        final_call = query.edit_message_text.call_args_list[-1]
        text = final_call[0][0]
        self.assertTrue(text.startswith("<blockquote>"))
        self.assertTrue(text.endswith("</blockquote>"))
        self.assertIn("GoddessAnna", text)
        self.assertIn("304 (19 Pages)", text)
        self.assertNotIn("Sort chunein", text)

        reply_markup = final_call[1].get("reply_markup")
        button_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertIn(f"sp_sort:{short_id}:newest", button_data)
        self.assertIn(f"sp_sort:{short_id}:most_viewed", button_data)
        self.assertIn(f"sp_sort:{short_id}:most_liked", button_data)
        self.assertIn(f"sp_sort:{short_id}:oldest", button_data)
        self.assertIn("sp_cancel", button_data)

    async def test_callback_query_sp_sort(self):
        """Test clicking sort button (sp_sort:) asks for range/count/page and sets user_data."""
        from bot import callback_query_handler

        test_url = "https://livecamrips.to/model/36773/GoddessAnna"
        short_id = db.get_or_create_short_id(test_url)

        update = MagicMock()
        context = MagicMock()
        context.user_data = {
            f"model_stats_{short_id}": {
                "name": "GoddessAnna",
                "total_str": "304 (19 Pages)",
                "url": test_url,
            }
        }
        query = AsyncMock()
        query.data = f"sp_sort:{short_id}:most_viewed"
        query.message.chat_id = 12345
        query.message.message_id = 67890
        update.callback_query = query

        await callback_query_handler(update, context)
        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        self.assertTrue(text.startswith("<blockquote>"))
        self.assertTrue(text.endswith("</blockquote>"))
        self.assertIn("Most Viewed", text)
        self.assertIn("Enter Range, Count or Page", text)

        # Verify state stored in user_data
        flow = context.user_data.get("awaiting_model_range")
        self.assertIsNotNone(flow)
        self.assertEqual(flow["short_id"], short_id)
        self.assertEqual(flow["sort_by"], "most_viewed")
        self.assertEqual(flow["chat_id"], 12345)
        self.assertEqual(flow["message_id"], 67890)

    @patch("bot.run_livecam_model_scrape")
    async def test_handle_message_model_range_valid(self, mock_run_scrape):
        """Test entering a valid range (e.g. 5-10) deletes user message and triggers scrape."""
        from bot import handle_message

        test_url = "https://livecamrips.to/model/36773/GoddessAnna"
        short_id = db.get_or_create_short_id(test_url)

        update = MagicMock()
        msg = AsyncMock()
        msg.text = "5-10"
        msg.delete = AsyncMock()
        update.message = msg
        update.effective_message = msg
        update.effective_chat.id = 12345
        update.effective_user.id = 99999

        context = MagicMock()
        context.bot.edit_message_text = AsyncMock()
        context.user_data = {
            "awaiting_model_range": {
                "short_id": short_id,
                "url": test_url,
                "model_name": "GoddessAnna",
                "total_str": "304 (19 Pages)",
                "sort_by": "most_liked",
                "chat_id": 12345,
                "message_id": 67890,
            }
        }

        await handle_message(update, context)
        # Message was deleted to keep chat clean
        msg.delete.assert_called_once()
        # Card edited in place
        context.bot.edit_message_text.assert_called_once()
        # State cleared
        self.assertNotIn("awaiting_model_range", context.user_data)
        # Scrape worker launched with correct args
        mock_run_scrape.assert_called_once()
        _, kwargs = mock_run_scrape.call_args
        self.assertEqual(kwargs["sort_by"], "most_liked")
        self.assertEqual(kwargs["start_idx"], 5)
        self.assertEqual(kwargs["end_idx"], 10)
        self.assertIsNone(kwargs["page_num"])

    async def test_handle_message_model_range_invalid(self):
        """Test entering invalid range updates the card with warning and retains prompt."""
        from bot import handle_message

        test_url = "https://livecamrips.to/model/36773/GoddessAnna"
        short_id = db.get_or_create_short_id(test_url)

        update = MagicMock()
        msg = AsyncMock()
        msg.text = "invalid_text"
        msg.delete = AsyncMock()
        update.message = msg
        update.effective_message = msg
        update.effective_chat.id = 12345
        update.effective_user.id = 99999

        context = MagicMock()
        context.bot.edit_message_text = AsyncMock()
        context.user_data = {
            "awaiting_model_range": {
                "short_id": short_id,
                "url": test_url,
                "model_name": "GoddessAnna",
                "total_str": "304 (19 Pages)",
                "sort_by": "newest",
                "chat_id": 12345,
                "message_id": 67890,
            }
        }

        await handle_message(update, context)
        msg.delete.assert_called_once()
        context.bot.edit_message_text.assert_called_once()
        args, kwargs = context.bot.edit_message_text.call_args
        self.assertIn("Invalid format", kwargs["text"])
        self.assertIn("invalid_text", kwargs["text"])
        # State should still be active for user to retry
        self.assertIn("awaiting_model_range", context.user_data)

    @patch("bot.get_dropmms_forums")
    async def test_callback_query_sp_choose_fm(self, mock_forums):
        """Test clicking DropMMS Forum in /search displays category buttons and keyword search option."""
        from bot import callback_query_handler

        mock_forums.return_value = [
            {"title": "Desi Videos & MMS", "url": "https://dropmms.com/forum/4-desi/"},
            {"title": "General Discussion", "url": "https://dropmms.com/forum/2-general/"},
        ]
        update = MagicMock()
        context = MagicMock()
        context.user_data = {}
        query = AsyncMock()
        query.data = "sp_choose:fm"
        query.message.chat_id = 12345
        update.callback_query = query

        await callback_query_handler(update, context)
        self.assertEqual(query.edit_message_text.call_count, 2)
        final_call = query.edit_message_text.call_args_list[-1]
        text = final_call[0][0]
        self.assertIn("DropMMS Forums", text)
        self.assertIn("Select a forum category", text)

        reply_markup = final_call[1].get("reply_markup")
        button_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertTrue(any(b.startswith("sp_cat:") for b in button_data))
        self.assertIn("sp_choose_kw:fm", button_data)
        self.assertIn("cb_search", button_data)
        self.assertIn("sp_cancel", button_data)

    @patch("bot.get_dropmms_category_stats")
    async def test_callback_query_sp_cat(self, mock_stats):
        """Test clicking a forum category button displays 2 filter buttons (Upload Date & Recently Updated)."""
        from bot import callback_query_handler

        test_url = "https://dropmms.com/forum/4-desi/"
        short_id = db.get_or_create_short_id(test_url)
        mock_stats.return_value = {
            "title": "Desi Videos & MMS",
            "total_pages": 45,
            "total_topics_str": "1125 (45 Pages)",
            "url": test_url,
        }

        update = MagicMock()
        context = MagicMock()
        context.user_data = {}
        query = AsyncMock()
        query.data = f"sp_cat:{short_id}"
        query.message.chat_id = 12345
        update.callback_query = query

        await callback_query_handler(update, context)
        self.assertEqual(query.edit_message_text.call_count, 2)
        final_call = query.edit_message_text.call_args_list[-1]
        text = final_call[0][0]
        self.assertTrue(text.startswith("<blockquote>"))
        self.assertIn("Desi Videos", text)
        self.assertIn("1125 (45 Pages)", text)

        reply_markup = final_call[1].get("reply_markup")
        button_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertIn(f"sp_csort:{short_id}:start_date", button_data)
        self.assertIn(f"sp_csort:{short_id}:updated", button_data)
        self.assertIn("sp_choose:fm", button_data)
        self.assertIn("sp_cancel", button_data)

    async def test_callback_query_sp_csort(self):
        """Test clicking sort button (sp_csort:) for a forum category sets user_data prompt."""
        from bot import callback_query_handler

        test_url = "https://dropmms.com/forum/4-desi/"
        short_id = db.get_or_create_short_id(test_url)

        update = MagicMock()
        context = MagicMock()
        context.user_data = {
            f"cat_stats_{short_id}": {
                "title": "Desi Videos & MMS",
                "total_str": "1125 (45 Pages)",
                "url": test_url,
            }
        }
        query = AsyncMock()
        query.data = f"sp_csort:{short_id}:start_date"
        query.message.chat_id = 12345
        query.message.message_id = 77777
        update.callback_query = query

        await callback_query_handler(update, context)
        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        self.assertIn("Upload Date (Start Date)", text)
        self.assertIn("Enter Range, Count or Page", text)

        cat_flow = context.user_data.get("awaiting_category_range")
        self.assertIsNotNone(cat_flow)
        self.assertEqual(cat_flow["short_id"], short_id)
        self.assertEqual(cat_flow["sort_by"], "start_date")
        self.assertEqual(cat_flow["chat_id"], 12345)
        self.assertEqual(cat_flow["message_id"], 77777)

    @patch("bot.run_forum_category_scrape")
    async def test_handle_message_category_range_valid(self, mock_cat_scrape):
        """Test entering a valid range for forum category deletes user message and triggers scrape."""
        from bot import handle_message

        test_url = "https://dropmms.com/forum/4-desi/"
        short_id = db.get_or_create_short_id(test_url)

        update = MagicMock()
        msg = AsyncMock()
        msg.text = "page 2"
        msg.delete = AsyncMock()
        update.message = msg
        update.effective_message = msg
        update.effective_chat.id = 12345
        update.effective_user.id = 99999

        context = MagicMock()
        context.bot.edit_message_text = AsyncMock()
        context.user_data = {
            "awaiting_category_range": {
                "short_id": short_id,
                "url": test_url,
                "cat_title": "Desi Videos & MMS",
                "total_str": "1125 (45 Pages)",
                "sort_by": "start_date",
                "chat_id": 12345,
                "message_id": 77777,
            }
        }

        await handle_message(update, context)
        msg.delete.assert_called_once()
        context.bot.edit_message_text.assert_called_once()
        self.assertNotIn("awaiting_category_range", context.user_data)
        mock_cat_scrape.assert_called_once()
        _, kwargs = mock_cat_scrape.call_args
        self.assertEqual(kwargs["page_num"], 2)
        self.assertEqual(kwargs["sort_by"], "start_date")
        self.assertIsNone(kwargs["end_idx"])


if __name__ == "__main__":
    unittest.main()
