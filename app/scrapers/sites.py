"""Portal-spezifische Scraper. Auf 4 verbreitete Portale begrenzt (Annahme:
"minimal, ohne Overengineering" - weitere Portale lassen sich nach demselben
Muster als weitere BaseScraper-Subklasse ergänzen und in SOURCE_CLASSES
registrieren, ohne den Rest des Systems anzufassen)."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .base import BaseScraper

_UMLAUT_MAP = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}


def slugify_city(name: str) -> str:
    text = name.strip()
    for src, repl in _UMLAUT_MAP.items():
        text = text.replace(src, repl)
    text = re.sub(r"[\s.]+", "-", text.casefold())
    return re.sub(r"-+", "-", text).strip("-")


def _locations(params):
    return [] if params.nationwide else params.locations


class KleinanzeigenScraper(BaseScraper):
    SOURCE_KEY = "kleinanzeigen"
    SOURCE_LABEL = "eBay Kleinanzeigen"
    BASE_URL = "https://www.kleinanzeigen.de"
    CARD_SELECTORS = ("article.aditem", ".aditem", "li.ad-listitem")
    LINK_SELECTORS = ("a.ellipsis", "a[href*='/s-anzeige/']", "a[href]")

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/s-wohnung-mieten/c203"]
        return [f"{self.BASE_URL}/s-wohnung-mieten/{slugify_city(loc)}/c203" for loc in _locations(p)][:8]

    def build_page_url(self, base_url, page):
        if page <= self.PAGE_START:
            return base_url
        parts = urlsplit(base_url)
        idx = parts.path.lower().rfind("/c203")
        if idx < 0:
            return super().build_page_url(base_url, page)
        path = parts.path[:idx] + f"/seite:{page}" + parts.path[idx:]
        return parts._replace(path=path).geturl()

    def is_listing_href(self, href):
        return "/s-anzeige/" in href


class ImmoScout24Scraper(BaseScraper):
    SOURCE_KEY = "immoscout24"
    SOURCE_LABEL = "ImmoScout24"
    BASE_URL = "https://www.immobilienscout24.de"
    CARD_SELECTORS = ("article.result-list__listing", "div.result-list__listing")
    LINK_SELECTORS = ("a[href*='/expose/']", "a[href]")
    PAGE_PARAM = "pagenumber"

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/Suche/de/wohnung-mieten?geo=de"]
        return [f"{self.BASE_URL}/Suche/de/{slugify_city(loc)}/wohnung-mieten" for loc in _locations(p)][:8]

    def is_listing_href(self, href):
        return "/expose/" in href


class ImmoweltScraper(BaseScraper):
    SOURCE_KEY = "immowelt"
    SOURCE_LABEL = "Immowelt"
    BASE_URL = "https://www.immowelt.de"
    CARD_SELECTORS = ("article", "div[data-testid*='result' i]")
    LINK_SELECTORS = ("a[href*='/expose/']", "a[href]")

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/suche/mieten/wohnung/deutschland"]
        return [f"{self.BASE_URL}/suche/mieten/wohnung/{slugify_city(loc)}" for loc in _locations(p)][:8]

    def is_listing_href(self, href):
        return "/expose/" in href


class WgGesuchtScraper(BaseScraper):
    SOURCE_KEY = "wg_gesucht"
    SOURCE_LABEL = "WG-Gesucht"
    BASE_URL = "https://www.wg-gesucht.de"
    CARD_SELECTORS = ("div.wgg_card", "div[id^='ad-']", "article")
    LINK_SELECTORS = ("a[href*='.html']", "a[href]")

    def build_search_urls(self, p):
        if p.nationwide:
            return []  # kein belastbarer deutschlandweiter Endpoint bekannt
        return [f"{self.BASE_URL}/wohnungen-in-{slugify_city(loc)}.html" for loc in _locations(p)][:8]

    def is_listing_href(self, href):
        return "/wohnungen-in-" in href or "/angebot_" in href


SOURCE_CLASSES = [
    KleinanzeigenScraper,
    ImmoScout24Scraper,
    ImmoweltScraper,
    WgGesuchtScraper,
]
