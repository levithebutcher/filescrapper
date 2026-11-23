# tests/test_clean_search.py
"""Unit tests for the clean, button-free search UX and number extraction engine."""

import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup

from ui import (
    parse_search_selection,
    format_clean_search_results_page,
    format_search_completion_card,
)
from keyboards import (
    build_search_results_clean_keyboard,
    build_forum_sort_keyboard,
    build_category_options_keyboard,
)
from engines.invision import search_forum_advanced


class TestCleanSearchUX(unittest.TestCase):
    """Test number-based selection parsing and clean card layouts."""

    def test_parse_search_selection_single(self):
        self.assertEqual(parse_search_selection("1", 10), [1])
        self.assertEqual(parse_search_selection(" 5 ", 10), [5])
        self.assertEqual(parse_search_selection("10", 10), [10])

    def test_parse_search_selection_out_of_bounds(self):
        self.assertEqual(parse_search_selection("0", 10), [])
        self.assertEqual(parse_search_selection("11", 10), [])
        self.assertEqual(parse_search_selection("-2", 10), [])

    def test_parse_search_selection_range(self):
        self.assertEqual(parse_search_selection("1-3", 10), [1, 2, 3])
        self.assertEqual(parse_search_selection("2 to 5", 10), [2, 3, 4, 5])
        self.assertEqual(parse_search_selection("4-2", 10), [2, 3, 4])
        # Range exceeding total items clips to maximum available
        self.assertEqual(parse_search_selection("8-12", 10), [8, 9, 10])

    def test_parse_search_selection_all(self):
        self.assertEqual(parse_search_selection("all", 5), [1, 2, 3, 4, 5])
        self.assertEqual(parse_search_selection("ALL", 3), [1, 2, 3])
        self.assertEqual(parse_search_selection("sab", 4), [1, 2, 3, 4])

    def test_parse_search_selection_list(self):
        self.assertEqual(parse_search_selection("1, 3, 5", 10), [1, 3, 5])
        self.assertEqual(parse_search_selection("2 4 6", 10), [2, 4, 6])
        self.assertEqual(parse_search_selection("1, 2, 1", 10), [1, 2])

    def test_parse_search_selection_invalid(self):
        self.assertEqual(parse_search_selection("", 10), [])
        self.assertEqual(parse_search_selection("hello world", 10), [])
        self.assertEqual(parse_search_selection("https://dropmms.com", 10), [])

    def test_format_clean_search_results_page(self):
        items = [
            {"title": "Sample Topic 1", "date_ist": "22 Nov 2026, 06:00 PM IST"},
            {"title": "Sample Topic 2", "date_ist": "22 Nov 2026, 05:00 PM IST"},
        ]
        card = format_clean_search_results_page(
            query="dance",
            scope_name="Lesbian Videos",
            page=1,
            total_pages=5,
            total_count=50,
            items=items,
            delivered_indices={1},
        )
        self.assertIn("Lesbian Videos Search Results", card)
        self.assertIn("dance", card)
        self.assertIn("1.</b> Sample Topic 1", card)
        self.assertIn("✅ <i>(Delivered)</i>", card)
        self.assertIn("2.</b> Sample Topic 2", card)
        self.assertIn("How to Extract:", card)

    def test_format_search_completion_card(self):
        items = [
            {"title": "Sample Topic 1", "date_ist": "22 Nov 2026, 06:00 PM IST"},
            {"title": "Sample Topic 2", "date_ist": "22 Nov 2026, 05:00 PM IST"},
        ]
        card = format_search_completion_card(
            delivered_summary="1 topic(s)",
            query="dance",
            scope_name="DropMMS",
            page=1,
            total_pages=3,
            total_count=30,
            items=items,
            delivered_indices={1},
        )
        self.assertIn("✅ <b>Delivered:</b> 1 topic(s)", card)
        self.assertIn("1.</b> Sample Topic 1", card)
        self.assertIn("✅ <i>(Delivered)</i>", card)
        self.assertIn("💡 Type another number", card)

    def test_build_search_results_clean_keyboard(self):
        # Page 1 of 3: Next button + Page counter, Back, Cancel
        kb = build_search_results_clean_keyboard(
            page=1,
            total_pages=3,
            page_callback_prefix="sp_fp:fm:all",
            back_callback="sp_choose:fm",
        )
        self.assertEqual(len(kb.inline_keyboard), 2)
        # Row 1: [📄 1/3, Next ➡️]
        self.assertEqual(len(kb.inline_keyboard[0]), 2)
        self.assertEqual(kb.inline_keyboard[0][0].text, "📄 1/3")
        self.assertEqual(kb.inline_keyboard[0][1].text, "Next ➡️")
        self.assertEqual(kb.inline_keyboard[0][1].callback_data, "sp_fp:fm:all:2")
        # Row 2: [🔙 Back, ❌ Cancel]
        self.assertEqual(len(kb.inline_keyboard[1]), 2)
        self.assertEqual(kb.inline_keyboard[1][0].text, "🔙 Back")
        self.assertEqual(kb.inline_keyboard[1][1].text, "❌ Cancel")

        # Page 2 of 3: Both Prev, Page counter, and Next
        kb_mid = build_search_results_clean_keyboard(
            page=2,
            total_pages=3,
            page_callback_prefix="sp_fp:fm:2",
            back_callback="sp_cat:123",
        )
        self.assertEqual(len(kb_mid.inline_keyboard), 2)
        self.assertEqual(len(kb_mid.inline_keyboard[0]), 3)
        self.assertEqual(kb_mid.inline_keyboard[0][0].text, "⬅️ Previous")
        self.assertEqual(kb_mid.inline_keyboard[0][1].text, "📄 2/3")
        self.assertEqual(kb_mid.inline_keyboard[0][2].text, "Next ➡️")

    def test_invision_search_forum_advanced_scoping(self):
        with patch("engines.invision._fetch_soup") as mock_fetch:
            html = """
            <html>
                <body data-pageapp="forums">
                    <h1>1 results</h1>
                    <ol class="ipsStream">
                        <li class="ipsStreamItem" data-role="activityItem">
                            <h2 class="ipsStreamItem_title"><a href="https://dropmms.com/topic/101-test/">Scoped Test Topic</a></h2>
                            <time datetime="2026-11-22T10:00:00Z"></time>
                        </li>
                    </ol>
                </body>
            </html>
            """
            mock_fetch.return_value = BeautifulSoup(html, "html.parser")

            res = search_forum_advanced(
                query="video",
                page=1,
                limit=10,
                base_url="https://dropmms.com",
                forum_id=4,
            )
            # Verify URL passed to _fetch_soup includes node scoping
            called_url = mock_fetch.call_args[0][0]
            self.assertIn("nodes[4]=1", called_url)
            self.assertEqual(len(res["topics"]), 1)
            self.assertEqual(res["topics"][0]["title"], "Scoped Test Topic")


if __name__ == "__main__":
    unittest.main()
