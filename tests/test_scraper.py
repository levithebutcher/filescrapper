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

        # Test index.php query style URLs
        url_idx = "https://dropmms.com/index.php?/topic/123-sample-title/&page=2#comment"
        cleaned_idx = _clean_topic_url(url_idx)
        self.assertEqual(cleaned_idx, "https://dropmms.com/index.php?/topic/123-sample-title/")

    def test_is_forum_url(self):
        """Test detection of forum/category URLs."""
        self.assertTrue(is_forum_url("https://dropmms.com/forum/2-general-discussion/"))
        self.assertTrue(is_forum_url("https://dropmms.com/forums/forum-name/"))
        self.assertTrue(is_forum_url("https://dropmms.com/category/1-movies/"))
        self.assertTrue(is_forum_url("https://dropmms.com/categories/1-movies/"))
        self.assertTrue(is_forum_url("https://dropmms.com/"))
        self.assertTrue(is_forum_url("https://dropmms.com"))
        self.assertTrue(is_forum_url("https://dropmms.com/index.php"))
        self.assertFalse(is_forum_url("https://dropmms.com/topic/456-sample/"))
        self.assertFalse(is_forum_url(""))

    def test_is_topic_url(self):
        """Test detection of single topic/post URLs."""
        self.assertTrue(is_topic_url("https://dropmms.com/topic/123-sample-title/"))
        self.assertTrue(is_topic_url("https://dropmms.com/TOPIC/123-SAMPLE/"))
        self.assertTrue(is_topic_url("https://dropmms.com/index.php?/topic/123-sample/"))
        self.assertTrue(is_topic_url("https://dropmms.com/topics/topic/123-sample/"))
        self.assertFalse(is_topic_url("https://dropmms.com/forum/2-general/"))
        self.assertFalse(is_topic_url("https://dropmms.com/category/1-movies/"))
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
        self.assertFalse(_is_valid_thumbnail_url("https://i.t.net.ar/images/cerrar.png"))
        self.assertFalse(_is_valid_thumbnail_url("https://example.com/close.png"))
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

    @patch("scraper._fetch_soup")
    def test_exclude_author_avatar_and_prioritize_poster(self, mock_fetch_soup):
        """Test that author avatar in cAuthorPane is excluded and post body image is chosen."""
        html = """
        <html>
            <body>
                <article class="cPost">
                    <aside class="cAuthorPane">
                        <img class="ipsUserPhoto" src="https://dropmms.com/uploads/avatar_author.jpg" />
                    </aside>
                    <div class="cPost_contentWrap">
                        <div data-role="commentContent">
                            <img class="ipsImage" src="https://dropmms.com/uploads/movie_poster_real.jpg" />
                            <a href="https://vidara.to/v/test123">Vidara</a>
                        </div>
                    </div>
                </article>
            </body>
        </html>
        """
        mock_fetch_soup.return_value = BeautifulSoup(html, "html.parser")
        details = get_post_details("https://dropmms.com/topic/999-poster-test/")
        self.assertEqual(details["thumbnail"], "https://dropmms.com/uploads/movie_poster_real.jpg")
        self.assertNotIn("https://dropmms.com/uploads/avatar_author.jpg", details["thumbnail_candidates"])

    def test_is_valid_thumbnail_image_pillow(self):
        """Test Pillow dimension verification rejects tiny avatars and accepts large posters."""
        from PIL import Image
        import io
        from scraper import is_valid_thumbnail_image

        # Tiny avatar (64x64) -> rejected
        im_small = Image.new("RGB", (64, 64), color="red")
        buf_small = io.BytesIO()
        im_small.save(buf_small, format="JPEG")
        self.assertFalse(is_valid_thumbnail_image(buf_small.getvalue()))

        # Large movie poster (600x900) -> accepted
        im_large = Image.new("RGB", (600, 900), color="blue")
        buf_large = io.BytesIO()
        im_large.save(buf_large, format="JPEG")
        self.assertTrue(is_valid_thumbnail_image(buf_large.getvalue()))

    def test_clean_highres_image_url(self):
        """Test converting thumbnail URLs to original full-resolution posters."""
        from scraper import _clean_highres_image_url

        # Invision thumb removal
        ips_url = "https://dropmms.com/uploads/monthly_2026_11/poster.thumb.jpg.12345.jpg"
        self.assertEqual(_clean_highres_image_url(ips_url), "https://dropmms.com/uploads/monthly_2026_11/poster.jpg.12345.jpg")

        # PixHost thumbs to full images
        pix_url = "https://t15.pixhost.to/thumbs/888/poster.jpg"
        self.assertEqual(_clean_highres_image_url(pix_url), "https://img15.pixhost.to/images/888/poster.jpg")

        # ImgBox thumbs to original
        imgbox_url = "https://thumbs2.imgbox.com/ab/cd/poster_t.jpg"
        self.assertEqual(_clean_highres_image_url(imgbox_url), "https://images2.imgbox.com/ab/cd/poster_o.jpg")

    def test_optimize_image_for_telegram(self):
        """Test that excessively tall images are padded to prevent squarish cropping on Telegram."""
        from PIL import Image
        import io
        from scraper import optimize_image_for_telegram

        # Very tall image (400x1200, ratio 3.0)
        im_tall = Image.new("RGB", (400, 1200), color="green")
        buf = io.BytesIO()
        im_tall.save(buf, format="JPEG")

        opt_data = optimize_image_for_telegram(buf.getvalue())
        with Image.open(io.BytesIO(opt_data)) as im_opt:
            w, h = im_opt.size
            self.assertEqual(h, 1200)
            self.assertGreater(w, 400)
            # Aspect ratio should now be <= 1.7 (safe for Telegram without cropping)
            self.assertLessEqual(h / w, 1.7)

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
        self.assertEqual(_is_posted_today(None, "5h"), (True, False))
        self.assertEqual(_is_posted_today(None, "5h ago"), (True, False))
        self.assertEqual(_is_posted_today(None, "25m"), (True, False))
        self.assertEqual(_is_posted_today(None, "Just now"), (True, False))
        self.assertEqual(_is_posted_today(None, "Today at 10:30"), (True, False))
        self.assertEqual(_is_posted_today(None, "Yesterday at 10:30 PM"), (False, True))
        self.assertEqual(_is_posted_today(None, "Yesterday at 9:43"), (False, True))
        self.assertEqual(_is_posted_today(None, None, full_row_text="Started by User, Yesterday at 9:43 PM"), (False, True))
        self.assertEqual(_is_posted_today(None, "3 days ago"), (False, True))
        self.assertEqual(_is_posted_today(None, "2d"), (False, True))

        # Month and Day formatting
        now_month_b = now_utc.strftime("%b")
        now_day = now_utc.day
        self.assertEqual(_is_posted_today(None, f"{now_month_b} {now_day}"), (True, False))
        self.assertEqual(_is_posted_today(None, f"{now_day} {now_month_b}"), (True, False))
        self.assertEqual(_is_posted_today(None, "Oct 15"), (False, True))

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
                <li class="ipsDataItem ipsDataItem_pinned">
                    <a href="/topic/000-pinned-announcement/">Forum Rules [Pinned]</a>
                    <time datetime="{yesterday_iso}">1 year ago</time>
                </li>
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

        # Mode B: only_today=False (Normal Page Scan) -> should return all 5 posts up to limit
        all_topics = get_forum_topics("https://dropmms.com/forum/2-test/", limit=25, only_today=False)
        self.assertEqual(len(all_topics), 5)

    @patch("scraper._fetch_soup")
    def test_get_forum_topics_subforums(self, mock_fetch_soup):
        """Test category page that lists subforums traverses into subforums."""
        from scraper import get_forum_topics

        parent_html = """
        <html>
            <body>
                <li class="cForumRow">
                    <a href="/forum/10-subforum-a/">Subforum A</a>
                </li>
            </body>
        </html>
        """
        child_html = """
        <html>
            <body>
                <li class="ipsDataItem">
                    <div class="ipsDataItem_main">
                        <h4 class="ipsDataItem_title"><a href="/topic/501-sub-video/">Subforum Video 1</a></h4>
                    </div>
                </li>
            </body>
        </html>
        """
        mock_fetch_soup.side_effect = [
            BeautifulSoup(parent_html, "html.parser"),
            BeautifulSoup(child_html, "html.parser"),
        ]

        topics = get_forum_topics("https://dropmms.com/category/1-parent/", limit=25, only_today=False)
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]["title"], "Subforum Video 1")
        self.assertEqual(topics[0]["url"], "https://dropmms.com/topic/501-sub-video/")

    @patch("scraper._fetch_soup")
    def test_get_forum_topics_specific_page(self, mock_fetch_soup):
        """Test that get_forum_topics respects user-provided /page/2/ URL and fetches Page 2."""
        from scraper import get_forum_topics

        p2_html = """
        <html><body>
            <li class="ipsDataItem"><a href="/topic/201-p2-video/">Page 2 Video 1</a></li>
            <li class="ipsDataItem"><a href="/topic/202-p2-video/">Page 2 Video 2</a></li>
        </body></html>
        """
        mock_fetch_soup.return_value = BeautifulSoup(p2_html, "html.parser")

        topics = get_forum_topics(
            "https://dropmms.com/forum/4-desi/page/2/?sortby=start_date&sortdirection=desc",
            limit=25,
            only_today=False,
        )

        called_url = mock_fetch_soup.call_args[0][0]
        self.assertIn("/page/2/", called_url)
        self.assertIn("sortby=forums_topics.start_date&sortdirection=desc", called_url)
        self.assertEqual(len(topics), 2)
        self.assertEqual(topics[0]["title"], "Page 2 Video 1")

    @patch("scraper._fetch_soup")
    def test_get_forum_topics_page_fallback_without_row_classes(self, mock_fetch_soup):
        """Test that get_forum_topics uses universal fallback on Page 2 when row classes are absent."""
        from scraper import get_forum_topics

        p2_links_html = """
        <html><body>
            <div>
                <a href="/topic/301-fallback-video/">Fallback Video 1</a>
                <a href="/topic/302-fallback-video/">Fallback Video 2</a>
            </div>
        </body></html>
        """
        mock_fetch_soup.return_value = BeautifulSoup(p2_links_html, "html.parser")

        topics = get_forum_topics(
            "https://dropmms.com/forum/4-desi/page/2/",
            limit=25,
            only_today=False,
        )
        self.assertEqual(len(topics), 2)
        self.assertEqual(topics[0]["title"], "Fallback Video 1")
        self.assertEqual(topics[1]["title"], "Fallback Video 2")

    @patch("scraper._fetch_soup")
    def test_get_forum_topics_clean_page_retry(self, mock_fetch_soup):
        """Test that get_forum_topics retries without query parameters if query params return 0 topics."""
        from scraper import get_forum_topics

        empty_html = "<html><body><div>No topics found with bad sort</div></body></html>"
        success_html = """
        <html><body>
            <li class="ipsDataItem"><a href="/topic/401-recovered/">Recovered Video 1</a></li>
        </body></html>
        """
        mock_fetch_soup.side_effect = [
            BeautifulSoup(empty_html, "html.parser"),
            BeautifulSoup(success_html, "html.parser"),
        ]

        topics = get_forum_topics(
            "https://dropmms.com/forum/4-desi/page/2/?sortby=invalid_col",
            limit=25,
            only_today=False,
        )
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]["title"], "Recovered Video 1")

    def test_provider_priority_and_fallback(self):
        """Test that PROVIDER_PRIORITY strictly picks Streamtape -> Vidara -> Streamfiles -> iPlayGo."""
        from scraper import filter_links_by_preference, PROVIDER_PRIORITY

        self.assertEqual(PROVIDER_PRIORITY[0], "streamtape")
        self.assertEqual(PROVIDER_PRIORITY[1], "vidara")
        self.assertEqual(PROVIDER_PRIORITY[2], "streamfiles")
        self.assertEqual(PROVIDER_PRIORITY[3], "iplaygo")

        # When streamtape and vidara are both present and user has no special pref (default streamtape)
        links = [
            "https://vidara.to/v/vid123",
            "https://streamtape.com/e/tape123",
            "https://streamfiles.net/sf123",
        ]
        badge, filtered, is_fallback = filter_links_by_preference(links, preferred_host="streamtape")
        self.assertEqual(badge, "🎬 Streamtape")
        self.assertEqual(filtered, ["https://streamtape.com/e/tape123"])
        self.assertFalse(is_fallback)

        # Smart fallback: preferred host (streamtape) is missing; should fall back to next priority (vidara)
        links_no_tape = [
            "https://streamfiles.net/sf123",
            "https://vidara.to/v/vid123",
            "https://doodstream.com/d/dood123",
        ]
        badge, filtered, is_fallback = filter_links_by_preference(links_no_tape, preferred_host="streamtape")
        self.assertEqual(badge, "⚡ Vidara")
        self.assertEqual(filtered, ["https://vidara.to/v/vid123"])
        self.assertTrue(is_fallback)

        # Fallback to streamfiles when streamtape and vidara are missing
        links_only_sf = [
            "https://doodstream.com/d/dood123",
            "https://streamfiles.net/sf123",
        ]
        badge, filtered, is_fallback = filter_links_by_preference(links_only_sf, preferred_host="streamtape")
        self.assertEqual(badge, "📥 Streamfiles")
        self.assertEqual(filtered, ["https://streamfiles.net/sf123"])
        self.assertTrue(is_fallback)

    def test_slicing_and_ranges(self):
        """Test parse_slicing_args and apply_slice for count, range, and last-N."""
        from scraper import parse_slicing_args, apply_slice

        # 1. Single count: 4
        url, start, end, is_last = parse_slicing_args(["4"])
        self.assertIsNone(url)
        self.assertEqual((start, end, is_last), (1, 4, False))

        # 2. Range: 1-5
        url, start, end, is_last = parse_slicing_args(["1-5"])
        self.assertIsNone(url)
        self.assertEqual((start, end, is_last), (1, 5, False))

        # 3. Range with words: 1 to 5
        url, start, end, is_last = parse_slicing_args(["1", "to", "5"])
        self.assertEqual((start, end, is_last), (1, 5, False))

        # 4. Last 5
        url, start, end, is_last = parse_slicing_args(["last", "5"])
        self.assertEqual((start, end, is_last), (None, 5, True))

        # 5. URL with count
        url, start, end, is_last = parse_slicing_args(["https://dropmms.com/forum/2-general/", "4"])
        self.assertEqual(url, "https://dropmms.com/forum/2-general/")
        self.assertEqual((start, end, is_last), (1, 4, False))

        # 6. Apply slice tests
        items = list(range(1, 11))  # 1 to 10
        self.assertEqual(apply_slice(items, 1, 4, False), [1, 2, 3, 4])
        self.assertEqual(apply_slice(items, 1, 5, False), [1, 2, 3, 4, 5])
        self.assertEqual(apply_slice(items, 6, 10, False), [6, 7, 8, 9, 10])
        self.assertEqual(apply_slice(items, None, 5, True), [6, 7, 8, 9, 10])
        self.assertEqual(apply_slice(items, None, 15, True), items)

    def test_livecamrips_helpers(self):
        """Test LiveCamRips URL detection, title cleaning, and card formatting."""
        from scraper import (
            is_livecam_url,
            is_livecam_video_url,
            is_livecam_model_url,
            clean_livecam_title,
            format_livecam_card,
        )

        model_url = "https://livecamrips.to/model/36773/GoddessAnna?sort=newest"
        video_url = "https://livecamrips.to/video/16877744"

        self.assertTrue(is_livecam_url(model_url))
        self.assertTrue(is_livecam_url(video_url))
        self.assertTrue(is_livecam_model_url(model_url))
        self.assertFalse(is_livecam_model_url(video_url))
        self.assertTrue(is_livecam_video_url(video_url))
        self.assertFalse(is_livecam_video_url(model_url))

        # Title cleaning: strip "Stripchat Recording", "Stripchat", "Recording"
        self.assertEqual(clean_livecam_title("GoddessAnna - Stripchat Recording"), "GoddessAnna")
        self.assertEqual(clean_livecam_title("GoddessAnna — Stripchat Recording"), "GoddessAnna")
        self.assertEqual(clean_livecam_title("GoddessAnna - Stripchat - 2026-11-19 00:19"), "GoddessAnna")
        self.assertEqual(clean_livecam_title("livecamrips.to GoddessAnna - Stripchat"), "GoddessAnna")

        # Card formatting - Default mode ('streaming')
        details = {
            "model_name": "GoddessAnna - Stripchat Recording",
            "title": "GoddessAnna - Stripchat Recording",
            "date": "19 Nov 2026, 00:19",
            "duration": "10:34",
            "platform": "Stripchat",
            "video_url": "https://livecamrips.to/video/16877744",
            "streaming_links": ["https://abstream.to/embed-kpmvtq4znbl6.html"],
        }
        card_default = format_livecam_card(details)
        self.assertIn("<blockquote>📹 <b>GoddessAnna</b>", card_default)
        self.assertNotIn("Stripchat Recording", card_default)
        self.assertIn("📅 <b>Date:</b> 19 Nov 2026, 00:19", card_default)
        self.assertIn("⏱️ <b>Duration:</b> 10:34", card_default)
        self.assertIn("#GoddessAnna", card_default)
        self.assertIn("<code>https://abstream.to/embed-kpmvtq4znbl6.html</code>", card_default)
        self.assertNotIn("<code>https://livecamrips.to/video/16877744</code>", card_default)

        # Card formatting - 'both' mode
        card_both = format_livecam_card(details, link_mode="both")
        self.assertIn("<code>https://livecamrips.to/video/16877744</code>", card_both)
        self.assertIn("<code>https://abstream.to/embed-kpmvtq4znbl6.html</code>", card_both)

        # Card formatting - 'page' mode
        card_page = format_livecam_card(details, link_mode="page")
        self.assertIn("<code>https://livecamrips.to/video/16877744</code>", card_page)
        self.assertNotIn("<code>https://abstream.to/embed-kpmvtq4znbl6.html</code>", card_page)

    def test_title_words_not_triggering_cutoff(self):
        """Test that words like 'week', 'month', 'year' in titles do NOT trigger cutoff."""
        from datetime import datetime, timezone, timedelta
        from scraper import _is_posted_today

        now_utc = datetime.now(timezone.utc)
        today_iso = now_utc.strftime("%Y-%m-%dT10:00:00Z")

        # Title containing 'week', 'month', 'year'
        is_today, is_older = _is_posted_today(today_iso, "2 hours ago", full_row_text="Best compilation of the week and year")
        self.assertTrue(is_today)
        self.assertFalse(is_older)

    @patch("scraper._fetch_soup")
    def test_get_forum_topics_multipage_today(self, mock_fetch_soup):
        """Test that get_forum_topics paginates to page 2 to collect all today's uploads."""
        from datetime import datetime, timezone, timedelta
        from scraper import get_forum_topics

        now_utc = datetime.now(timezone.utc)
        today_iso = now_utc.strftime("%Y-%m-%dT10:00:00Z")
        yesterday_iso = (now_utc - timedelta(days=1)).strftime("%Y-%m-%dT10:00:00Z")

        # Page 1: 3 today posts
        p1_html = f"""
        <html><body>
            <li class="ipsDataItem"><a href="/topic/1-p1/">Post 1</a><time datetime="{today_iso}">1h ago</time></li>
            <li class="ipsDataItem"><a href="/topic/2-p1/">Post 2</a><time datetime="{today_iso}">2h ago</time></li>
            <li class="ipsDataItem"><a href="/topic/3-p1/">Post 3</a><time datetime="{today_iso}">3h ago</time></li>
        </body></html>
        """
        # Page 2: 2 today posts + 1 yesterday post (cutoff)
        p2_html = f"""
        <html><body>
            <li class="ipsDataItem"><a href="/topic/4-p2/">Post 4</a><time datetime="{today_iso}">4h ago</time></li>
            <li class="ipsDataItem"><a href="/topic/5-p2/">Post 5</a><time datetime="{today_iso}">5h ago</time></li>
            <li class="ipsDataItem"><a href="/topic/6-p2/">Yesterday Post</a><time datetime="{yesterday_iso}">Yesterday</time></li>
        </body></html>
        """
        mock_fetch_soup.side_effect = [
            BeautifulSoup(p1_html, "html.parser"),
            BeautifulSoup(p2_html, "html.parser"),
        ]

        topics = get_forum_topics("https://dropmms.com/forum/2-general/", limit=100, only_today=True)
        self.assertEqual(len(topics), 5)
        self.assertEqual([t["title"] for t in topics], ["Post 1", "Post 2", "Post 3", "Post 4", "Post 5"])

    @patch("scraper._fetch_soup")
    def test_get_livecam_model_videos_multipage(self, mock_fetch_soup):
        """Test multi-page crawling for LiveCamRips model pages."""
        from scraper import get_livecam_model_videos

        p1_html = """
        <html><body>
            <figure video-id="101" class="tm-video-item"><a href="/video/101"></a></figure>
            <figure video-id="102" class="tm-video-item"><a href="/video/102"></a></figure>
        </body></html>
        """
        p2_html = """
        <html><body>
            <figure video-id="103" class="tm-video-item"><a href="/video/103"></a></figure>
            <figure video-id="104" class="tm-video-item"><a href="/video/104"></a></figure>
        </body></html>
        """
        mock_fetch_soup.side_effect = [
            BeautifulSoup(p1_html, "html.parser"),
            BeautifulSoup(p2_html, "html.parser"),
        ]

        videos = get_livecam_model_videos("https://livecamrips.to/model/36773/GoddessAnna", only_today=False, limit=4)
        self.assertEqual(len(videos), 4)
        self.assertEqual([v["video_id"] for v in videos], ["101", "102", "103", "104"])

    @patch("scraper._fetch_soup")
    def test_search_livecam_models(self, mock_fetch_soup):
        """Test searching LiveCamRips models."""
        from scraper import search_livecam_models

        search_html = """
        <html><body>
            <figure class="tm-video-item">
                <a href="https://livecamrips.to/model/36773/GoddessAnna">
                    <img src="https://images.livecamrips.to/1292/12922696.png" />
                </a>
            </figure>
            <div>
                <a href="https://livecamrips.to/model/36773/GoddessAnna">
                    <span class="tm-text-gray-light">GoddessAnna</span>
                </a>
            </div>
            <figure class="tm-video-item">
                <a href="https://livecamrips.to/model/231613/GoddessAnnaxxx">
                    <img src="https://images.livecamrips.to/283/2832444.png" />
                </a>
            </figure>
        </body></html>
        """
        mock_fetch_soup.return_value = BeautifulSoup(search_html, "html.parser")

        models = search_livecam_models("GoddessAnna", limit=5)
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["name"], "GoddessAnna")
        self.assertEqual(models[0]["url"], "https://livecamrips.to/model/36773/GoddessAnna")
        self.assertEqual(models[0]["thumb"], "https://images.livecamrips.to/1292/12922696.png")
        self.assertEqual(models[1]["name"], "GoddessAnnaxxx")

    def test_parse_model_range_input(self):
        """Test parsing various range/count/page input formats."""
        from scraper import parse_model_range_input

        # Single numbers
        self.assertEqual(parse_model_range_input("5"), (1, 5, None))
        self.assertEqual(parse_model_range_input("10"), (1, 10, None))
        self.assertEqual(parse_model_range_input("0"), (None, None, None))

        # Ranges
        self.assertEqual(parse_model_range_input("1-5"), (1, 5, None))
        self.assertEqual(parse_model_range_input("5-10"), (5, 10, None))
        self.assertEqual(parse_model_range_input("5 to 10"), (5, 10, None))
        self.assertEqual(parse_model_range_input("10-5"), (5, 10, None))

        # Pages
        self.assertEqual(parse_model_range_input("page 1"), (None, None, 1))
        self.assertEqual(parse_model_range_input("page 2"), (None, None, 2))
        self.assertEqual(parse_model_range_input("p2"), (None, None, 2))
        self.assertEqual(parse_model_range_input("p 3"), (None, None, 3))
        self.assertEqual(parse_model_range_input("page 0"), (None, None, None))

        # Invalid
        self.assertEqual(parse_model_range_input("invalid text"), (None, None, None))
        self.assertEqual(parse_model_range_input("-5"), (None, None, None))

    @patch("scraper._fetch_soup")
    def test_get_livecam_model_stats(self, mock_fetch_soup):
        """Test fetching and computing model statistics and total video counts."""
        from scraper import get_livecam_model_stats

        html = """
        <html><body>
            <h1>GoddessAnna</h1>
            <figure class="tm-video-item" video-id="1"></figure>
            <figure class="tm-video-item" video-id="2"></figure>
            <ul class="pagination">
                <li><a href="/model/36773/GoddessAnna/1">1</a></li>
                <li><a href="/model/36773/GoddessAnna/2">2</a></li>
                <li><a href="/model/36773/GoddessAnna/19">19</a></li>
            </ul>
        </body></html>
        """
        mock_fetch_soup.return_value = BeautifulSoup(html, "html.parser")
        stats = get_livecam_model_stats("https://livecamrips.to/model/36773/GoddessAnna/2")
        self.assertEqual(stats["name"], "GoddessAnna")
        self.assertEqual(stats["total_pages"], 19)
        self.assertEqual(stats["total_videos_str"], "304 (19 Pages)")
        self.assertEqual(stats["url"], "https://livecamrips.to/model/36773/GoddessAnna")

    @patch("scraper._fetch_soup")
    def test_get_dropmms_forums(self, mock_fetch_soup):
        """Test dynamic extraction and fallback for DropMMS forum categories."""
        from scraper import get_dropmms_forums

        html = """
        <html><body>
            <ol>
                <li class="ipsDataItem">
                    <h4 class="ipsDataItem_title">
                        <a href="https://dropmms.com/forum/4-desi-new-semi-nude-masked-no-face-videos-pics/">Desi Videos & MMS</a>
                    </h4>
                </li>
                <li class="ipsDataItem">
                    <h4 class="ipsDataItem_title">
                        <a href="/forum/2-general/">General Discussion</a>
                    </h4>
                </li>
                <li class="ipsDataItem">
                    <h4 class="ipsDataItem_title">
                        <a href="/forum/6-exclusive/">Exclusive Drops (12)</a>
                    </h4>
                </li>
            </ol>
        </body></html>
        """
        mock_fetch_soup.return_value = BeautifulSoup(html, "html.parser")
        forums = get_dropmms_forums()
        titles = [f["title"] for f in forums]
        self.assertIn("Desi Videos & MMS", titles)
        self.assertIn("General Discussion", titles)
        self.assertIn("Exclusive Drops", titles)

    @patch("scraper._fetch_soup")
    def test_get_dropmms_forums_fallback(self, mock_fetch_soup):
        """Test fallback when DropMMS home page fails to load."""
        from scraper import get_dropmms_forums, DEFAULT_DROP_FORUMS

        mock_fetch_soup.return_value = None
        forums = get_dropmms_forums()
        self.assertEqual(forums, DEFAULT_DROP_FORUMS)



if __name__ == "__main__":
    unittest.main()
