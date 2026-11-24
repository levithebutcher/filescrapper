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
        self.assertIn("<blockquote>🎬 <b>Sample Movie &lt;4K&gt;</b>", caption)
        self.assertIn("🏛️ <b>Platform:</b> DropMMS</blockquote>", caption)
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
        self.assertNotIn("sp_choose_kw:fm", button_data)
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
        self.assertIn("Range, Count or Page", text)
        self.assertIn("Quick Filter by Date (IST)", text)
        # Check date filter buttons in markup
        reply_markup = query.edit_message_text.call_args[1].get("reply_markup")
        callbacks = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertIn(f"sp_cdate:{short_id}:start_date:today", callbacks)
        self.assertIn(f"sp_cdate:{short_id}:start_date:yesterday", callbacks)

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

    @patch("bot.run_forum_category_scrape")
    async def test_callback_query_sp_cdate(self, mock_cat_scrape):
        """Test clicking sp_cdate:today button triggers category scrape with date_filter=today."""
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
        query.data = f"sp_cdate:{short_id}:start_date:today"
        query.message.chat_id = 12345
        query.message.message_id = 77777
        query.from_user.id = 99999
        update.callback_query = query

        await callback_query_handler(update, context)
        query.edit_message_text.assert_called_once()
        self.assertNotIn("awaiting_category_range", context.user_data)
        mock_cat_scrape.assert_called_once()
        _, kwargs = mock_cat_scrape.call_args
        self.assertEqual(kwargs["date_filter"], "today")
        self.assertTrue(kwargs["only_today"])
        self.assertEqual(kwargs["sort_by"], "start_date")

    @patch("bot.run_forum_category_scrape")
    async def test_handle_message_category_range_date_word(self, mock_cat_scrape):
        """Test typing 'today' or 'yesterday' triggers category scrape with date_filter."""
        from bot import handle_message

        test_url = "https://dropmms.com/forum/4-desi/"
        short_id = db.get_or_create_short_id(test_url)

        update = MagicMock()
        msg = AsyncMock()
        msg.text = "yesterday"
        msg.delete = AsyncMock()
        msg.chat_id = 12345
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
        self.assertEqual(kwargs["date_filter"], "yesterday")
        self.assertEqual(kwargs["sort_by"], "start_date")


    @patch("bot.get_forum_topics", return_value=[])
    async def test_run_forum_category_scrape_no_topics_today_buttons(self, mock_get_topics):
        """Test that when 0 topics are found for today, status message provides helpful next action buttons."""
        from bot import run_forum_category_scrape

        bot_mock = AsyncMock()
        status_msg = AsyncMock()
        test_url = "https://dropmms.com/forum/2-desi/"

        await run_forum_category_scrape(
            bot=bot_mock,
            chat_id=12345,
            target_url=test_url,
            only_today=True,
            date_filter="today",
            sort_by="start_date",
            status_msg=status_msg,
            cat_title="Desi Videos",
        )

        self.assertEqual(status_msg.edit_text.call_count, 2)
        args, kwargs = status_msg.edit_text.call_args
        sent_text = args[0] if args else kwargs.get("text", "")
        self.assertIn("No uploads found today (IST)", sent_text)
        self.assertIn("reply_markup", kwargs)
        markup = kwargs["reply_markup"]
        btn_texts = [btn.text for row in markup.inline_keyboard for btn in row]
        self.assertIn("📆 Check Yesterday & Today", btn_texts)
        self.assertIn("🔝 Latest 10 Posts", btn_texts)
        self.assertIn("🔙 Back to Category", btn_texts)

    @patch("bot.process_topic_scrape")
    @patch("bot.get_forum_topics")
    async def test_run_forum_category_scrape_completion_card_and_cleanup(self, mock_get_topics, mock_process):
        """Test that top progress message is deleted and options card is resurfaced at the bottom."""
        from bot import run_forum_category_scrape

        mock_get_topics.return_value = [
            {"title": "Topic 1", "url": "https://dropmms.com/topic/1-one/"},
            {"title": "Topic 2", "url": "https://dropmms.com/topic/2-two/"},
        ]
        bot_mock = AsyncMock()
        end_msg_mock = MagicMock()
        end_msg_mock.message_id = 9999
        bot_mock.send_message.return_value = end_msg_mock
        status_msg = AsyncMock()
        status_msg.message_id = 8888

        context = MagicMock()
        context.user_data = {}

        await run_forum_category_scrape(
            bot=bot_mock,
            chat_id=12345,
            target_url="https://dropmms.com/forum/2-desi/",
            status_msg=status_msg,
            cat_title="Desi Videos",
            context=context,
        )

        # 1. Ephemeral cleanup: status_msg deleted
        status_msg.delete.assert_called_once()

        # 2. Resurfaced card sent at bottom
        bot_mock.send_message.assert_called_once()
        args, kwargs = bot_mock.send_message.call_args
        card_text = kwargs.get("text", "")
        self.assertIn("Extraction Complete!", card_text)
        self.assertIn("Delivered: <b>2</b> topic(s)", card_text)
        self.assertIn("Desi Videos", card_text)

        markup = kwargs.get("reply_markup")
        btn_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertTrue(any("today" in b for b in btn_data))
        self.assertTrue(any("yesterday" in b for b in btn_data))

        # 3. Context registered for immediate next range input
        self.assertIn("awaiting_category_range", context.user_data)
        self.assertEqual(context.user_data["awaiting_category_range"]["message_id"], 9999)

    def test_format_post_card_attached_album_and_sites(self):
        """Test format_post_card handles attached photo albums and video page links cleanly."""
        # 1. MMSVibex Video with attached album
        vibex_details = {
            "title": "Sakshi Media Video",
            "post_url": "https://mmsvibex.life/sakshi-video/",
            "tags": ["1080p"],
            "streaming_links": ["https://cdn.mmsvibex.fit/processed/1900438950_final.mp4"],
            "attached_photo_albums": [
                {"title": "Sakshi Album 1 (12 photos)", "url": "https://mmsvibex.life/photos/sakshi-1/"},
                {"title": "Sakshi Album 2 (98 photos)", "url": "https://mmsvibex.life/photos/sakshi-2/"},
            ],
            "collection_url": "https://mmsvibex.life/actor/sakshi/",
            "site": "mmsvibex",
        }
        card_vibex = format_post_card(vibex_details, user_pref="all")
        self.assertIn("<blockquote>📸 <b>Attached Photo Albums:</b></blockquote>", card_vibex)
        self.assertIn("<code>https://mmsvibex.life/photos/sakshi-1/</code>", card_vibex)
        self.assertIn("<code>https://mmsvibex.life/photos/sakshi-2/</code>", card_vibex)
        self.assertIn("<blockquote>📹 <b>Attached Video Parts:</b></blockquote>", card_vibex)
        self.assertIn("<code>https://mmsvibex.life/actor/sakshi/</code>", card_vibex)
        self.assertIn("🔗 <code>https://mmsvibex.life/sakshi-video/</code>", card_vibex)
        self.assertNotIn("Original Video Page", card_vibex)
        self.assertNotIn("cdn.mmsvibex.fit", card_vibex)

        # 2. WordPress Locker Post
        wp_details = {
            "title": "Desi Locker Video",
            "post_url": "https://desijugar.me/2026/11/22/post-1/",
            "tags": ["720p"],
            "streaming_links": ["https://cloudfam.io/12345"],
            "site": "wp_locker",
        }
        card_wp = format_post_card(wp_details, user_pref="all")
        self.assertIn("🌐 <a href='https://desijugar.me/2026/11/22/post-1/'>Original Post</a>", card_wp)

    async def test_search_command_multi_platform_buttons(self):
        """Test /search displays buttons for all 5 integrated platforms."""
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
        button_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertIn("sp_choose:fm", button_data)     # DropMMS
        self.assertIn("sp_choose:mmst", button_data)   # MMSTown
        self.assertIn("sp_choose:vibex", button_data)  # MMSVibex
        self.assertIn("sp_choose:lc", button_data)     # LiveCamRips
        self.assertIn("sp_wpsite:omaal", button_data)      # Omaal63
        self.assertIn("sp_wpsite:desijugar", button_data)  # DesiJugar
        self.assertIn("sp_wpsite:gulabi", button_data)     # GulabiHub
        self.assertIn("cb_main_menu", button_data)         # Back
        self.assertIn("sp_cancel", button_data)            # Cancel

    @patch("bot.send_post_card")
    @patch("bot.get_mmsvibex_video_details")
    async def test_handle_raw_url_mmsvibex_video(self, mock_details, mock_send):
        """Test sending a single MMSVibex video URL routes to MMSVibex video extraction."""
        from bot import handle_raw_url

        mock_details.return_value = {
            "title": "Sakshi Video",
            "post_url": "https://mmsvibex.life/sakshi-video/",
            "streaming_links": ["https://cdn.mmsvibex.fit/final.mp4"],
        }
        update = MagicMock()
        msg = AsyncMock()
        msg.text = "https://mmsvibex.life/sakshi-video/"
        msg.chat_id = 12345
        status_msg = AsyncMock()
        msg.reply_text.return_value = status_msg
        update.effective_message = msg
        update.effective_user.id = 99999

        context = MagicMock()
        context.bot = AsyncMock()
        context.user_data = {}

        await handle_raw_url(update, context, "https://mmsvibex.life/sakshi-video/")
        mock_details.assert_called_once_with("https://mmsvibex.life/sakshi-video/")
        mock_send.assert_called_once()

    @patch("bot.send_post_card")
    @patch("bot.get_mmsvibex_photo_details")
    async def test_handle_raw_url_mmsvibex_photo(self, mock_details, mock_send):
        """Test sending an MMSVibex photo album URL routes to photo ZIP extraction."""
        from bot import handle_raw_url

        mock_details.return_value = {
            "title": "Nisha Mony Album",
            "post_url": "https://mmsvibex.life/photos/nisha-mony/",
            "streaming_links": ["https://cdn.mmsvibex.fit/downloads/nisha.zip"],
        }
        update = MagicMock()
        msg = AsyncMock()
        msg.text = "https://mmsvibex.life/photos/nisha-mony/"
        msg.chat_id = 12345
        status_msg = AsyncMock()
        msg.reply_text.return_value = status_msg
        update.effective_message = msg
        update.effective_user.id = 99999

        context = MagicMock()
        context.bot = AsyncMock()
        context.user_data = {}

        await handle_raw_url(update, context, "https://mmsvibex.life/photos/nisha-mony/")
        mock_details.assert_called_once_with("https://mmsvibex.life/photos/nisha-mony/")
        mock_send.assert_called_once()

    @patch("bot.send_post_card")
    @patch("bot.get_wp_post_details")
    async def test_handle_raw_url_wp_locker_post(self, mock_details, mock_send):
        """Test sending a WordPress locker URL routes to WP post extraction."""
        from bot import handle_raw_url

        mock_details.return_value = {
            "title": "Desi Post",
            "post_url": "https://desijugar.me/2026/11/22/post-1/",
            "streaming_links": ["https://cloudfam.io/12345"],
        }
        update = MagicMock()
        msg = AsyncMock()
        msg.text = "https://desijugar.me/2026/11/22/post-1/"
        msg.chat_id = 12345
        status_msg = AsyncMock()
        msg.reply_text.return_value = status_msg
        update.effective_message = msg
        update.effective_user.id = 99999

        context = MagicMock()
        context.bot = AsyncMock()
        context.user_data = {}

        await handle_raw_url(update, context, "https://desijugar.me/2026/11/22/post-1/")
        mock_details.assert_called_once_with("https://desijugar.me/2026/11/22/post-1/")
        mock_send.assert_called_once()

    @patch("bot.get_mmstown_forums")
    async def test_callback_query_sp_choose_mmst(self, mock_forums):
        """Test clicking MMSTown button in /search displays MMSTown categories."""
        from bot import callback_query_handler

        mock_forums.return_value = [
            {"id": 7, "title": "Desi New Videos HD/SD", "url": "https://mmstown.com/forum/7-desi/"},
            {"id": 8, "title": "Desi Web Series", "url": "https://mmstown.com/forum/8-series/"},
        ]
        update = MagicMock()
        context = MagicMock()
        context.user_data = {}
        query = AsyncMock()
        query.data = "sp_choose:mmst"
        query.message.chat_id = 12345
        update.callback_query = query

        await callback_query_handler(update, context)
        self.assertEqual(query.edit_message_text.call_count, 2)
        final_call = query.edit_message_text.call_args_list[-1]
        text = final_call[0][0]
        self.assertIn("MMSTown Forums", text)
        self.assertIn("Select a forum category", text)

        reply_markup = final_call[1].get("reply_markup")
        button_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertTrue(any(b.startswith("sp_cat:") for b in button_data))
        self.assertNotIn("sp_choose_kw:mmst", button_data)
        self.assertIn("cb_search", button_data)
        self.assertIn("sp_cancel", button_data)

    async def test_callback_query_sp_choose_vibex(self):
        """Test clicking MMSVibex button in /search displays dynamic sorting options."""
        from bot import callback_query_handler

        update = MagicMock()
        context = MagicMock()
        context.user_data = {}
        query = AsyncMock()
        query.data = "sp_choose:vibex"
        query.message.chat_id = 12345
        update.callback_query = query

        await callback_query_handler(update, context)
        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        self.assertIn("MMSVibex Hub", text)

        reply_markup = query.edit_message_text.call_args[1].get("reply_markup")
        button_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertIn("sp_choose_kw:vibex", button_data)
        self.assertIn("sp_vsort:latest", button_data)
        self.assertIn("sp_vsort:photos", button_data)
        self.assertIn("cb_search", button_data)
        self.assertIn("sp_cancel", button_data)
        self.assertNotIn("sp_vsort:most-viewed", button_data)

    async def test_callback_query_sp_choose_wplock(self):
        """Test clicking WP Locker Sites button in /search displays site options."""
        from bot import callback_query_handler

        update = MagicMock()
        context = MagicMock()
        context.user_data = {}
        query = AsyncMock()
        query.data = "sp_choose:wplock"
        query.message.chat_id = 12345
        update.callback_query = query

        await callback_query_handler(update, context)
        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        self.assertIn("WordPress Locker Hub", text)

        reply_markup = query.edit_message_text.call_args[1].get("reply_markup")
        button_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertIn("sp_wpsite:omaal", button_data)
        self.assertIn("sp_wpsite:desijugar", button_data)
        self.assertIn("sp_wpsite:gulabi", button_data)
        self.assertIn("cb_search", button_data)

    @patch("bot.send_post_card")
    @patch("bot.get_mmsvibex_actor_videos")
    async def test_mmsvibex_normal_and_advance_mode_callback(self, mock_actor_vids, mock_send):
        """Test MMSVibex Normal mode delivers single video with extract button, and Advance mode delivers all parts."""
        from bot import callback_query_handler

        target_url = "https://mmsvibex.life/submissive-baddie-part-2/"
        short_id = db.get_or_create_short_id(target_url)

        # 1. Normal mode (mv_opt:{sid}:norm)
        update_norm = MagicMock()
        context_norm = MagicMock()
        context_norm.user_data = {
            f"mv_dt_{short_id}": {
                "title": "Submissive Baddie Part 2",
                "post_url": target_url,
                "collection_url": "https://mmsvibex.life/actor/submissive-baddie/",
                "streaming_links": ["https://cdn.mmsvibex.fit/final.mp4"],
            }
        }
        query_norm = AsyncMock()
        query_norm.data = f"mv_opt:{short_id}:norm"
        query_norm.message.chat_id = 12345
        update_norm.callback_query = query_norm

        await callback_query_handler(update_norm, context_norm)
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        self.assertIsNotNone(kwargs.get("reply_markup"))
        btn_data = [btn.callback_data for row in kwargs["reply_markup"].inline_keyboard for btn in row]
        self.assertIn(f"mv_all:{short_id}", btn_data)

        # 2. Advance mode (mv_opt:{sid}:adv / mv_all)
        mock_send.reset_mock()
        mock_actor_vids.return_value = [
            {"title": "Part 1", "url": "https://mmsvibex.life/part-1/"},
            {"title": "Part 2", "url": "https://mmsvibex.life/part-2/"},
        ]
        update_adv = MagicMock()
        context_adv = MagicMock()
        context_adv.user_data = {
            f"mv_dt_{short_id}": {
                "title": "Submissive Baddie Part 2",
                "post_url": target_url,
                "collection_url": "https://mmsvibex.life/actor/submissive-baddie/",
                "streaming_links": ["https://cdn.mmsvibex.fit/final.mp4"],
            }
        }
        query_adv = AsyncMock()
        query_adv.data = f"mv_opt:{short_id}:adv"
        query_adv.message.chat_id = 12345
        status_msg = AsyncMock()
        query_adv.message.reply_text.return_value = status_msg
        update_adv.callback_query = query_adv

        with patch("bot.get_mmsvibex_video_details") as mock_vdetails:
            mock_vdetails.side_effect = [
                {"title": "Part 1", "post_url": "https://mmsvibex.life/part-1/", "streaming_links": ["https://cdn.mmsvibex.fit/1.mp4"]},
                {"title": "Part 2", "post_url": "https://mmsvibex.life/part-2/", "streaming_links": ["https://cdn.mmsvibex.fit/2.mp4"]},
            ]
            await callback_query_handler(update_adv, context_adv)
            self.assertEqual(mock_send.call_count, 2)

    async def test_callback_query_main_menu_and_nav_keyboard(self):
        """Test cb_main_menu callback routes to start_command and get_navigation_keyboard provides persistent buttons."""
        from bot import callback_query_handler, get_navigation_keyboard

        nav_kb = get_navigation_keyboard()
        buttons = [btn.callback_data for row in nav_kb.inline_keyboard for btn in row]
        self.assertIn("cb_search", buttons)
        self.assertIn("cb_main_menu", buttons)

        update = MagicMock()
        query = AsyncMock()
        query.data = "cb_main_menu"
        update.callback_query = query
        msg = AsyncMock()
        update.effective_message = msg
        update.effective_user.first_name = "Alex"
        context = MagicMock()

        await callback_query_handler(update, context)
        msg.reply_text.assert_called_once()
        args, kwargs = msg.reply_text.call_args
        self.assertIn("Welcome, Alex!", args[0])

    @patch("bot.process_topic_scrape")
    async def test_callback_query_sc_extracts_and_sends_navigation(self, mock_scrape):
        """Test tapping sc_<id> extracts the post and sends persistent navigation controls."""
        from bot import callback_query_handler

        target_url = "https://dropmms.com/topic/123-nav-test/"
        short_id = db.get_or_create_short_id(target_url)

        update = MagicMock()
        query = AsyncMock()
        query.data = f"sc_{short_id}"
        query.message.chat_id = 12345
        query.from_user.id = 99999
        update.callback_query = query
        context = MagicMock()

        await callback_query_handler(update, context)
        mock_scrape.assert_called_once_with(context.bot, 12345, target_url, user_id=99999)
        context.bot.send_message.assert_called_once()
        _, kwargs = context.bot.send_message.call_args
        self.assertEqual(kwargs.get("chat_id"), 12345)
        self.assertIsNotNone(kwargs.get("reply_markup"))
        nav_buttons = [btn.callback_data for row in kwargs["reply_markup"].inline_keyboard for btn in row]
        self.assertIn("cb_search", nav_buttons)
        self.assertIn("cb_main_menu", nav_buttons)

    @patch("bot.execute_platform_search")
    async def test_sp_choose_lc_and_vibex_search_flow(self, mock_search):
        """Test clicking LiveCam or MMSVibex search prompts sets awaiting_search_flow and executes on text input."""
        from bot import callback_query_handler, handle_message

        # 1. LiveCam search prompt button
        update = MagicMock()
        query = AsyncMock()
        query.data = "sp_choose:lc"
        query.message.chat_id = 12345
        query.message.message_id = 991
        update.callback_query = query
        context = MagicMock()
        context.user_data = {}

        await callback_query_handler(update, context)
        self.assertIn("awaiting_search_flow", context.user_data)
        self.assertEqual(context.user_data["awaiting_search_flow"]["plat"], "lc")
        self.assertEqual(context.user_data["awaiting_search_flow"]["message_id"], 991)

        # User types model name in chat
        msg_update = MagicMock()
        msg_update.effective_chat.id = 12345
        msg_update.effective_user.id = 888
        msg_update.message.text = "GoddessAnna"
        msg_update.effective_message = AsyncMock()

        await handle_message(msg_update, context)
        mock_search.assert_called_once()
        _, s_kwargs = mock_search.call_args
        self.assertEqual(s_kwargs.get("plat"), "lc")
        self.assertEqual(s_kwargs.get("query"), "GoddessAnna")

    @patch("bot.execute_platform_search")
    async def test_search_flow_overrides_stale_range_states(self, mock_search):
        """Test that search flow takes priority and clears stale range flows."""
        from bot import callback_query_handler, handle_message

        # User previously had an active vibex range state
        context = MagicMock()
        context.user_data = {
            "awaiting_vibex_range": {
                "url": "https://mmsvibex.life/?filter=latest",
                "sort_key": "latest",
                "chat_id": 12345,
                "message_id": 555,
            }
        }

        # User clicks search button on MMSVibex hub
        update = MagicMock()
        query = AsyncMock()
        query.data = "sp_choose_kw:vibex"
        query.message.chat_id = 12345
        query.message.message_id = 888
        update.callback_query = query

        await callback_query_handler(update, context)
        self.assertNotIn("awaiting_vibex_range", context.user_data)
        self.assertIn("awaiting_search_flow", context.user_data)
        self.assertEqual(context.user_data["awaiting_search_flow"]["plat"], "vibex")

        # User sends search term
        msg_update = MagicMock()
        msg_update.effective_chat.id = 12345
        msg_update.effective_user.id = 888
        msg_update.message.text = "baddie"
        msg_update.effective_message = AsyncMock()

        await handle_message(msg_update, context)
        mock_search.assert_called_once()
        _, s_kwargs = mock_search.call_args
        self.assertEqual(s_kwargs.get("plat"), "vibex")
        self.assertEqual(s_kwargs.get("query"), "baddie")

    def test_mmsvibex_post_card_direct_page_and_unhidden_urls(self):
        """Test MMSVibex post card layout shows original page link, no CDN MP4, and unhidden media links."""
        details = {
            "title": "Popular Viral Dance",
            "post_url": "https://mmsvibex.life/popular-viral-dance/",
            "tags": ["1080p"],
            "streaming_links": ["https://cdn.mmsvibex.fit/processed/12345_final.mp4"],
            "attached_videos": [
                {"title": "02:04Tamil Girl Sai Part-11", "url": "https://mmsvibex.life/tamil-girl-part-11/"},
                {"title": "00:22Tamil Girl Sai Part-23", "url": "https://mmsvibex.life/tamil-girl-part-23/"},
            ],
            "attached_photo_albums": [
                {"title": "Dance Album 1 (85 photos)", "url": "https://mmsvibex.life/photos/dance-1/"},
            ],
            "site": "mmsvibex",
        }
        card = format_post_card(details, user_pref="streamtape")
        # 1. Main link is original video page URL directly
        self.assertIn("🔗 <code>https://mmsvibex.life/popular-viral-dance/</code>", card)
        # 2. No raw CDN mp4 or streamtape fallback warning
        self.assertNotIn("cdn.mmsvibex.fit", card)
        self.assertNotIn("Streamtape not available", card)
        self.assertNotIn("Original Video Page", card)
        # 3. Attached video parts have unhidden code URLs
        self.assertIn("<blockquote>📹 <b>Attached Video Parts:</b></blockquote>", card)
        self.assertIn("<b>1. Tamil Girl Sai Part-11</b>\n🔗 <code>https://mmsvibex.life/tamil-girl-part-11/</code>", card)
        self.assertIn("<b>2. Tamil Girl Sai Part-23</b>\n🔗 <code>https://mmsvibex.life/tamil-girl-part-23/</code>", card)
        # 4. Attached photo albums have unhidden code URLs
        self.assertIn("<blockquote>📸 <b>Attached Photo Albums:</b></blockquote>", card)
        self.assertIn("<b>1. Dance Album 1 (85 photos)</b>\n🔗 <code>https://mmsvibex.life/photos/dance-1/</code>", card)

    @patch("bot.send_post_card", new_callable=AsyncMock)
    @patch("bot.get_mmsvibex_video_details")
    async def test_search_result_number_selection_priority(self, mock_get_details, mock_send_post):
        """Test that typing item number extracts item and takes priority over lingering awaiting_search prompt."""
        from bot import handle_message

        mock_get_details.return_value = {
            "title": "Item 7 Video",
            "post_url": "https://mmsvibex.life/video-7/",
            "streaming_links": ["https://cdn.mmsvibex.fit/7.mp4"],
            "platform_name": "MMSVibex",
            "site": "mmsvibex",
        }

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        context.bot.delete_message = AsyncMock()

        # Both active search results AND lingering awaiting_search='prompt' exist
        context.user_data = {
            "awaiting_search": "prompt",
            "active_search_results": {
                "plat": "vibex",
                "query": "dance",
                "scope_name": "MMSVibex",
                "forum_id": None,
                "page": 1,
                "total_pages": 3,
                "total_count": 30,
                "items": [{"title": f"Video {i}", "url": f"https://mmsvibex.life/video-{i}/"} for i in range(1, 11)],
                "delivered_indices": set(),
                "chat_id": 12345,
                "message_id": 777,
            }
        }

        msg_update = MagicMock()
        msg_update.effective_chat.id = 12345
        msg_update.effective_user.id = 888
        msg_update.message.text = "7"
        msg_update.effective_message = AsyncMock()

        await handle_message(msg_update, context)

        # User's message '7' was deleted
        msg_update.effective_message.delete.assert_called_once()
        # Item 7 was extracted
        mock_get_details.assert_called_once_with("https://mmsvibex.life/video-7/")
        mock_send_post.assert_called_once()
        # Lingering awaiting_search was cleared
        self.assertNotIn("awaiting_search", context.user_data)
        # Search state has item 7 recorded in delivered_indices
        self.assertIn(7, context.user_data["active_search_results"]["delivered_indices"])

    @patch("bot.send_post_card", new_callable=AsyncMock)
    @patch("bot.get_mmsvibex_video_details")
    async def test_search_result_extraction_timeout_handled_gracefully(self, mock_get_details, mock_send_post):
        """Test that network timeout on search result item is handled gracefully and does not crash."""
        from bot import handle_message

        mock_get_details.side_effect = RuntimeError("Read timed out")

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        context.bot.delete_message = AsyncMock()

        context.user_data = {
            "active_search_results": {
                "plat": "vibex",
                "query": "dance",
                "scope_name": "MMSVibex",
                "forum_id": None,
                "page": 1,
                "total_pages": 1,
                "total_count": 1,
                "items": [{"title": "Video 1", "url": "https://mmsvibex.life/video-1/"}],
                "delivered_indices": set(),
                "chat_id": 12345,
                "message_id": 777,
            }
        }

        msg_update = MagicMock()
        msg_update.effective_chat.id = 12345
        msg_update.effective_user.id = 888
        msg_update.message.text = "1"
        msg_update.effective_message = AsyncMock()

        # Should not raise exception
        await handle_message(msg_update, context)
        # Notification was sent regarding the failure
        self.assertTrue(context.bot.send_message.called)

    async def test_sp_choose_lc_handler(self):
        """Test that tapping LiveCam Models in platform picker configures search flow."""
        from bot import callback_query_handler

        context = MagicMock()
        context.user_data = {"awaiting_search": "prompt"}

        update = MagicMock()
        query = AsyncMock()
        query.data = "sp_choose:lc"
        query.message.chat_id = 12345
        query.message.message_id = 888
        update.callback_query = query

        await callback_query_handler(update, context)

        self.assertNotIn("awaiting_search", context.user_data)
        self.assertIn("awaiting_search_flow", context.user_data)
        self.assertEqual(context.user_data["awaiting_search_flow"]["plat"], "lc")
        query.edit_message_text.assert_called_once()

    def test_build_search_platform_keyboard_3_columns(self):
        """Test build_search_platform_keyboard has 3 buttons per row and Back + Cancel."""
        from keyboards import build_search_platform_keyboard

        kb = build_search_platform_keyboard()
        grid = kb.inline_keyboard
        # Row 1: DropMMS, MMSTown, MMSVibex
        self.assertEqual(len(grid[0]), 3)
        self.assertEqual(grid[0][0].callback_data, "sp_choose:fm")
        self.assertEqual(grid[0][1].callback_data, "sp_choose:mmst")
        self.assertEqual(grid[0][2].callback_data, "sp_choose:vibex")

        # Row 2: LiveCam, Omaal63, DesiJugar
        self.assertEqual(len(grid[1]), 3)
        self.assertEqual(grid[1][0].callback_data, "sp_choose:lc")
        self.assertEqual(grid[1][1].callback_data, "sp_wpsite:omaal")
        self.assertEqual(grid[1][2].callback_data, "sp_wpsite:desijugar")

        # Row 3: GulabiHub
        self.assertEqual(len(grid[2]), 1)
        self.assertEqual(grid[2][0].callback_data, "sp_wpsite:gulabi")

        # Row 4: Back, Cancel
        self.assertEqual(len(grid[3]), 2)
        self.assertEqual(grid[3][0].text, "🔙 Back")
        self.assertEqual(grid[3][0].callback_data, "cb_main_menu")
        self.assertEqual(grid[3][1].text, "❌ Cancel")
        self.assertEqual(grid[3][1].callback_data, "sp_cancel")

    async def test_sp_wpsite_hub_callback(self):
        """Test tapping a WordPress site shows the Site Hub card with Search, Newest, Categories, Back, Cancel."""
        from bot import callback_query_handler

        context = MagicMock()
        context.user_data = {}

        update = MagicMock()
        query = AsyncMock()
        query.data = "sp_wpsite:omaal"
        query.message.chat_id = 12345
        query.message.message_id = 999
        update.callback_query = query

        await callback_query_handler(update, context)

        query.edit_message_text.assert_called_once()
        args, kwargs = query.edit_message_text.call_args
        self.assertIn("Omaal63 Hub", args[0])
        reply_markup = kwargs.get("reply_markup")
        btn_data = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        self.assertIn("sp_wpsearch:omaal", btn_data)
        self.assertIn("sp_wplatest:omaal", btn_data)
        self.assertIn("sp_wpcats:omaal", btn_data)
        self.assertIn("cb_search", btn_data)
        self.assertIn("sp_cancel", btn_data)

    @patch("bot.get_wp_categories")
    async def test_sp_wpcats_callback(self, mock_cats):
        """Test tapping Categories fetches live categories and displays them in a grid."""
        from bot import callback_query_handler

        mock_cats.return_value = [
            {"name": "Stripchat Live", "url": "https://omaal63.net/category/stripchat-live/"},
            {"name": "Desi MMS", "url": "https://omaal63.net/category/desi-mms/"},
        ]

        context = MagicMock()
        context.user_data = {}

        update = MagicMock()
        query = AsyncMock()
        query.data = "sp_wpcats:omaal"
        query.message.chat_id = 12345
        query.message.message_id = 999
        update.callback_query = query

        await callback_query_handler(update, context)

        mock_cats.assert_called_once_with("omaal")
        self.assertEqual(query.edit_message_text.call_count, 2)
        args, kwargs = query.edit_message_text.call_args
        self.assertIn("Omaal63 Categories", args[0])
        self.assertIn("Select a category to browse:", args[0])

    @patch("bot.get_wp_listing_posts")
    async def test_sp_wpcat_post_listing_callback(self, mock_listing):
        """Test tapping a specific category displays Option 2 clean numbered post list in blockquote."""
        from bot import callback_query_handler

        mock_listing.return_value = [
            {"title": "Stripchat Video 1", "url": "https://omaal63.net/stripchat-video-1/"},
            {"title": "Stripchat Video 2", "url": "https://omaal63.net/stripchat-video-2/"},
        ]

        context = MagicMock()
        context.user_data = {
            "wpcat_101": {
                "name": "Stripchat Live",
                "url": "https://omaal63.net/category/stripchat-live/",
                "site_key": "omaal",
            }
        }

        update = MagicMock()
        query = AsyncMock()
        query.data = "sp_wpcat:omaal:101"
        query.message.chat_id = 12345
        query.message.message_id = 999
        update.callback_query = query

        await callback_query_handler(update, context)

        query.edit_message_text.assert_called()
        args, kwargs = query.edit_message_text.call_args
        self.assertIn("Stripchat Live", args[0])
        self.assertIn("Stripchat Video 1", args[0])
        self.assertIn("<blockquote>", args[0])
        self.assertIn("active_search_results", context.user_data)
        search_state = context.user_data["active_search_results"]
        self.assertEqual(search_state["plat"], "wp_omaal")
        self.assertTrue(search_state.get("is_category_browse"))


if __name__ == "__main__":
    unittest.main()
