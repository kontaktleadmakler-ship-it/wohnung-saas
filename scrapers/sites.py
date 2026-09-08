from __future__ import annotations

from urllib.parse import quote_plus, urlencode

from .base import BaseScraper
from .models import SearchParams, Listing


def locs(params):
    return params.locations or (["Berlin"] if "BE" in params.region_codes else [])


class KleinanzeigenScraper(BaseScraper):
    SOURCE_KEY = "kleinanzeigen"; SOURCE_LABEL = "eBay Kleinanzeigen"; BASE_URL = "https://www.kleinanzeigen.de"
    CARD_SELECTORS = ("article.aditem", ".aditem", "li.ad-listitem", "article[data-testid*='ad' i]")
    LINK_SELECTORS = ("a.ellipsis", "a[href*='/s-anzeige/']", "a[href*='/s-wohnung']", "a[href]")
    def build_search_urls(self, p):
        out=[]
        for location in locs(p) or ["Deutschland"]:
            slug=quote_plus(location.lower()).replace("+","-")
            out.append(f"{self.BASE_URL}/s-wohnung-mieten/{slug}/c203")
        return out[:8]
    def is_listing_href(self, href): return "/s-anzeige/" in href or "/s-wohnung" in href


class ImmoScout24Scraper(BaseScraper):
    SOURCE_KEY = "immoscout24"; SOURCE_LABEL = "ImmoScout24"; BASE_URL = "https://www.immobilienscout24.de"
    CARD_SELECTORS = ("article.result-list__listing", "div.result-list__listing", "li.result-list__listing", "article[data-testid*='result' i]")
    LINK_SELECTORS = ("a[href*='/expose/']", "a[href*='/expose']", "a[href]")
    def build_search_urls(self, p):
        out=[]
        for location in locs(p) or ["Deutschland"]:
            if location.lower()=="deutschland":
                out.append(f"{self.BASE_URL}/Suche/de/wohnung-mieten?geo=de")
            else:
                out.append(f"{self.BASE_URL}/Suche/de/{quote_plus(location.lower())}/wohnung-mieten")
        return out[:8]
    def is_listing_href(self, href): return "/expose/" in href


class ImmoweltScraper(BaseScraper):
    SOURCE_KEY = "immowelt"; SOURCE_LABEL = "Immowelt"; BASE_URL = "https://www.immowelt.de"
    CARD_SELECTORS = ("article", "div[data-testid*='result' i]", "div[class*='Estate' i]", "div[class*='ListItem' i]")
    LINK_SELECTORS = ("a[href*='/expose/']", "a[href*='/angebot/']", "a[href]")
    def build_search_urls(self, p):
        out=[]
        for location in locs(p) or ["Berlin"]:
            slug=quote_plus(location.lower()).replace("+","-")
            # Current public result route; search pages may redirect to canonical city paths.
            out.append(f"{self.BASE_URL}/suche/mieten/wohnung/{slug}")
        return out[:8]
    def is_listing_href(self, href): return "/expose/" in href or "/angebot/" in href


class ImmonetScraper(BaseScraper):
    SOURCE_KEY = "immonet"; SOURCE_LABEL = "Immonet"; BASE_URL = "https://www.immonet.de"
    CARD_SELECTORS = ("div.list-entry", "article.list-entry", "div[data-testid*='result' i]", "article")
    LINK_SELECTORS = ("a[href*='/angebot/']", "a[href*='/expose/']", "a[href]")
    def build_search_urls(self, p):
        out=[]
        for location in locs(p) or ["Deutschland"]:
            q=quote_plus(location)
            out.append(f"{self.BASE_URL}/immobiliensuche/sel.do?suchart=miete&location={q}")
        return out[:8]
    def is_listing_href(self, href): return "/angebot/" in href or "/expose/" in href


class WgGesuchtScraper(BaseScraper):
    SOURCE_KEY = "wg_gesucht"; SOURCE_LABEL = "WG-Gesucht"; BASE_URL = "https://www.wg-gesucht.de"
    CARD_SELECTORS = ("div.wgg_card", "div[id^='ad-']", "article", ".offer_list_item")
    LINK_SELECTORS = ("a[href*='.html']", "a[href*='/wohnungen-in-']", "a[href]")
    def build_search_urls(self, p):
        out=[]
        for location in locs(p) or ["Berlin"]:
            slug=location.replace(" ","-")
            out.append(f"{self.BASE_URL}/wohnungen-in-{slug}.html")
            out.append(f"{self.BASE_URL}/1-zimmer-wohnungen/{quote_plus(location.lower())}")
        return out[:8]
    def is_listing_href(self, href): return any(x in href for x in ("/angebot_", "/wohnungen-in-", "/1-zimmer-wohnungen/", "/2-zimmer-wohnungen/", "/3-zimmer-wohnungen/"))


class MeinestadtScraper(BaseScraper):
    SOURCE_KEY = "meinestadt"; SOURCE_LABEL = "meinestadt.de"; BASE_URL = "https://www.meinestadt.de"
    CARD_SELECTORS = ("article", "li[data-testid*='result' i]", "div[data-testid*='estate' i]", "div[class*='result' i]")
    LINK_SELECTORS = ("a[href*='/immobilien/']", "a[href]")
    def build_search_urls(self, p):
        out=[]
        for location in locs(p) or ["Berlin"]:
            slug=quote_plus(location.lower()).replace("+","-")
            out.append(f"{self.BASE_URL}/{slug}/immobilien/wohnungen")
        return out[:8]
    def is_listing_href(self, href): return "/immobilien/" in href and ("wohnung" in href.lower() or "angebot" in href.lower() or "miete" in href.lower())


class KalaydoScraper(BaseScraper):
    SOURCE_KEY = "kalaydo"; SOURCE_LABEL = "Kalaydo"; BASE_URL = "https://www.kalaydo.de"
    CARD_SELECTORS = ("article", "div[data-testid*='result' i]")
    LINK_SELECTORS = ("a[href]",)
    def build_search_urls(self, p):
        # Kalaydo's current public site is a jobs marketplace; no current residential
        # rental category is exposed. Keep the source registered and health-checked,
        # but never manufacture real-estate URLs/results.
        return [self.BASE_URL + "/immobilien/"]
    def run(self, params):
        try:
            # Base runner will safely return zero if the legacy route redirects/404s.
            return super().run(params)
        except Exception:
            self.log.exception("Kalaydo currently has no public residential rental section")
            return []
    def is_listing_href(self, href): return "/immobilien/" in href and "/stellen" not in href and "/jobs" not in href

SOURCE_CLASSES = [KleinanzeigenScraper, ImmoScout24Scraper, ImmonetScraper, ImmoweltScraper, KalaydoScraper, WgGesuchtScraper, MeinestadtScraper]
