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


if __name__ == "__main__":
    unittest.main()
