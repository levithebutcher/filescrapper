# tests/test_engines.py
"""Unit tests for the modular scraper engines and central engine registry."""

import unittest
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup

from engines.base import BaseEngine
from engines.invision import InvisionCommunityEngine
from engines.wordpress import WordPressLockerEngine
from engines.tube import MediaTubeEngine
from engines.livecam import LiveCamEngine
from engines.registry import EngineRegistry, registry, get_engine_for_url


class TestEngines(unittest.TestCase):
    """Test engine resolution and extensible engine registration."""

    def test_default_registry_resolution(self):
        """Verify that default registry resolves correct engine for each supported website."""
        # 1. Invision Community (DropMMS & MMSTown)
        e_dropmms = get_engine_for_url("https://dropmms.com/forum/4-desi/")
        self.assertIsInstance(e_dropmms, InvisionCommunityEngine)
        self.assertEqual(e_dropmms.name, "InvisionCommunity")

        e_mmstown = get_engine_for_url("https://mmstown.com/topic/62375-title/")
        self.assertIsInstance(e_mmstown, InvisionCommunityEngine)

        # 2. WordPress Locker Sites
        for url in [
            "https://omaal63.net/exclusive-post/",
            "https://desijugar.me/2026/11/22/tango-live/",
            "https://gulabihub.com/video-title/",
        ]:
            e_wp = get_engine_for_url(url)
            self.assertIsInstance(e_wp, WordPressLockerEngine)
            self.assertEqual(e_wp.name, "WordPressLocker")

        # 3. Media Tube (MMSVibex)
        e_vibex = get_engine_for_url("https://mmsvibex.life/video-title/")
        self.assertIsInstance(e_vibex, MediaTubeEngine)
        self.assertEqual(e_vibex.name, "MediaTube")

        # 4. LiveCam (LiveCamRips)
        e_lc = get_engine_for_url("https://livecamrips.to/model/36773/GoddessAnna")
        self.assertIsInstance(e_lc, LiveCamEngine)
        self.assertEqual(e_lc.name, "LiveCam")

        # 5. Unsupported URL without fallback returns None
        self.assertIsNone(get_engine_for_url("https://unsupported-site.com/video/123"))

        # 6. Unsupported URL with allow_fallback=True returns UniversalFallbackEngine
        from engines.universal import UniversalFallbackEngine
        e_fallback = get_engine_for_url("https://unsupported-site.com/video/123", allow_fallback=True)
        self.assertIsInstance(e_fallback, UniversalFallbackEngine)
        self.assertEqual(e_fallback.name, "UniversalFallback")

    def test_universal_fallback_extraction(self):
        """Test UniversalFallbackEngine extracts title, thumbnail, and stream links from arbitrary HTML."""
        from engines.universal import get_universal_post_details
        sample_html = """
        <html>
        <head>
            <meta property="og:title" content="Awesome Dance Video" />
            <meta property="og:image" content="https://images.com/thumb.jpg" />
            <meta property="article:published_time" content="2026-11-23T04:00:00Z" />
        </head>
        <body>
            <iframe src="https://streamtape.com/e/abc123xyz"></iframe>
            <video src="https://cdn.example.com/videos/stream.mp4"></video>
        </body>
        </html>
        """
        with patch("engines.universal._fetch_soup", return_value=BeautifulSoup(sample_html, "html.parser")):
            details = get_universal_post_details("https://arbitrary-site.com/clip/456")
            self.assertEqual(details["title"], "Awesome Dance Video")
            self.assertEqual(details["thumbnail"], "https://images.com/thumb.jpg")
            self.assertTrue(any("streamtape.com" in l for l in details["streaming_links"]))
            self.assertTrue(any("stream.mp4" in l for l in details["streaming_links"]))
            self.assertIn("23 Nov 2026", details["date_ist"])

    def test_universal_date_resolver_tiers(self):
        """Verify UniversalDateResolver multi-tier resolution across formats and timeless sites."""
        from engines.base import UniversalDateResolver, IST_TZ
        from datetime import datetime, timezone

        # Tier 1: ISO UTC timestamp conversion to IST
        dt, s = UniversalDateResolver.resolve(raw_date="2026-11-22T18:30:00Z")
        self.assertIsNotNone(dt)
        self.assertIn("23 Nov 2026", s)  # 18:30 UTC is 00:00 (next day) in IST!

        # Tier 2: URL regex
        dt_url, s_url = UniversalDateResolver.resolve(url="https://desijugar.me/2026/11/22/video-clip/")
        self.assertIsNotNone(dt_url)
        self.assertIn("22 Nov 2026", s_url)

        # Tier 4: Fallback to database first_seen for timeless tube sites (like MMSVibex)
        with patch("db.get_or_record_first_seen") as mock_first_seen:
            mock_first_seen.return_value = datetime(2026, 11, 23, 3, 30, tzinfo=timezone.utc)
            dt_db, s_db = UniversalDateResolver.resolve(fallback_db_url="https://mmsvibex.life/timeless-clip/")
            self.assertIsNotNone(dt_db)
            self.assertIn("Discovered: 23 Nov 2026", s_db)

    def test_universal_sort_mappings(self):
        """Verify that each engine provides canonical sort parameter resolutions."""
        from engines.base import UniversalSort

        drop_engine = InvisionCommunityEngine()
        self.assertEqual(drop_engine.get_sort_param(UniversalSort.NEWEST), "start_date")
        self.assertEqual(drop_engine.get_sort_param(UniversalSort.MOST_VIEWED), "views")

        tube_engine = MediaTubeEngine()
        self.assertEqual(tube_engine.get_sort_param(UniversalSort.NEWEST), "latest")
        self.assertEqual(tube_engine.get_sort_param(UniversalSort.MOST_VIEWED), "most-viewed")
        self.assertEqual(tube_engine.get_sort_param(UniversalSort.POPULAR), "popular")
        self.assertEqual(tube_engine.get_sort_param(UniversalSort.LONGEST), "longest")

        lc_engine = LiveCamEngine()
        self.assertEqual(lc_engine.get_sort_param(UniversalSort.NEWEST), "newest")
        self.assertEqual(lc_engine.get_sort_param(UniversalSort.MOST_VIEWED), "most_viewed")

    def test_search_forum_advanced(self):
        """Test search_forum_advanced extracts total count, pages, and structured items."""
        from engines.invision import search_forum_advanced
        sample_search_html = """
        <html>
        <body>
            <h1 class="ipsType_pageTitle">Found 36 results for 'dance'</h1>
            <ul class="ipsPagination" data-pages="4"></ul>
            <ol class="ipsStream">
                <li class="ipsStreamItem">
                    <h2 class="ipsStreamItem_title"><a href="https://dropmms.com/topic/101-dance-clip/">Dance Clip 1</a></h2>
                </li>
                <li class="ipsStreamItem">
                    <h2 class="ipsStreamItem_title"><a href="https://dropmms.com/topic/102-dance-solo/">Dance Solo 2</a></h2>
                </li>
            </ol>
        </body>
        </html>
        """
        with patch("engines.invision._fetch_soup", return_value=BeautifulSoup(sample_search_html, "html.parser")):
            res = search_forum_advanced("dance", page=1, limit=5)
            self.assertEqual(res["total_count"], 36)
            self.assertEqual(res["total_pages"], 4)
            self.assertEqual(len(res["topics"]), 2)
            self.assertEqual(res["topics"][0]["title"], "Dance Clip 1")
            self.assertEqual(res["topics"][0]["url"], "https://dropmms.com/topic/101-dance-clip/")

    def test_dynamic_engine_registration_and_extensibility(self):
        """Verify how easily a new website (e.g. abcd.com) can be registered into the registry."""
        custom_registry = EngineRegistry()

        # Define or instantiate engine for a new website (e.g. abcd.com)
        class CustomAbcdEngine(BaseEngine):
            name = "AbcdEngine"
            domains = ["abcd.com", "sub.abcd.org"]

            def is_listing_url(self, url: str) -> bool:
                return "/category/" in url

            def is_detail_url(self, url: str) -> bool:
                return "/post/" in url

            def get_details(self, url: str) -> dict:
                return {"title": "ABCD Post", "url": url}

        abcd_engine = CustomAbcdEngine()
        custom_registry.register(abcd_engine)

        # Check resolution
        resolved = custom_registry.get_engine_for_url("https://abcd.com/post/999-sample/")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, "AbcdEngine")
        self.assertTrue(resolved.is_detail_url("https://abcd.com/post/999-sample/"))
        self.assertTrue(resolved.is_listing_url("https://abcd.com/category/desi/"))

        details = resolved.get_details("https://abcd.com/post/999-sample/")
        self.assertEqual(details["title"], "ABCD Post")

        # Check supported domains list
        self.assertIn("abcd.com", custom_registry.supported_domains())
        self.assertIn("sub.abcd.org", custom_registry.supported_domains())

    def test_parse_relative_to_ist(self):
        """Test relative time parsing into IST datetimes."""
        from engines.base import parse_relative_to_ist, parse_to_ist

        # Just now
        dt_now = parse_relative_to_ist("just now")
        self.assertIsNotNone(dt_now)

        # 2 hours ago
        dt_2h = parse_relative_to_ist("2 hours ago")
        self.assertIsNotNone(dt_2h)

        # 15 mins ago
        dt_15m = parse_relative_to_ist("15 mins ago")
        self.assertIsNotNone(dt_15m)

        # Yesterday
        dt_yest = parse_relative_to_ist("yesterday at 10:30 pm")
        self.assertIsNotNone(dt_yest)
        self.assertEqual(dt_yest.hour, 22)
        self.assertEqual(dt_yest.minute, 30)

        # parse_to_ist fallback
        dt_fallback = parse_to_ist("4 hours ago")
        self.assertIsNotNone(dt_fallback)

    def test_universal_card_formatting_and_keyboard(self):
        """Test Universal Card layout and interactive action buttons."""
        from bot import format_post_card, build_card_keyboard

        details = {
            "title": "Universal Sample Video",
            "post_url": "https://dropmms.com/topic/555-sample/",
            "tags": ["1080p", "HD"],
            "date_ist": "23 Nov 2026, 10:30 AM IST",
            "platform_name": "DropMMS",
            "category_name": "Desi Videos",
            "duration": "14:20",
            "streaming_links": ["https://streamtape.com/e/abc12345"],
        }
        card = format_post_card(details, user_pref="streamtape")
        self.assertIn("<blockquote>🎬 <b>Universal Sample Video</b>", card)
        self.assertIn("⏱️ <b>Duration:</b> 14:20</blockquote>", card)
        self.assertIn("🏷️ <code>#1080p</code> <code>#HD</code>", card)
        self.assertIn("📅 <b>Date:</b> 23 Nov 2026, 10:30 AM IST", card)
        self.assertIn("🏛️ <b>Platform:</b> DropMMS", card)
        self.assertIn("📁 <b>Category:</b> Desi Videos", card)
        self.assertIn("⏱️ <b>Duration:</b> 14:20", card)
        self.assertIn("🎬 Streamtape Links:", card)
        self.assertIn("<code>https://streamtape.com/e/abc12345</code>", card)

        kb = build_card_keyboard(details, user_pref="streamtape")
        self.assertEqual(kb.inline_keyboard[0][0].text, "🎬 Watch Video")
        self.assertEqual(kb.inline_keyboard[0][0].url, "https://streamtape.com/e/abc12345")
        self.assertEqual(kb.inline_keyboard[1][0].text, "🔍 Search Again")
        self.assertEqual(kb.inline_keyboard[1][1].text, "🏛️ Main Menu")

    def test_platform_metadata_in_invision_and_wordpress(self):
        """Verify platform_name is automatically attached in engine post details."""
        from engines.invision import get_post_details
        from engines.wordpress import get_wp_post_details

        inv_html = "<html><body><h1>Dance Post</h1><article class='cPost'><time datetime='2026-11-23T05:00:00Z'>Earlier</time></article></body></html>"
        with patch("engines.invision._fetch_soup", return_value=BeautifulSoup(inv_html, "html.parser")):
            res = get_post_details("https://mmstown.com/topic/999-dance/")
            self.assertEqual(res["platform_name"], "MMSTown")
            self.assertIsNotNone(res["date_ist"])

        wp_html = "<html><body><h1>WP Locker Video</h1><time class='entry-date'>2026-11-23T04:00:00Z</time></body></html>"
        with patch("engines.wordpress._fetch_soup", return_value=BeautifulSoup(wp_html, "html.parser")):
            res_wp = get_wp_post_details("https://desijugar.me/2026/11/23/dance-video/")
            self.assertEqual(res_wp["platform_name"], "DesiJugar")
            self.assertIsNotNone(res_wp["date_ist"])

    def test_category_cards_and_clean_keyboards(self):
        """Verify forum category prompt card, completion card, and clean keyboards."""
        from ui import format_category_options_card, format_category_completion_card
        from keyboards import build_category_options_keyboard

        opt_card = format_category_options_card("Desi Sex", "1075 Topics", "start_date")
        self.assertIn("💬 <b>Desi Sex</b>", opt_card)
        self.assertIn("📊 <b>Total Topics:</b> 1075 Topics", opt_card)
        self.assertIn("🎯 <b>Sort:</b> Upload Date (Start Date)", opt_card)
        self.assertIn("⚡ <b>Quick Filter by Date (IST):</b>", opt_card)
        self.assertIn("✏️ <b>Or Enter Custom Range, Count or Page:</b>", opt_card)

        comp_card = format_category_completion_card(5, "Desi Sex", "1075 Topics", "start_date")
        self.assertIn("<blockquote>✅ <b>Extraction Complete!</b>\n📁 Delivered: <b>5</b> topic(s)</blockquote>", comp_card)
        self.assertIn("💬 <b>Desi Sex</b>", comp_card)

        kb = build_category_options_keyboard(42, "start_date")
        btn_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("sp_cdate:42:start_date:today", btn_data)
        self.assertIn("sp_cdate:42:start_date:yesterday", btn_data)
        self.assertIn("sp_cat:42", btn_data)
        self.assertIn("sp_cancel", btn_data)

    def test_get_wp_listing_posts_search_query_preservation(self):
        """Verify get_wp_listing_posts preserves search query ?s=... on page 1 and page 2+."""
        from engines.wordpress import get_wp_listing_posts

        html_content = """
        <html><body>
        <article class="post">
            <header class="entry-header">
                <h2 class="entry-title"><a href="https://omaal63.net/aditi-post/">Aditi Viral MMS</a></h2>
            </header>
            <img src="https://omaal63.net/thumb.jpg"/>
        </article>
        </body></html>
        """
        soup = BeautifulSoup(html_content, "html.parser")
        with patch("engines.wordpress._fetch_soup", return_value=soup) as mock_fetch:
            res = get_wp_listing_posts("https://omaal63.net/?s=Aditi", page=1, limit=10)
            mock_fetch.assert_called_with("https://omaal63.net/?s=Aditi")
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["title"], "Aditi Viral MMS")
            self.assertEqual(res[0]["url"], "https://omaal63.net/aditi-post/")

        with patch("engines.wordpress._fetch_soup", return_value=soup) as mock_fetch:
            res_p2 = get_wp_listing_posts("https://omaal63.net/?s=Aditi", page=2, limit=10)
            mock_fetch.assert_called_with("https://omaal63.net/page/2/?s=Aditi")
            self.assertEqual(len(res_p2), 1)


if __name__ == "__main__":
    unittest.main()
