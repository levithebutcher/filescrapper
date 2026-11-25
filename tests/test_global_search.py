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


if __name__ == "__main__":
    unittest.main()
