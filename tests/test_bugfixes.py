# tests/test_bugfixes.py
"""
Unit tests verifying fixes for command access controls, state collisions,
pagination routing, callback handlers, and URL detection.
"""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch

import db
import bot  # noqa: F401 - ensures `bot` module attributes resolve cleanly in handlers


class TestBugFixes(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def tearDown(self):
        from handlers.session import end_scrape_for_chat
        end_scrape_for_chat(12345)
        end_scrape_for_chat(99881)

    async def test_channels_command_owner_type_and_db_call(self):
        """Ensure /channels handles string OWNER_ID against int user IDs and calls db.get_all_active_channels."""
        from handlers.commands import channels_command

        update = MagicMock()
        update.effective_user.id = 123456
        update.effective_message = AsyncMock()
        context = MagicMock()

        sample_channels = [{"channel_id": -100123, "title": "Updates Feed"}]
        with patch("handlers.commands.OWNER_ID", "123456"), \
             patch("handlers.commands.db.get_all_active_channels", return_value=sample_channels) as mock_get:
            await channels_command(update, context)
            mock_get.assert_called_once()
            reply_text = update.effective_message.reply_text.call_args[0][0]
            self.assertIn("Updates Feed", reply_text)
            self.assertNotIn("restricted", reply_text.lower())

        update_other = MagicMock()
        update_other.effective_user.id = 999999
        update_other.effective_message = AsyncMock()
        with patch("handlers.commands.OWNER_ID", "123456"):
            await channels_command(update_other, context)
            reply_text = update_other.effective_message.reply_text.call_args[0][0]
            self.assertIn("restricted", reply_text.lower())

    async def test_cleanup_ephemeral_progress_int_and_message(self):
        """Ensure cleanup_ephemeral_progress supports both integer message IDs and Message objects."""
        from handlers.commands import cleanup_ephemeral_progress

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.delete_message = AsyncMock()
        context.user_data = {"active_progress_msg_12345": 777}

        await cleanup_ephemeral_progress(context, 12345)
        context.bot.delete_message.assert_awaited_once_with(chat_id=12345, message_id=777)
        self.assertNotIn("active_progress_msg_12345", context.user_data)

        msg_obj = AsyncMock()
        context.user_data = {"active_progress_msg_12345": msg_obj}
        await cleanup_ephemeral_progress(context, 12345)
        msg_obj.delete.assert_awaited_once()

    async def test_stop_command_clears_pending_prompts(self):
        """Ensure /stop clears all interactive range and search prompt states."""
        from handlers.commands import stop_command

        update = MagicMock()
        update.effective_chat.id = 99881
        update.effective_message = AsyncMock()
        context = MagicMock()
        context.bot = MagicMock()
        context.user_data = {
            "awaiting_search_flow": {"plat": "fm"},
            "awaiting_search": "fm",
            "awaiting_model_range": {"url": "https://example.com/m"},
            "awaiting_category_range": {"url": "https://example.com/c"},
            "awaiting_vibex_range": {"url": "https://example.com/v"},
            "awaiting_wp_range": {"url": "https://example.com/w"},
        }

        await stop_command(update, context)
        self.assertEqual(context.user_data, {})

    def test_search_forum_accepts_page_and_guards_positional_int(self):
        """Verify search_forum accepts page parameter and recovers cleanly from legacy 3-int positional args."""
        from engines.invision import search_forum

        with patch("engines.invision.search_forum_advanced", return_value={"topics": [{"title": "T1"}]}) as mock_adv:
            res = search_forum("alpha", limit=4, page=3)
            self.assertEqual(len(res), 1)
            self.assertEqual(mock_adv.call_args.kwargs["page"], 3)
            self.assertEqual(mock_adv.call_args.kwargs["limit"], 4)

            # Positional (query, page, limit) where base_url receives an int
            res2 = search_forum("alpha", 2, 5)
            self.assertEqual(len(res2), 1)
            self.assertEqual(mock_adv.call_args.kwargs["page"], 2)
            self.assertEqual(mock_adv.call_args.kwargs["limit"], 5)

    async def test_global_search_forwards_page_to_forum_search(self):
        """Verify federated search forwards the requested page number to forum search."""
        from handlers.global_search import execute_global_search

        with patch("handlers.global_search.search_kvs", return_value=[]), \
             patch("handlers.global_search.search_leakedzone", return_value=[]), \
             patch("handlers.global_search.search_thotchicks", return_value=[]), \
             patch("handlers.global_search.get_wp_listing_posts", return_value=[]), \
             patch("handlers.global_search.search_mmsdesi", return_value=[]), \
             patch("handlers.global_search.search_mmsvibex", return_value=[]), \
             patch("handlers.global_search.search_forum", return_value=[]) as mock_forum:
            await execute_global_search("sample", page=4, limit_per_engine=5)
            mock_forum.assert_called_once()
            self.assertEqual(mock_forum.call_args.kwargs["page"], 4)
            self.assertEqual(mock_forum.call_args.kwargs["limit"], 5)

    async def test_range_prompt_not_hijacked_by_stale_search_results(self):
        """Verify numeric range input routes to awaiting_model_range when active_search_results also exists."""
        from handlers.messages_handler import handle_message

        context = MagicMock()
        context.bot = MagicMock()
        context.bot.edit_message_text = AsyncMock(return_value=MagicMock(message_id=501))
        context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=502))
        context.user_data = {
            "active_search_results": {
                "plat": "vibex",
                "items": [{"title": "Item 1", "url": "https://mmsvibex.life/item-1/"}],
            },
            "awaiting_model_range": {
                "short_id": 10,
                "url": "https://livecamrips.to/model/10/Creator",
                "model_name": "Creator",
                "total_str": "20",
                "sort_by": "newest",
                "chat_id": 12345,
                "message_id": 500,
            },
        }

        update = MagicMock()
        update.effective_chat.id = 12345
        update.effective_user.id = 77
        update.message.text = "1-5"
        update.effective_message = AsyncMock()

        with patch("bot.run_livecam_model_scrape", new_callable=AsyncMock) as mock_model_scrape:
            await handle_message(update, context)
            mock_model_scrape.assert_awaited_once()
            self.assertEqual(mock_model_scrape.call_args.kwargs["start_idx"], 1)
            self.assertEqual(mock_model_scrape.call_args.kwargs["end_idx"], 5)
            self.assertNotIn("awaiting_model_range", context.user_data)

    async def test_vibex_and_wp_page_input_forwards_page_num(self):
        """Verify `page N` text input forwards page_num into tube and archive listing workers."""
        from handlers.messages_handler import handle_message
        from handlers.scrapers import run_mmsvibex_listing_scrape, run_wp_listing_scrape

        # 1. Text router forwards page_num=2 for tube listing
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.edit_message_text = AsyncMock(return_value=MagicMock(message_id=601))
        context.user_data = {
            "awaiting_vibex_range": {
                "url": "https://mmsvibex.life/?filter=latest",
                "sort_key": "latest",
                "sort_label": "Latest",
                "chat_id": 12345,
                "message_id": 600,
            }
        }
        update = MagicMock()
        update.effective_chat.id = 12345
        update.effective_user.id = 77
        update.message.text = "page 2"
        update.effective_message = AsyncMock()

        with patch("bot.run_mmsvibex_listing_scrape", new_callable=AsyncMock) as mock_v:
            await handle_message(update, context)
            self.assertEqual(mock_v.call_args.kwargs["page_num"], 2)

        # 2. Worker passes page=2 into engine function
        status_msg = AsyncMock()
        status_msg.message_id = 602
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(return_value=MagicMock(message_id=603))
        with patch("bot.get_mmsvibex_listing_items", return_value=[]) as mock_items:
            await run_mmsvibex_listing_scrape(
                bot=bot_mock,
                chat_id=12345,
                target_url="https://mmsvibex.life/?filter=latest",
                page_num=2,
                status_msg=status_msg,
                context=context,
            )
            self.assertEqual(mock_items.call_args.kwargs["page"], 2)

        # 3. WP worker passes page=3 into engine function
        with patch("bot.get_wp_listing_posts", return_value=[]) as mock_posts:
            await run_wp_listing_scrape(
                bot=bot_mock,
                chat_id=12345,
                target_url="https://desijugar.me/",
                page_num=3,
                status_msg=status_msg,
                context=context,
            )
            self.assertEqual(mock_posts.call_args.kwargs["page"], 3)

    async def test_wp_mmsmaza_mapping_and_empty_page_loop_guard(self):
        """Verify WP category map includes all 4 sites and empty subsequent page resets total_pages cleanly."""
        from handlers.callbacks import callback_query_handler

        context = MagicMock()
        context.user_data = {
            "wpcat_201": {
                "name": "Featured",
                "url": "https://mmsmaza.im/category/featured/",
                "site_key": "mmsmaza",
            }
        }

        # Page 1 load for mmsmaza
        query1 = AsyncMock()
        query1.data = "sp_wpcat:mmsmaza:201"
        query1.message.chat_id = 12345
        query1.message.message_id = 800
        update1 = MagicMock(callback_query=query1)

        with patch("bot.get_wp_listing_posts", return_value=[{"title": "Post 1", "url": "https://mmsmaza.im/p1/"}]):
            await callback_query_handler(update1, context)
            rendered = query1.edit_message_text.call_args[0][0]
            self.assertIn("MMSMaza", rendered)

        # Empty page 2 fallback sets total_pages=1 instead of bouncing Page 1 <-> Page 2
        query2 = AsyncMock()
        query2.data = "sp_wppag_cat:mmsmaza:201:2"
        query2.message.chat_id = 12345
        query2.message.message_id = 800
        update2 = MagicMock(callback_query=query2)

        ten_items = [{"title": f"Post {i}", "url": f"https://mmsmaza.im/p{i}/"} for i in range(10)]
        with patch("bot.get_wp_listing_posts", side_effect=[[], ten_items]):
            await callback_query_handler(update2, context)
            state = context.user_data["active_search_results"]
            self.assertEqual(state["page"], 1)
            self.assertEqual(state["total_pages"], 1)

    async def test_cancel_before_single_sc_does_not_drop_request(self):
        """Verify prior /stop does not silently drop subsequent single item sc_ or mv_opt normal triggers."""
        from handlers.session import cancel_scrape_for_chat, is_scrape_cancelled
        from handlers.callbacks import callback_query_handler

        sid = db.get_or_create_short_id("https://dropmms.com/topic/999-demo/")
        cancel_scrape_for_chat(12345)
        self.assertTrue(is_scrape_cancelled(12345))

        query = AsyncMock()
        query.data = f"sc_{sid}"
        query.message.chat_id = 12345
        query.from_user.id = 88
        update = MagicMock(callback_query=query)
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.user_data = {}

        with patch("bot.process_topic_scrape", new_callable=AsyncMock) as mock_proc:
            await callback_query_handler(update, context)
            mock_proc.assert_awaited_once()
        self.assertFalse(is_scrape_cancelled(12345))

    async def test_callback_edge_cases_sp_p_and_sp_noop_and_channel_rm(self):
        """Verify 4-part sp_p callbacks, sp_noop, and cb_channel_rm execute without ValueError or unhandled fallthrough."""
        from handlers.callbacks import callback_query_handler

        context = MagicMock()
        context.user_data = {}

        # 4-part sp_p
        q1 = AsyncMock()
        q1.data = "sp_p:fm:demo_query:2"
        q1.message.chat_id = 12345
        with patch("bot.execute_platform_search", new_callable=AsyncMock) as mock_exec:
            await callback_query_handler(MagicMock(callback_query=q1), context)
            mock_exec.assert_awaited_once()
            self.assertEqual(mock_exec.call_args.args[2], "fm")
            self.assertEqual(mock_exec.call_args.args[3], "demo_query")
            self.assertEqual(mock_exec.call_args.kwargs["page"], 2)

        # sp_noop
        q2 = AsyncMock()
        q2.data = "sp_noop"
        await callback_query_handler(MagicMock(callback_query=q2), context)
        q2.answer.assert_awaited()

        # cb_channel_rm
        q3 = AsyncMock()
        q3.data = "cb_channel_rm"
        with patch("handlers.callbacks.db.get_all_active_channels", return_value=[{"channel_id": -10055, "title": "Ch1"}]):
            await callback_query_handler(MagicMock(callback_query=q3), context)
            rm_markup = q3.edit_message_text.call_args.kwargs["reply_markup"]
            btn_cbs = [b.callback_data for row in rm_markup.inline_keyboard for b in row]
            self.assertIn("unlink_-10055", btn_cbs)

    async def test_raw_url_kvs_listing_slug_and_schemeless_domains(self):
        """Verify KVS listing URL ending with /videos/ extracts real slug and parse_slicing_args recognizes all domains."""
        from handlers.raw_url import handle_raw_url
        from engines.base import parse_slicing_args, SUPPORTED_SITE_DOMAINS

        for dom in SUPPORTED_SITE_DOMAINS:
            u, _, _, _ = parse_slicing_args([f"{dom}/sample-path/"])
            self.assertEqual(u, f"{dom}/sample-path/")

        update = MagicMock()
        msg = AsyncMock()
        msg.chat_id = 12345
        update.effective_message = msg
        update.effective_user.id = 99
        context = MagicMock()
        context.bot = MagicMock()
        context.user_data = {}

        # Also verify individual video URLs are not misclassified as listings
        from engines.kvs import is_kvs_video_url, is_kvs_listing_url
        self.assertTrue(is_kvs_video_url("https://x-video.tube/video/12345/sample-clip/"))
        self.assertTrue(is_kvs_listing_url("https://x-video.tube/tags/sample-creator-archive/videos/"))
        self.assertFalse(is_kvs_video_url("https://x-video.tube/tags/sample-creator-archive/videos/"))

        await handle_raw_url(update, context, "https://x-video.tube/tags/sample-creator-archive/videos/")
        rendered_text = msg.reply_text.call_args[0][0]
        self.assertIn("Sample Creator Archive", rendered_text)
        self.assertNotIn(": Videos<", rendered_text)

    async def test_send_livecam_card_detached_photo_over_1024(self):
        """Verify send_livecam_card sends detached thumbnail photo even when caption exceeds 1024 chars."""
        from handlers.delivery import send_livecam_card

        bot_mock = MagicMock()
        bot_mock.send_photo = AsyncMock()
        bot_mock.send_message = AsyncMock()

        long_title = "Live Stream Event " * 80
        details = {
            "title": long_title,
            "model_name": "Creator",
            "video_url": "https://livecamrips.to/video/123",
            "streaming_links": ["https://streamtape.com/e/abc123"],
            "thumbnail": "https://livecamrips.to/thumb.jpg",
        }
        with patch("handlers.delivery.download_image_bytes", return_value=b"fake_jpg_bytes"):
            await send_livecam_card(bot_mock, 12345, details)
            bot_mock.send_photo.assert_awaited_once()
            bot_mock.send_message.assert_awaited_once()

    async def test_engine_search_methods_forward_page_and_encode(self):
        """Verify MediaTubeEngine and WordPressLockerEngine forward page and quote_plus search queries."""
        from engines.tube import MediaTubeEngine
        from engines.wordpress import WordPressLockerEngine

        with patch("engines.tube.search_mmsvibex", return_value=[]) as mock_v:
            MediaTubeEngine().search("alpha beta", limit=5, page=3)
            self.assertEqual(mock_v.call_args.kwargs["page"], 3)

        with patch("engines.wordpress.get_wp_listing_posts", return_value=[]) as mock_wp:
            WordPressLockerEngine().search("alpha beta", limit=7, page=2)
            self.assertIn("?s=alpha+beta", mock_wp.call_args.args[0])
            self.assertEqual(mock_wp.call_args.kwargs["page"], 2)

    async def test_feed_setchannel_handles_none_title(self):
        """Verify /setchannel does not crash if chat.title is None."""
        from handlers.feed import setchannel_command

        update = MagicMock()
        update.effective_chat.id = -100777
        update.effective_chat.type = "channel"
        update.effective_chat.title = None
        update.effective_chat.username = None
        update.effective_user.id = 42
        update.effective_message = AsyncMock()
        context = MagicMock()
        context.args = []

        with patch("handlers.feed.db.add_or_update_channel", return_value=True):
            await setchannel_command(update, context)
            update.effective_message.reply_text.assert_awaited_once()

    def test_leakedzone_listing_card_extracts_clean_title_and_duration(self):
        """Verify listing card parser separates glued duration and metadata from video titles."""
        from bs4 import BeautifulSoup
        from engines.leakedzone import get_leakedzone_model_videos

        sample_html = """
        <html><body>
            <div class="card">
                <a href="/samplecreator/video/22079644">
                    <img src="/storage/thumb.webp"/>02:06Sample Clip Title@samplecreator · #22079644 · 846 views · 1 year ago
                </a>
            </div>
        </body></html>
        """
        with patch("engines.leakedzone._fetch_soup", return_value=BeautifulSoup(sample_html, "html.parser")):
            items = get_leakedzone_model_videos("samplecreator", limit=5)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "Sample Clip Title")
            self.assertEqual(items[0]["duration"], "02:06")

    async def test_delivery_chunks_messages_over_4096(self):
        """Verify send_post_card splits captions over Telegram 4096-char limit without losing markup."""
        from handlers.delivery import send_post_card
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton

        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock()
        links = [f"https://streamtape.com/e/part_{i:02d}_" + ("x" * 55) for i in range(60)]
        details = {
            "title": "Multi Link Collection",
            "post_url": "https://dropmms.com/topic/1-collection/",
            "streaming_links": links,
        }
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="cb_search")]])

        await send_post_card(bot_mock, 12345, details, reply_markup=markup)
        self.assertGreater(bot_mock.send_message.await_count, 1)
        calls = bot_mock.send_message.await_args_list
        for idx, c in enumerate(calls):
            self.assertLessEqual(len(c.kwargs["text"]), 4096)
            if idx < len(calls) - 1:
                self.assertIsNone(c.kwargs.get("reply_markup"))
            else:
                self.assertIs(c.kwargs.get("reply_markup"), markup)

    async def test_livecam_scrape_sends_single_stop_notification(self):
        """Verify mid-scrape cancellation sends only one Scraping stopped notification card."""
        from handlers.scrapers import run_livecam_model_scrape
        from handlers.session import cancel_scrape_for_chat

        status_msg = AsyncMock()
        status_msg.message_id = 900
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(return_value=MagicMock(message_id=901))
        videos = [
            {"title": "V1", "video_url": "https://livecamrips.to/video/1"},
            {"title": "V2", "video_url": "https://livecamrips.to/video/2"},
        ]

        async def _proc_cancel(b, cid, v, user_id=None):
            cancel_scrape_for_chat(cid)

        with patch("bot.get_livecam_model_videos", return_value=videos), \
             patch("bot.process_livecam_scrape", side_effect=_proc_cancel):
            await run_livecam_model_scrape(
                bot=bot_mock,
                chat_id=12345,
                target_url="https://livecamrips.to/model/1/Creator",
                status_msg=status_msg,
            )

        stop_msgs = [
            c.kwargs["text"]
            for c in bot_mock.send_message.await_args_list
            if "Scraping stopped!" in c.kwargs.get("text", "")
        ]
        self.assertEqual(len(stop_msgs), 1)
        self.assertIn("Delivered: <b>0</b>", stop_msgs[0])


if __name__ == "__main__":
    unittest.main()
