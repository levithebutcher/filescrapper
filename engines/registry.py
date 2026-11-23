# engines/registry.py
"""
Central Registry for FileScrapper Scraping Engines.
Allows discovering, selecting, and dynamically adding new engines for websites.
"""

from typing import Optional
from engines.base import BaseEngine
from engines.invision import InvisionCommunityEngine
from engines.wordpress import WordPressLockerEngine
from engines.tube import MediaTubeEngine
from engines.livecam import LiveCamEngine


class EngineRegistry:
    """Registry maintaining active scraper engines."""

    def __init__(self):
        self._engines: list[BaseEngine] = []
        self._name_map: dict[str, BaseEngine] = {}

    def register(self, engine: BaseEngine) -> None:
        """Register a new engine instance."""
        self._engines.append(engine)
        self._name_map[engine.name.lower()] = engine

    def get_engine_for_url(self, url: str) -> Optional[BaseEngine]:
        """Find the matching engine for a given URL."""
        if not url or not isinstance(url, str):
            return None
        for engine in self._engines:
            if engine.is_supported_url(url):
                return engine
        return None

    def get_engine_by_name(self, name: str) -> Optional[BaseEngine]:
        """Find an engine by its name."""
        return self._name_map.get(name.lower().strip())

    def get_all_engines(self) -> list[BaseEngine]:
        """Return all registered engines."""
        return list(self._engines)

    def supported_domains(self) -> list[str]:
        """Return all supported domains across registered engines."""
        domains = []
        for engine in self._engines:
            domains.extend(engine.domains)
        return domains


# Global singleton registry pre-populated with standard engines
registry = EngineRegistry()

# 1. Invision Community IPS4 Forums (DropMMS, MMSTown)
registry.register(InvisionCommunityEngine())

# 2. WordPress Lockers & Tubes (Omaal63, DesiJugar, GulabiHub)
registry.register(WordPressLockerEngine())

# 3. Media Tube Engines (MMSVibex)
registry.register(MediaTubeEngine())

# 4. LiveCam Engine (LiveCamRips)
registry.register(LiveCamEngine())


def get_engine_for_url(url: str) -> Optional[BaseEngine]:
    """Helper shortcut to get engine for URL."""
    return registry.get_engine_for_url(url)
