# tests/test_global_search.py
"""
Unit tests for Global Multi-Platform Federated Search and Deduplication.
"""

import unittest
from handlers.global_search import (
    normalize_title,
    parse_duration_seconds,
    is_duplicate_video,
    deduplicate_and_merge_results,
)


class TestGlobalSearch(unittest.TestCase):
    def test_normalize_title(self):
        t1 = "Jasmine Sherni - Leaked OnlyFans Video 1080p HD"
        norm1 = normalize_title(t1)
        self.assertIn("jasmine", norm1)
        self.assertIn("sherni", norm1)
        self.assertNotIn("onlyfans", norm1)
        self.assertNotIn("1080p", norm1)

    def test_parse_duration_seconds(self):
        self.assertEqual(parse_duration_seconds("05:30"), 330)
        self.assertEqual(parse_duration_seconds("12m 45s"), 765)
        self.assertEqual(parse_duration_seconds("01:00:10"), 3610)
        self.assertIsNone(parse_duration_seconds(None))
        self.assertIsNone(parse_duration_seconds("N/A"))

    def test_is_duplicate_video_with_duration(self):
        v1 = {
            "title": "Jasmine Sherni OnlyFans Leaked HD",
            "duration": "05:30",
            "url": "https://x-video.tube/video/123",
        }
        v2 = {
            "title": "Jasmine Sherni Onlyfans Viral Video",
            "duration": "05:34",
            "url": "https://hornysapiens.com/videos/456",
        }
        self.assertTrue(is_duplicate_video(v1, v2))

    def test_is_not_duplicate_different_videos(self):
        v1 = {
            "title": "Jasmine Sherni Shower Clip",
            "duration": "02:10",
            "url": "https://x-video.tube/video/1",
        }
        v2 = {
            "title": "Ananya Pandey Viral MMS",
            "duration": "02:10",
            "url": "https://mmsmaza.com/video/2",
        }
        self.assertFalse(is_duplicate_video(v1, v2))

    def test_deduplicate_and_merge_results(self):
        raw = [
            {
                "title": "Jasmine Sherni OnlyFans Leaked",
                "duration": "05:30",
                "platform_name": "X-Video Tube",
                "url": "https://x-video.tube/video/123",
            },
            {
                "title": "Jasmine Sherni OnlyFans Video",
                "duration": "05:32",
                "platform_name": "HornySapiens",
                "url": "https://hornysapiens.com/videos/456",
            },
            {
                "title": "Diana Estrada Dance Clip",
                "duration": "03:15",
                "platform_name": "LeakedZone",
                "url": "https://leakedzone.com/video/789",
            },
        ]
        merged = deduplicate_and_merge_results(raw)
        self.assertEqual(len(merged), 2)
        # Check that the first item merged mirrors
        self.assertEqual(len(merged[0]["mirrors"]), 2)
        mirror_plats = [m["platform"] for m in merged[0]["mirrors"]]
        self.assertIn("X-Video Tube", mirror_plats)
        self.assertIn("HornySapiens", mirror_plats)

    def test_kvs_model_search_deduplication(self):
        """Test KVS model candidate probing strictly deduplicates buttons with identical names."""
        from unittest.mock import patch
        from bs4 import BeautifulSoup
        from engines.kvs import search_kvs_models

        mock_soup = BeautifulSoup("""
        <html>
        <head><title>Jasmine Sherni - Videos</title></head>
        <body>
            <a href="/video/123/clip-1/">Video 1</a>
        </body>
        </html>
        """, "html.parser")

        with patch("engines.kvs._fetch_soup", return_value=mock_soup):
            models = search_kvs_models("xvideotube", "Jasmine Sherni", limit=10)
            names = [m["name"] for m in models]
            # Ensure no duplicate names exist in model selection buttons
            self.assertEqual(len(names), len(set(names)))
            # Ensure official model profile is prioritized first
            self.assertEqual(models[0]["name"], "Jasmine Sherni")
            self.assertEqual(models[0]["url"], "https://x-video.tube/models/jasmine-sherni/")

    def test_search_mode_persistence(self):
        """Test search mode is saved in db and retained across calls."""
        from handlers.session import set_search_mode, get_search_mode
        import db

        set_search_mode("video")
        self.assertEqual(get_search_mode(), "video")
        self.assertEqual(db.get_setting("search_mode"), "video")

        set_search_mode("model")
        self.assertEqual(get_search_mode(), "model")
        self.assertEqual(db.get_setting("search_mode"), "model")

    def test_global_search_passes_page_number(self):
        """Verify execute_global_search passes the page parameter to underlying scraper engines."""
        from handlers.global_search import execute_global_search
        from unittest.mock import patch
        import asyncio

        with patch("handlers.global_search.search_kvs", return_value=[]) as mock_kvs, \
             patch("handlers.global_search.search_leakedzone", return_value=[]) as mock_lz, \
             patch("handlers.global_search.search_thotchicks", return_value=[]) as mock_tc, \
             patch("handlers.global_search.get_wp_listing_posts", return_value=[]) as mock_wp, \
             patch("handlers.global_search.search_mmsdesi", return_value=[]) as mock_desi, \
             patch("handlers.global_search.search_mmsvibex", return_value=[]) as mock_vibex, \
             patch("handlers.global_search.search_forum", return_value=[]) as mock_forum:

            asyncio.run(execute_global_search("test query", page=3, limit_per_engine=5))

            # Check page=3 was passed to search_kvs (args: site_key, query, page, limit)
            self.assertEqual(mock_kvs.call_args_list[0][0][2], 3)
            # Check page=3 was passed to search_leakedzone (args: query, page, limit)
            self.assertEqual(mock_lz.call_args_list[0][0][1], 3)
            # Check page=3 was passed to search_thotchicks (args: query, page, limit)
            self.assertEqual(mock_tc.call_args_list[0][0][1], 3)

    def test_kvs_and_leakedzone_pagination_urls(self):
        """Verify KVS and LeakedZone construct correct URL query parameters for page 2."""
        from engines.kvs import get_kvs_listing_items
        from engines.leakedzone import get_leakedzone_model_videos
        from bs4 import BeautifulSoup
        from unittest.mock import patch

        dummy_soup = BeautifulSoup("<html><body></body></html>", "html.parser")

        with patch("engines.kvs._fetch_soup") as mock_kvs_soup:
            mock_kvs_soup.return_value = dummy_soup
            # Test HornySapiens search page 2
            get_kvs_listing_items("https://hornysapiens.com/search/desi/", page=2)
            called_url = mock_kvs_soup.call_args[0][0]
            self.assertIn("from_videos=02", called_url)

            # Test X-Video Tube model page 2
            get_kvs_listing_items("https://x-video.tube/models/jasmine-sherni/", page=2)
            xv_called_url = mock_kvs_soup.call_args[0][0]
            self.assertIn("videos/2", xv_called_url)

        with patch("engines.leakedzone._fetch_soup") as mock_lz_soup:
            mock_lz_soup.return_value = dummy_soup
            get_leakedzone_model_videos("jasminesherni", page=2)
            lz_called_url = mock_lz_soup.call_args[0][0]
            self.assertIn("page=2", lz_called_url)
            self.assertNotIn("sort=latest", lz_called_url)


if __name__ == "__main__":
    unittest.main()
