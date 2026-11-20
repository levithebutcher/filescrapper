# tests/test_bot.py
"""
Unit tests for bot message formatting, UI buttons, and database integration.
"""

import uuid
import unittest
from bot import format_post_card, group_links_by_host
from scraper import get_host_display_name
import db


class TestBot(unittest.TestCase):
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
        """Test formatting of post details card with copyable multi-line code boxes."""
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
        caption, markup = format_post_card(details)
        self.assertIn("Sample Movie &lt;4K&gt;", caption)
        self.assertIn("#4K", caption)
        self.assertIn("View Forum Thread", caption)
        self.assertIn("<pre><code>https://vidara.to/v/part1\nhttps://vidara.to/v/part2</code></pre>", caption)
        self.assertIn("All Links (Batch Copy All):", caption)
        self.assertIsNone(markup)

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


if __name__ == "__main__":
    unittest.main()
