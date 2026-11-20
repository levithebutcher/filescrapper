# tests/test_bot.py
"""
Unit tests for bot message formatting, utility functions, and structure.
"""

import unittest
from bot import format_post_message, get_uptime_str, get_start_keyboard
from config import STREAMING_DOMAINS, BOT_VERSION


class TestBot(unittest.TestCase):
    def test_format_post_message_with_links(self):
        """Test formatting post message when streaming links are present."""
        details = {
            "title": "Amazing Movie <HD>",
            "post_url": "https://dropmms.com/topic/123-movie/",
            "streaming_links": ["https://vidara.to/v/abc12", "https://streamtape.com/e/xyz89"],
            "thumbnail": "https://dropmms.com/thumb.jpg",
        }
        msg = format_post_message(details)

        # Ensure HTML escaping occurred
        self.assertIn("Amazing Movie &lt;HD&gt;", msg)
        self.assertNotIn("Amazing Movie <HD>", msg)

        # Check links presence
        self.assertIn("https://vidara.to/v/abc12", msg)
        self.assertIn("https://streamtape.com/e/xyz89", msg)
        self.assertIn("Streaming Links (2)", msg)

    def test_format_post_message_without_links(self):
        """Test formatting post message when no streaming links are found."""
        details = {
            "title": "Discussion Only",
            "post_url": "https://dropmms.com/topic/456-discuss/",
            "streaming_links": [],
            "thumbnail": None,
        }
        msg = format_post_message(details)
        self.assertIn("Discussion Only", msg)
        self.assertIn("Koi streaming link nahi mila", msg)

    def test_get_uptime_str(self):
        """Test uptime string generation."""
        uptime = get_uptime_str()
        self.assertIsInstance(uptime, str)
        self.assertTrue(any(unit in uptime for unit in ["s", "m", "h", "d"]))

    def test_get_start_keyboard(self):
        """Test inline keyboard markup generation."""
        kb = get_start_keyboard()
        self.assertIsNotNone(kb.inline_keyboard)
        # Check that we have buttons configured
        flat_buttons = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertTrue(any("Help" in b for b in flat_buttons))
        self.assertTrue(any("Domains" in b for b in flat_buttons))
        self.assertTrue(any("Status" in b for b in flat_buttons))


if __name__ == "__main__":
    unittest.main()
