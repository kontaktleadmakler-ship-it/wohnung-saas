from __future__ import annotations

import re
from urllib.parse import quote_plus

from .base import PortalSpider


class KleinanzeigenSpider(PortalSpider):
    name = "kleinanzeigen"
    source_key = "kleinanzeigen"
    source_label = "eBay Kleinanzeigen"
    base_url = "https://www.kleinanzeigen.de"
    card_selectors = ("article.aditem", ".aditem", "li.ad-listitem", "article")
    link_selectors = ("a[href*='/s-anzeige/']", "a[href*='/s-wohnung']")

    def start_requests(self):
        yield from super().start_requests()

    def is_listing_href(self, href):
        return "/s-anzeige/" in href or "/s-wohnung" in href


class ImmoScout24Spider(PortalSpider):
    name = "immoscout24"
    source_key = "immoscout24"
    source_label = "ImmoScout24"
    base_url = "https://www.immobilienscout24.de"
    page_param = "pagenumber"
    card_selectors = ("article.result-list__listing", "div.result-list__listing", "li.result-list__listing", "article")
    link_selectors = ("a[href*='/expose/']", "a[href*='/expose']")

    def is_listing_href(self, href):
        return "/expose/" in href


class ImmoweltSpider(PortalSpider):
    name = "immowelt"
    source_key = "immowelt"
    source_label = "Immowelt"
    base_url = "https://www.immowelt.de"
    card_selectors = ("div[id^='listitem-']", "article[id^='listitem-']", "div.result-list-item", "article")
    link_selectors = ("a[href*='/immobilie/']", "a[href*='/expose/']", "a[href*='/angebot/']")

    def is_listing_href(self, href):
        return any(x in href for x in ("/immobilie/", "/expose/", "/angebot/"))


class ImmonetSpider(PortalSpider):
    name = "immonet"
    source_key = "immonet"
    source_label = "Immonet"
    base_url = "https://www.immonet.de"
    card_selectors = ("div.list-entry", "article.list-entry", "div[data-testid*='result' i]", "article")
    link_selectors = ("a[href*='/angebot/']", "a[href*='/expose/']")

    def is_listing_href(self, href):
        return "/angebot/" in href or "/expose/" in href


class WgGesuchtSpider(PortalSpider):
    name = "wg_gesucht"
    source_key = "wg_gesucht"
    source_label = "WG-Gesucht"
    base_url = "https://www.wg-gesucht.de"
    card_selectors = ("div.wgg_card", "div[id^='ad-']", "article", ".offer_list_item")
    link_selectors = ("a[href*='.html']", "a[href*='/wohnungen-in-']", "a[href]")

    def is_listing_href(self, href):
        return any(x in href for x in ("/angebot_", "/wohnungen-in-", "/1-zimmer-wohnungen/", "/2-zimmer-wohnungen/", "/3-zimmer-wohnungen/"))


class MeinestadtSpider(PortalSpider):
    name = "meinestadt"
    source_key = "meinestadt"
    source_label = "meinestadt.de"
    base_url = "https://immobilien.meinestadt.de"
    use_playwright = False
    card_selectors = ("[data-testid='result-list-entry']", "div.result-entry", "article")
    link_selectors = ("a[href]",)

    def is_listing_href(self, href):
        return "/immobil" in href or "/wohnung" in href


class KalaydoSpider(PortalSpider):
    name = "kalaydo"
    source_key = "kalaydo"
    source_label = "Kalaydo"
    base_url = "https://www.kalaydo.de"
    max_pages = 1
    card_selectors = ("div.result-list-entry", "article.result-list-entry", "div.result-item")
    link_selectors = ("a[href*='/immobilie/']", "a[href*='immobilie']")

    def is_listing_href(self, href):
        return "/immobilie/" in href and "/stellen" not in href and "/jobs" not in href


SPIDER_CLASSES = {
    cls.source_key: cls
    for cls in (
        KleinanzeigenSpider,
        ImmoScout24Spider,
        ImmoweltSpider,
        ImmonetSpider,
        WgGesuchtSpider,
        MeinestadtSpider,
        KalaydoSpider,
    )
}
