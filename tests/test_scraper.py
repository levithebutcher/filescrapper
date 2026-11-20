# tests/test_scraper.py
"""
Unit tests for scraper.py parsing, extraction, and validation logic.
"""

import unittest
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from scraper import (
    _is_streaming_link,
    _clean_topic_url,
    is_forum_url,
    is_topic_url,
    _extract_streaming_links_from_html,
    _extract_thumbnail,
    get_post_details,
)


class TestScraper(unittest.TestCase):
    def test_is_streaming_link(self):
        """Test streaming domain identification."""
        self.assertTrue(_is_streaming_link("https://vidara.to/v/12345"))
        self.assertTrue(_is_streaming_link("https://streamtape.com/e/67890"))
        self.assertTrue(_is_streaming_link("https://streamfiles.net/abc"))
        self.assertTrue(_is_streaming_link("https://doodstream.com/d/xyz"))
        self.assertTrue(_is_streaming_link("https://streamwish.to/embed/xyz"))

        # Non-streaming links
        self.assertFalse(_is_streaming_link("https://google.com"))
        self.assertFalse(_is_streaming_link("https://dropmms.com/forum/test"))
        self.assertFalse(_is_streaming_link(""))
        self.assertFalse(_is_streaming_link(None))

    def test_clean_topic_url(self):
        """Test cleaning of query params, fragments, and pagination."""
        url = "https://dropmms.com/topic/123-sample-title/?tab=comments#comment-456"
        cleaned = _clean_topic_url(url)
        self.assertEqual(cleaned, "https://dropmms.com/topic/123-sample-title/")

        url_page = "https://dropmms.com/topic/123-sample-title/page/3/"
        cleaned_page = _clean_topic_url(url_page)
        self.assertEqual(cleaned_page, "https://dropmms.com/topic/123-sample-title/")

    def test_is_forum_url(self):
        """Test detection of forum/category URLs."""
        self.assertTrue(is_forum_url("https://dropmms.com/forum/2-general-discussion/"))
        self.assertTrue(is_forum_url("https://dropmms.com/forums/forum-name/"))
        self.assertTrue(is_forum_url("https://dropmms.com/index.php"))
        self.assertFalse(is_forum_url("https://dropmms.com/topic/456-sample/"))
        self.assertFalse(is_forum_url(""))

    def test_is_topic_url(self):
        """Test detection of single topic/post URLs."""
        self.assertTrue(is_topic_url("https://dropmms.com/topic/123-sample-title/"))
        self.assertTrue(is_topic_url("https://dropmms.com/TOPIC/123-SAMPLE/"))
        self.assertFalse(is_topic_url("https://dropmms.com/forum/2-general/"))
        self.assertFalse(is_topic_url(""))

    def test_extract_streaming_links_from_html(self):
        """Test extraction of streaming links from <a>, <iframe>, and plain text."""
        sample_html = """
        <html>
            <body>
                <p>Check these links:</p>
                <a href="https://vidara.to/v/abc12345">Vidara Player</a>
                <iframe src="https://streamtape.com/e/tape123"></iframe>
                <embed src="https://streamfiles.net/embed/sf999"></embed>
                <p>Also plain text here: https://doodstream.com/d/dood456 and enjoy!</p>
                <a href="https://unrelated-domain.com/page">Unrelated</a>
            </body>
        </html>
        """
        soup = BeautifulSoup(sample_html, "html.parser")
        links = _extract_streaming_links_from_html(soup, "https://dropmms.com/topic/123/")

        self.assertIn("https://vidara.to/v/abc12345", links)
        self.assertIn("https://streamtape.com/e/tape123", links)
        self.assertIn("https://streamfiles.net/embed/sf999", links)
        self.assertIn("https://doodstream.com/d/dood456", links)
        self.assertNotIn("https://unrelated-domain.com/page", links)

    def test_extract_thumbnail(self):
        """Test OpenGraph and content image extraction."""
        html_with_og = """
        <html>
            <head>
                <meta property="og:image" content="https://dropmms.com/uploads/thumb.jpg" />
            </head>
            <body></body>
        </html>
        """
        soup_og = BeautifulSoup(html_with_og, "html.parser")
        thumb = _extract_thumbnail(soup_og, "https://dropmms.com/topic/123/")
        self.assertEqual(thumb, "https://dropmms.com/uploads/thumb.jpg")

        html_with_body_img = """
        <html>
            <body>
                <div class="cPost_contentWrap">
                    <img src="https://dropmms.com/images/poster.png" />
                </div>
            </body>
        </html>
        """
        soup_body = BeautifulSoup(html_with_body_img, "html.parser")
        thumb2 = _extract_thumbnail(soup_body, "https://dropmms.com/topic/123/")
        self.assertEqual(thumb2, "https://dropmms.com/images/poster.png")

    @patch("scraper._fetch_soup")
    def test_get_post_details(self, mock_fetch_soup):
        """Test full get_post_details with mocked soup response."""
        html = """
        <html>
            <head>
                <meta property="og:image" content="https://dropmms.com/thumb.jpg" />
            </head>
            <body>
                <h1 class="ipsType_pageTitle">Sample Video Title 2026</h1>
                <div class="cPost_contentWrap">
                    <a href="https://vidara.to/v/sample123">Vidara Link</a>
                </div>
            </body>
        </html>
        """
        mock_fetch_soup.return_value = BeautifulSoup(html, "html.parser")

        details = get_post_details("https://dropmms.com/topic/123-sample/")
        self.assertEqual(details["title"], "Sample Video Title 2026")
        self.assertEqual(details["thumbnail"], "https://dropmms.com/thumb.jpg")
        self.assertEqual(details["streaming_links"], ["https://vidara.to/v/sample123"])
        self.assertEqual(details["post_url"], "https://dropmms.com/topic/123-sample/")


if __name__ == "__main__":
    unittest.main()
