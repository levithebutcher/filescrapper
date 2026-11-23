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

        # 5. Unsupported URL
        self.assertIsNone(get_engine_for_url("https://unsupported-site.com/video/123"))

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


if __name__ == "__main__":
    unittest.main()
