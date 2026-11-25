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
        self.assertEqual(kb.inline_keyboard[1][0].text, "🔙 Back")
        self.assertEqual(kb.inline_keyboard[1][1].text, "❌ Cancel")

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

    def test_new_platforms_registry_resolution(self):
        """Verify default registry resolves engines for all 6 new platforms."""
        from engines.leakedzone import LeakedZoneEngine
        from engines.kvs import KvsEngine
        from engines.thotchicks import ThotChicksEngine
        from engines.mmsdesi import MmsDesiEngine

        # LeakedZone
        e_lz = get_engine_for_url("https://leakedzone.com/jasminesherni/video/22079644")
        self.assertIsInstance(e_lz, LeakedZoneEngine)
        self.assertEqual(e_lz.name, "LeakedZone")

        # X-Video Tube
        e_xv = get_engine_for_url("https://x-video.tube/video/340835/jasmine-sherni/")
        self.assertIsInstance(e_xv, KvsEngine)
        self.assertEqual(e_xv.name, "KVSTube")

        # HornySapiens & ViralXXXPorn
        e_hs = get_engine_for_url("https://hornysapiens.com/videos/304192/jasmine-sherni/")
        self.assertIsInstance(e_hs, KvsEngine)
        e_vx = get_engine_for_url("https://viralxxxporn.com/videos/304192/jasmine-sherni/")
        self.assertIsInstance(e_vx, KvsEngine)

        # ThotChicks
        e_tc = get_engine_for_url("https://thotchicks.com/jasmine-sherni-video/")
        self.assertIsInstance(e_tc, ThotChicksEngine)
        self.assertEqual(e_tc.name, "ThotChicks")

        # MMSDesi
        e_desi = get_engine_for_url("https://www.mmsdesi.me/watch/vandana-pathak-exclusive")
        self.assertIsInstance(e_desi, MmsDesiEngine)
        self.assertEqual(e_desi.name, "MMSDesi")

        # MMSMaza (registered in WordPressLockerEngine)
        e_maza = get_engine_for_url("https://mmsmaza.im/indian-housewife-video/")
        self.assertIsInstance(e_maza, WordPressLockerEngine)
        self.assertEqual(e_maza.name, "WordPressLocker")

    def test_leakedzone_token_crack_and_card_format(self):
        """Test LeakedZone JWPlayer token decoding and post card formatting."""
        from engines.leakedzone import decode_leakedzone_token
        from ui import format_post_card

        # Valid token test: s.slice(16); s.slice(0, -16); atob(s.reverse())
        # Let's craft a token for: https://leakedzone.com/m3u8/test.m3u8
        import base64
        url = "https://leakedzone.com/m3u8/test.m3u8"
        b64_rev = base64.b64encode(url.encode("utf-8")).decode("utf-8")[::-1]
        token = "1234567890123456" + b64_rev + "1234567890123456"

        decoded = decode_leakedzone_token(token)
        self.assertEqual(decoded, url)

        # Post card formatting
        details = {
            "title": "Jasmine Sherni Exclusive Private Session",
            "model_name": "Jasmine Sherni",
            "duration": "14m 28s",
            "date_ist": "2 days ago",
            "streaming_link": "https://stream.leakedzone.com/hls/22079644/master.m3u8",
            "post_url": "https://leakedzone.com/jasminesherni/video/22079644",
            "site": "leakedzone",
        }
        card = format_post_card(details)
        self.assertIn("📌 <b>Title:</b> Jasmine Sherni Exclusive Private Session", card)
        self.assertIn("👤 <b>Model:</b> Jasmine Sherni, LeakedZone", card)
        self.assertIn("⏱️ <b>Duration:</b> 14m 28s  •  📅 <b>Added:</b> 2 days ago", card)
        self.assertIn("🔗 <b>Direct Video Page Link:</b>", card)
        self.assertIn("<code>https://leakedzone.com/jasminesherni/video/22079644</code>", card)
        self.assertNotIn("Source Webpage", card)

    def test_kvs_card_format(self):
        """Test KVS post card formatting for X-Video Tube and HornySapiens."""
        from ui import format_post_card

        # X-Video
        xv_details = {
            "title": "Jasmine Sherni OnlyFans Leaked",
            "model_name": "jasminesherni-onlyfans-leaked",
            "quality": "1080p Full HD",
            "duration": "18m 42s",
            "date_ist": "3 days ago",
            "streaming_link": "https://cdn.x-video.tube/videos/340835/1080p.mp4?validfrom=123",
            "post_url": "https://x-video.tube/video/340835/jasmine-sherni/",
            "site": "xvideotube",
        }
        xv_card = format_post_card(xv_details)
        self.assertIn("📌 <b>Title:</b> Jasmine Sherni OnlyFans Leaked", xv_card)
        self.assertIn("🏷️ <b>Tag:</b> jasminesherni-onlyfans-leaked, X-Video Tube", xv_card)
        self.assertIn("⚡ <b>Quality:</b> 1080p Full HD", xv_card)
        self.assertIn("🔗 <b>Direct Video Page Link:</b>", xv_card)
        self.assertIn("<code>https://x-video.tube/video/340835/jasmine-sherni/</code>", xv_card)
        self.assertNotIn("Source Webpage", xv_card)

        # HornySapiens
        hs_details = {
            "title": "Jasmine Sherni Hardcore",
            "model_name": "Jasmine Sherni",
            "quality": "1080p Full HD",
            "duration": "24m 10s",
            "date_ist": "1 week ago",
            "streaming_link": "https://cdn.hornysapiens.com/get_file/1/video/304192/1080p.mp4",
            "post_url": "https://hornysapiens.com/videos/304192/jasmine-sherni/",
            "site": "hornysapiens",
        }
        hs_card = format_post_card(hs_details)
        self.assertIn("📌 <b>Title:</b> Jasmine Sherni Hardcore", hs_card)
        self.assertIn("👤 <b>Model:</b> Jasmine Sherni, HornySapiens", hs_card)
        self.assertIn("🔗 <b>Direct Video Page Link:</b>", hs_card)
        self.assertIn("<code>https://hornysapiens.com/videos/304192/jasmine-sherni/</code>", hs_card)
        self.assertNotIn("Source Webpage", hs_card)

    def test_thotchicks_card_format(self):
        """Test ThotChicks post card formatting."""
        from ui import format_post_card

        details = {
            "title": "Jasmine Sherni POV Video",
            "actor_name": "Jasmine Sherni",
            "duration": "16m 50s",
            "date_ist": "4 days ago",
            "streaming_link": "https://edge.thotplay.com/hls/live/video_token/playlist.m3u8",
            "post_url": "https://thotchicks.com/jasmine-sherni-pov/",
            "site": "thotchicks",
        }
        card = format_post_card(details)
        self.assertIn("📌 <b>Title:</b> Jasmine Sherni POV Video", card)
        self.assertIn("👤 <b>Actor:</b> Jasmine Sherni, ThotChicks", card)
        self.assertIn("🔗 <b>Direct Video Page Link:</b>", card)
        self.assertIn("<code>https://thotchicks.com/jasmine-sherni-pov/</code>", card)
        self.assertNotIn("Source Webpage", card)

    def test_mmsdesi_card_format(self):
        """Test MMSDesi post card formatting with attached photos."""
        from ui import format_post_card

        # Case 1: with attached photos
        details = {
            "title": "Cute College Girl Viral Hotel MMS Video",
            "category_name": "Desi New",
            "duration": "08m 15s",
            "date_ist": "Today",
            "streaming_link": "https://cdn.mmsdesi.me/media/videos/hotel-mms-720p.mp4",
            "attached_photos": [
                "https://cdn.mmsdesi.me/media/photos/01.jpg",
                "https://cdn.mmsdesi.me/media/photos/02.jpg",
            ],
            "post_url": "https://www.mmsdesi.me/watch/hotel-mms-viral-video",
            "site": "mmsdesi",
        }
        card = format_post_card(details)
        self.assertIn("📌 <b>Title:</b> Cute College Girl Viral Hotel MMS Video", card)
        self.assertIn("📁 <b>Category:</b> Desi New, MMSDesi", card)
        self.assertIn("🔗 <b>Main Direct Video Link:</b>", card)
        self.assertIn("<code>https://cdn.mmsdesi.me/media/videos/hotel-mms-720p.mp4</code>", card)
        self.assertIn("📸 <b>Attached Photo Album (2 Photos):</b>", card)
        self.assertIn("1. <code>https://cdn.mmsdesi.me/media/photos/01.jpg</code>", card)
        self.assertIn("2. <code>https://cdn.mmsdesi.me/media/photos/02.jpg</code>", card)
        self.assertIn('<a href="https://www.mmsdesi.me/watch/hotel-mms-viral-video">Source Webpage</a>', card)

        # Case 2: without photos -> 'Not present'
        details["attached_photos"] = []
        card_no_photo = format_post_card(details)
        self.assertIn("📸 <b>Attached Photo Album:</b> Not present", card_no_photo)

    def test_mmsmaza_card_format_single_link(self):
        """Test MMSMaza delivers only ONE single best streaming mirror link."""
        from ui import format_post_card

        details = {
            "title": "Indian Housewife Viral Bathroom Video",
            "category_name": "Indian Leaks",
            "duration": "11m 30s",
            "date_ist": "Yesterday",
            "streaming_links": [
                "https://shavetape.cash/v/p1lm4vzAwYclGK",
                "https://luluvido.com/ryrvym3ce2c4",
                "https://cloudfam.io/e/8x9q21az",
            ],
            "post_url": "https://mmsmaza.im/indian-housewife-video/",
            "site": "mmsmaza",
        }
        card = format_post_card(details, user_pref="streamtape")
        self.assertIn("📌 <b>Title:</b> Indian Housewife Viral Bathroom Video", card)
        self.assertIn("📂 <b>Category:</b> Indian Leaks, MMSMaza", card)
        self.assertIn("🔗 <b>Streaming Mirror Link:</b>", card)
        self.assertIn("<code>https://shavetape.cash/v/p1lm4vzAwYclGK</code>", card)
        self.assertNotIn("https://luluvido.com", card)
        self.assertNotIn("https://cloudfam.io", card)
        self.assertIn('<a href="https://mmsmaza.im/indian-housewife-video/">Source Webpage</a>', card)

    def test_hub_keyboards_structure(self):
        """Verify Hub Keyboards have Search on top row and follow exact button specs."""
        from handlers.session import set_search_mode
        set_search_mode("model")
        from keyboards import (
            build_leakedzone_hub_keyboard,
            build_xvideo_hub_keyboard,
            build_hornysapiens_hub_keyboard,
            build_thotchicks_hub_keyboard,
            build_mmsdesi_hub_keyboard,
            build_mmsmaza_hub_keyboard,
        )

        # 1. LeakedZone: Search top if no model, or model profile sorting buttons
        lz_hub = build_leakedzone_hub_keyboard("")
        self.assertEqual(lz_hub.inline_keyboard[0][0].text, "🔍 Search Models")
        lz_kb = build_leakedzone_hub_keyboard("jasmine")
        self.assertEqual(len(lz_kb.inline_keyboard[0]), 3)
        self.assertEqual(lz_kb.inline_keyboard[0][0].text, "🆕 Newest")
        self.assertEqual(lz_kb.inline_keyboard[0][1].text, "👁️ Most Viewed")
        self.assertEqual(lz_kb.inline_keyboard[0][2].text, "⏱️ Longest")
        self.assertEqual(lz_kb.inline_keyboard[1][0].text, "🔙 Back")
        self.assertEqual(lz_kb.inline_keyboard[1][1].text, "❌ Cancel")

        # 2. X-Video: Search top if no model, or model profile sorting buttons
        xv_hub = build_xvideo_hub_keyboard("")
        self.assertEqual(xv_hub.inline_keyboard[0][0].text, "🔍 Search Models")
        xv_kb = build_xvideo_hub_keyboard("jasmine")
        self.assertEqual(len(xv_kb.inline_keyboard[0]), 2)
        self.assertEqual(xv_kb.inline_keyboard[0][0].text, "🆕 Latest")
        self.assertEqual(xv_kb.inline_keyboard[0][1].text, "⏱️ Longest")

        # 3. HornySapiens: Search top if no model, or model profile sorting buttons
        hs_hub = build_hornysapiens_hub_keyboard("")
        self.assertEqual(hs_hub.inline_keyboard[0][0].text, "🔍 Search Models")
        hs_kb = build_hornysapiens_hub_keyboard("jasmine")
        self.assertEqual(len(hs_kb.inline_keyboard[0]), 3)

        # 4. ThotChicks: Search top if no actor, or actor profile sorting buttons
        tc_hub = build_thotchicks_hub_keyboard("")
        self.assertEqual(tc_hub.inline_keyboard[0][0].text, "🔍 Search Actors")
        tc_kb = build_thotchicks_hub_keyboard("jasmine")
        self.assertEqual(len(tc_kb.inline_keyboard[0]), 3)

        # 5. MMSDesi: Search top, 4 Categories, Back/Cancel
        desi_kb = build_mmsdesi_hub_keyboard()
        self.assertEqual(desi_kb.inline_keyboard[0][0].text, "🔍 Search Videos")
        self.assertEqual(desi_kb.inline_keyboard[1][0].text, "🔥 Trending")
        self.assertEqual(desi_kb.inline_keyboard[1][1].text, "⚡ Desi New")
        self.assertEqual(desi_kb.inline_keyboard[2][0].text, "📦 Desi Old")
        self.assertEqual(desi_kb.inline_keyboard[2][1].text, "💃 Tango Strip")

        # 6. MMSMaza: Search top, Newest Releases, Categories, Back/Cancel (No Most Viewed or Longest!)
        maza_kb = build_mmsmaza_hub_keyboard()
        self.assertEqual(maza_kb.inline_keyboard[0][0].text, "🔍 Search MMS")
        self.assertEqual(maza_kb.inline_keyboard[1][0].text, "🆕 Newest Releases")
        self.assertEqual(maza_kb.inline_keyboard[1][1].text, "📂 Categories")
        btn_texts = [b.text for row in maza_kb.inline_keyboard for b in row]
        self.assertNotIn("🔥 Most Viewed", btn_texts)
        self.assertNotIn("⏱️ Longest", btn_texts)

    def test_card_keyboard_watch_button_suppression(self):
        """Verify build_card_keyboard suppresses [Watch Video] button for sites 1-4."""
        from keyboards import build_card_keyboard

        # Sites 1-4: strictly NO Watch Video button, only Back and Cancel
        for site_key in ["leakedzone", "xvideotube", "hornysapiens", "thotchicks"]:
            kb = build_card_keyboard({"post_url": "https://example.com/post/123", "site": site_key})
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            self.assertFalse(any("Watch Video" in t for t in all_texts), f"Watch Video button found for {site_key}")
            self.assertEqual(len(kb.inline_keyboard), 1)
            self.assertEqual(kb.inline_keyboard[0][0].text, "🔙 Back")
            self.assertEqual(kb.inline_keyboard[0][1].text, "❌ Cancel")

        # Other platforms: Watch Video button is retained when streaming links are present
        kb_other = build_card_keyboard({
            "post_url": "https://example.com/post/123",
            "site": "omaal",
            "streaming_links": ["https://streamtape.com/v/test12345"],
        })
        all_texts_other = [btn.text for row in kb_other.inline_keyboard for btn in row]
        self.assertTrue(any("Watch Video" in t for t in all_texts_other))

    def test_search_leakedzone_models(self):
        """Test search_leakedzone_models finds profiles via candidate slug and search results."""
        from engines.leakedzone import search_leakedzone_models

        html_content = """
        <html><body>
            <a href="/jasminesherni">Jasmine Sherni</a>
            <a href="/actor/other-model">Other Model</a>
        </body></html>
        """
        with patch("engines.leakedzone._fetch_soup", return_value=BeautifulSoup(html_content, "html.parser")):
            models = search_leakedzone_models("jasmine", limit=5)
            self.assertGreaterEqual(len(models), 1)
            self.assertEqual(models[0]["name"], "Jasmine Sherni")
            self.assertEqual(models[0]["url"], "https://leakedzone.com/jasminesherni")

    def test_search_kvs_models(self):
        """Test search_kvs_models extracts model slugs and strips noise."""
        from engines.kvs import search_kvs_models

        html_content = """
        <html><body>
            <a href="/models/jasmine-sherni/" title="Jasmine Sherni 150k views">Jasmine Sherni 150k views</a>
            <a href="/tags/jasminesherni-onlyfans-leaked/">Jasmine Sherni Leaked</a>
        </body></html>
        """
        with patch("engines.kvs._fetch_soup", return_value=BeautifulSoup(html_content, "html.parser")):
            models = search_kvs_models("hornysapiens", "jasmine", limit=5)
            self.assertGreaterEqual(len(models), 1)
            self.assertEqual(models[0]["slug"], "jasmine-sherni")

    def test_search_thotchicks_actors(self):
        """Test search_thotchicks_actors discovers actor links."""
        from engines.thotchicks import search_thotchicks_actors

        html_content = """
        <html><body>
            <a href="https://thotchicks.com/actor/jasmine-sherni/">Jasmine Sherni</a>
        </body></html>
        """
        with patch("engines.thotchicks._fetch_soup", return_value=BeautifulSoup(html_content, "html.parser")):
            actors = search_thotchicks_actors("jasmine", limit=5)
            self.assertGreaterEqual(len(actors), 1)
            self.assertEqual(actors[0]["slug"], "jasmine-sherni")

    def test_search_mmsdesi_api(self):
        """Test search_mmsdesi queries internal JSON API correctly."""
        from engines.mmsdesi import search_mmsdesi
        import io
        import json

        mock_json = json.dumps({
            "videos": [
                {
                    "title": "College Girl Hotel MMS",
                    "slug": "college-girl-hotel-mms",
                    "category": {"slug": "desi-new"},
                    "thumbnailUrl": "https://cdn.mmsdesi.me/thumb.jpg",
                    "duration": 495,
                    "createdAt": "2026-11-24T12:00:00Z"
                }
            ]
        }).encode("utf-8")

        mock_resp = io.BytesIO(mock_json)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            results = search_mmsdesi("college", page=1, limit=10)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["title"], "College Girl Hotel MMS")
            self.assertEqual(results[0]["url"], "https://www.mmsdesi.me/desi-new/college-girl-hotel-mms")
            self.assertEqual(results[0]["duration"], "08:15")

    def test_mmsmaza_streamtape_mirror_priority(self):
        """Test MMSMaza delivers Streamtape when present, or next available mirror."""
        from ui import format_post_card

        # 1. When Streamtape is present alongside others
        details_with_st = {
            "site": "mmsmaza",
            "title": "Indian Housewife Bathroom Video",
            "category": "Indian Leaks",
            "duration": "08:15",
            "date_ist": "Today",
            "post_url": "https://mmsmaza.im/post-123/",
            "streaming_links": [
                "https://cloudfam.io/e/8x9q21az",
                "https://luluvido.com/ryrvym3ce2c4",
                "https://shavetape.cash/v/p1lm4vzAwYclGK",
            ],
        }
        card_st = format_post_card(details_with_st)
        self.assertIn("https://shavetape.cash/v/p1lm4vzAwYclGK", card_st)
        self.assertNotIn("https://cloudfam.io/e/8x9q21az", card_st)
        self.assertNotIn("https://luluvido.com/ryrvym3ce2c4", card_st)

        # 2. When Streamtape is absent, fall back to next available priority (luluvido/lplaygo)
        details_without_st = {
            "site": "mmsmaza",
            "title": "Indian Housewife Bathroom Video",
            "category": "Indian Leaks",
            "duration": "08:15",
            "date_ist": "Today",
            "post_url": "https://mmsmaza.im/post-123/",
            "streaming_links": [
                "https://cloudfam.io/e/8x9q21az",
                "https://luluvido.com/ryrvym3ce2c4",
            ],
        }
        card_fallback = format_post_card(details_without_st)
        self.assertIn("https://luluvido.com/ryrvym3ce2c4", card_fallback)
        self.assertNotIn("https://cloudfam.io/e/8x9q21az", card_fallback)

    def test_kvs_video_title_ignores_logo_h1(self):
        """Verify KVS video title extraction ignores header logo <h1 class='logo'> and uses real title."""
        from engines.kvs import get_kvs_video_details
        mock_html = """
        <html>
        <head>
            <title>Watch online Jasmine Sherni - 09-18-2024 Video on X-video</title>
            <meta property="og:title" content="Jasmine Sherni - 09-18-2024 Video" />
            <meta property="video:duration" content="20" />
            <meta property="og:image" content="https://x-video.tube/contents/videos_screenshots/640000/640561/preview.jpg" />
        </head>
        <body>
            <h1 class="logo"><a href="https://x-video.tube/">X -VIDEO</a></h1>
            <h1 class="title">Jasmine Sherni - 09-18-2024 Video</h1>
            <script>var video_duration = '20';</script>
        </body>
        </html>
        """
        with patch("engines.kvs._fetch_soup", return_value=BeautifulSoup(mock_html, "html.parser")):
            details = get_kvs_video_details("https://x-video.tube/video/640561/test-video/")
            self.assertEqual(details["title"], "Jasmine Sherni - 09-18-2024 Video")
            self.assertNotEqual(details["title"], "X-VIDEO")
            self.assertNotEqual(details["title"], "X -VIDEO")
            self.assertEqual(details["duration"], "00:20")
            self.assertIn("https://x-video.tube/contents/videos_screenshots/640000/640561/preview.jpg", details["thumbnail_candidates"])

    def test_kvs_listing_ignores_navigation_links(self):
        """Verify get_kvs_listing_items excludes navigation and sorting links like /videos/?by=duration."""
        from engines.kvs import get_kvs_listing_items
        mock_html = """
        <html>
        <body>
            <a href="https://x-video.tube/tags/model/videos/?by=duration">Longest</a>
            <a href="https://x-video.tube/tags/model/videos/?by=post_date">Recent</a>
            <div class="item">
                <a href="https://x-video.tube/video/341006/real-video-clip/" title="Real Video Clip">Real Video Clip</a>
                <span class="duration">05:20</span>
            </div>
        </body>
        </html>
        """
        with patch("engines.kvs._fetch_soup", return_value=BeautifulSoup(mock_html, "html.parser")):
            items = get_kvs_listing_items("https://x-video.tube/tags/model/videos/")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["url"], "https://x-video.tube/video/341006/real-video-clip/")
            self.assertEqual(items[0]["title"], "Real Video Clip")
            self.assertEqual(items[0]["duration"], "05:20")

    def test_post_card_sites_1_to_4_code_block_no_sourcewebpage(self):
        """Verify format_post_card for sites 1-4 uses <code> block and contains no Source Webpage link."""
        from ui import format_post_card
        for site_key in ["leakedzone", "xvideotube", "hornysapiens", "thotchicks"]:
            details = {
                "site": site_key,
                "title": "Model Performance Video",
                "model_name": "Test Star",
                "duration": "03:45",
                "date_ist": "Today",
                "post_url": f"https://{site_key}.com/video/123/",
            }
            card = format_post_card(details)
            self.assertIn(f"<code>https://{site_key}.com/video/123/</code>", card)
            self.assertNotIn("Source Webpage", card)


if __name__ == "__main__":
    unittest.main()
