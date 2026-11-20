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
    _is_valid_thumbnail_url,
    get_post_details,
    filter_links_by_preference,
    get_host_display_name,
    extract_tags_and_quality,
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

    def test_get_host_display_name(self):
        """Test emoji badge formatting for streaming hosts."""
        self.assertEqual(get_host_display_name("https://vidara.to/v/123"), "⚡ Vidara")
        self.assertEqual(get_host_display_name("https://streamtape.com/e/456"), "🎬 Streamtape")
        self.assertEqual(get_host_display_name("https://streamfiles.net/789"), "📥 Streamfiles")

    def test_extract_tags_and_quality(self):
        """Test quality and tag extraction from title."""
        title = "Super Action Film [1080p] (Exclusive) [Hindi]"
        clean_title, tags = extract_tags_and_quality(title)
        self.assertIn("1080p", tags)
        self.assertIn("Exclusive", tags)
        self.assertIn("Hindi", tags)

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

    def test_is_valid_thumbnail_url(self):
        """Test rejection of blank.gif, site logos, and acceptance of real images."""
        self.assertFalse(_is_valid_thumbnail_url("https://dropmms.com/uploads/blank.gif"))
        self.assertFalse(_is_valid_thumbnail_url("https://dropmms.com/images/spacer.png"))
        self.assertFalse(_is_valid_thumbnail_url("https://dropmms.com/theme/site_logo.png"))
        self.assertFalse(_is_valid_thumbnail_url("data:image/svg+xml;base64,..."))
        self.assertFalse(_is_valid_thumbnail_url(""))

        # Real movie poster
        self.assertTrue(_is_valid_thumbnail_url("https://dropmms.com/uploads/monthly_2026/poster_1080p.jpg"))
        self.assertTrue(_is_valid_thumbnail_url("https://img.host.com/images/movie_shot.webp"))

    @patch("scraper._fetch_soup")
    def test_get_post_details(self, mock_fetch_soup):
        """Test full get_post_details with mocked soup response."""
        html = """
        <html>
            <head>
                <meta property="og:image" content="https://dropmms.com/thumb.jpg" />
            </head>
            <body>
                <h1 class="ipsType_pageTitle">Sample Video Title [1080p]</h1>
                <div class="cPost_contentWrap">
                    <a href="https://vidara.to/v/sample123">Vidara Link</a>
                </div>
            </body>
        </html>
        """
        mock_fetch_soup.return_value = BeautifulSoup(html, "html.parser")

        details = get_post_details("https://dropmms.com/topic/123-sample/")
        self.assertEqual(details["title"], "Sample Video Title [1080p]")
        self.assertEqual(details["thumbnail"], "https://dropmms.com/thumb.jpg")
        self.assertEqual(details["streaming_links"], ["https://vidara.to/v/sample123"])
        self.assertEqual(details["post_url"], "https://dropmms.com/topic/123-sample/")
        self.assertIn("1080p", details["tags"])

    def test_filter_links_by_preference(self):
        """Test user preferred host filtering and smart fallback."""
        sample_links = [
            "https://vidara.to/v/vid1",
            "https://streamtape.com/e/tape1",
            "https://streamfiles.net/sf1",
        ]
        # Exact match
        badge, links, is_fallback = filter_links_by_preference(sample_links, "streamtape")
        self.assertEqual(badge, "🎬 Streamtape")
        self.assertEqual(links, ["https://streamtape.com/e/tape1"])
        self.assertFalse(is_fallback)

        # Fallback when preferred host is missing
        badge, links, is_fallback = filter_links_by_preference(sample_links, "doodstream")
        self.assertTrue(is_fallback)
        self.assertEqual(len(links), 1)

        # All hosts
        badge, links, is_fallback = filter_links_by_preference(sample_links, "all")
        self.assertEqual(len(links), 3)

    def test_is_valid_image_bytes(self):
        """Test strict validation of image magic bytes vs HTML error pages."""
        from scraper import is_valid_image_bytes

        # Valid JPEG
        jpeg_data = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 1000
        self.assertTrue(is_valid_image_bytes(jpeg_data))

        # Valid PNG
        png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 1000
        self.assertTrue(is_valid_image_bytes(png_data))

        # Valid WebP
        webp_data = b"RIFF\x00\x00\x04\x00WEBPVP8 " + b"\x00" * 1000
        self.assertTrue(is_valid_image_bytes(webp_data))

        # Reject HTML page (the cause of Image_process_failed)
        html_data = b"<!DOCTYPE html><html><head><title>Viewer</title></head><body>Error 404</body></html>" + b" " * 1000
        self.assertFalse(is_valid_image_bytes(html_data))

        # Reject short/empty data
        self.assertFalse(is_valid_image_bytes(b""))
        self.assertFalse(is_valid_image_bytes(None))
        self.assertFalse(is_valid_image_bytes(b"\xff\xd8\xff"))  # too short (<512 bytes)

    def test_is_posted_today(self):
        """Test Option 1 Live Date Cutoff logic."""
        from datetime import datetime, timezone, timedelta
        from scraper import _is_posted_today

        now_utc = datetime.now(timezone.utc)
        today_iso = now_utc.strftime("%Y-%m-%dT12:00:00Z")
        yesterday_dt = now_utc - timedelta(days=1)
        yesterday_iso = yesterday_dt.strftime("%Y-%m-%dT12:00:00Z")

        # Today ISO timestamp
        is_today, is_older = _is_posted_today(today_iso, None)
        self.assertTrue(is_today)
        self.assertFalse(is_older)

        # Yesterday ISO timestamp -> triggers cutoff
        is_today, is_older = _is_posted_today(yesterday_iso, None)
        self.assertFalse(is_today)
        self.assertTrue(is_older)

        # Relative time strings
        self.assertEqual(_is_posted_today(None, "2 hours ago"), (True, False))
        self.assertEqual(_is_posted_today(None, "Just now"), (True, False))
        self.assertEqual(_is_posted_today(None, "Yesterday at 10:30 PM"), (False, True))
        self.assertEqual(_is_posted_today(None, "3 days ago"), (False, True))

    @patch("scraper._fetch_soup")
    def test_get_forum_topics_date_cutoff(self, mock_fetch_soup):
        """Test that only_today=True stops scanning immediately on older topics."""
        from datetime import datetime, timezone, timedelta
        from scraper import get_forum_topics

        now_utc = datetime.now(timezone.utc)
        today_iso = now_utc.strftime("%Y-%m-%dT08:00:00Z")
        yesterday_iso = (now_utc - timedelta(days=1)).strftime("%Y-%m-%dT08:00:00Z")

        html = f"""
        <html>
            <body>
                <li class="ipsDataItem">
                    <a href="/topic/101-today-post-1/">Today Video 1</a>
                    <time datetime="{today_iso}">2 hours ago</time>
                </li>
                <li class="ipsDataItem">
                    <a href="/topic/102-today-post-2/">Today Video 2</a>
                    <time datetime="{today_iso}">5 hours ago</time>
                </li>
                <li class="ipsDataItem">
                    <a href="/topic/103-yesterday-post/">Yesterday Video</a>
                    <time datetime="{yesterday_iso}">Yesterday at 11 PM</time>
                </li>
                <li class="ipsDataItem">
                    <a href="/topic/104-older-post/">Older Video</a>
                    <time datetime="{yesterday_iso}">2 days ago</time>
                </li>
            </body>
        </html>
        """
        mock_fetch_soup.return_value = BeautifulSoup(html, "html.parser")

        # Mode A: only_today=True (Live Date Cutoff) -> should stop after 2 today posts!
        today_topics = get_forum_topics("https://dropmms.com/forum/2-test/", limit=25, only_today=True)
        self.assertEqual(len(today_topics), 2)
        self.assertEqual(today_topics[0]["title"], "Today Video 1")
        self.assertEqual(today_topics[1]["title"], "Today Video 2")

        # Mode B: only_today=False (Normal Page Scan) -> should return all 4 posts up to limit
        all_topics = get_forum_topics("https://dropmms.com/forum/2-test/", limit=25, only_today=False)
        self.assertEqual(len(all_topics), 4)


if __name__ == "__main__":
    unittest.main()
