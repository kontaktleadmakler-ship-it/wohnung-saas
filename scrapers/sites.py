from __future__ import annotations

from urllib.parse import quote_plus, urlsplit

from .base import BaseScraper
from .models import SearchParams


def locs(params):
    # Nationwide wird absichtlich nicht zu Berlin zurückgestuft. Das Suchgebiet
    # wird ausschließlich über SearchParams.nationwide gesteuert.
    if params.nationwide:
        return []
    return params.locations or (["Berlin"] if "BE" in params.region_codes else [])


class KleinanzeigenScraper(BaseScraper):
    SOURCE_KEY = "kleinanzeigen"
    SOURCE_LABEL = "eBay Kleinanzeigen"
    BASE_URL = "https://www.kleinanzeigen.de"
    CARD_SELECTORS = ("article.aditem", ".aditem", "li.ad-listitem", "article[data-testid*='ad' i]")
    LINK_SELECTORS = ("a.ellipsis", "a[href*='/s-anzeige/']", "a[href*='/s-wohnung']", "a[href]")

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/s-wohnung-mieten/c203"]
        out = []
        for location in locs(p):
            slug = quote_plus(location.lower()).replace("+", "-")
            out.append(f"{self.BASE_URL}/s-wohnung-mieten/{slug}/c203")
        return out[:8]

    def build_page_url(self, base_url, page):
        # Kleinanzeigen verwendet seite:N im Pfad. Der generische ?page=N-
        # Fallback bleibt für fremde Test-/Custom-URLs erhalten.
        parts = urlsplit(base_url)
        if "kleinanzeigen.de" not in parts.netloc.lower() or "/c203" not in parts.path:
            return super().build_page_url(base_url, page)
        if page <= self.PAGE_START:
            return base_url
        path = parts.path
        path = __import__("re").sub(r"/seite:\d+(?=/|$)", "", path, flags=__import__("re").I)
        marker = "/c203"
        idx = path.lower().rfind(marker.lower())
        if idx < 0:
            return super().build_page_url(base_url, page)
        path = path[:idx] + f"/seite:{page}" + path[idx:]
        return parts._replace(path=path).geturl()

    def is_listing_href(self, href):
        return "/s-anzeige/" in href or "/s-wohnung" in href


class ImmoScout24Scraper(BaseScraper):
    SOURCE_KEY = "immoscout24"
    SOURCE_LABEL = "ImmoScout24"
    BASE_URL = "https://www.immobilienscout24.de"
    CARD_SELECTORS = ("article.result-list__listing", "div.result-list__listing", "li.result-list__listing", "article[data-testid*='result' i]")
    LINK_SELECTORS = ("a[href*='/expose/']", "a[href*='/expose']", "a[href]")
    PAGE_PARAM = "pagenumber"

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/Suche/de/wohnung-mieten?geo=de"]
        out = []
        for location in locs(p):
            out.append(f"{self.BASE_URL}/Suche/de/{quote_plus(location.lower())}/wohnung-mieten")
        return out[:8]

    def is_listing_href(self, href):
        return "/expose/" in href


class ImmoweltScraper(BaseScraper):
    SOURCE_KEY = "immowelt"
    SOURCE_LABEL = "Immowelt"
    BASE_URL = "https://www.immowelt.de"
    CARD_SELECTORS = ("article", "div[data-testid*='result' i]", "div[class*='Estate' i]", "div[class*='ListItem' i]")
    LINK_SELECTORS = ("a[href*='/expose/']", "a[href*='/angebot/']", "a[href]")

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/suche/mieten/wohnung/deutschland"]
        out = []
        for location in locs(p):
            slug = quote_plus(location.lower()).replace("+", "-")
            out.append(f"{self.BASE_URL}/suche/mieten/wohnung/{slug}")
        return out[:8]

    def is_listing_href(self, href):
        return "/expose/" in href or "/angebot/" in href


class ImmonetScraper(BaseScraper):
    SOURCE_KEY = "immonet"
    SOURCE_LABEL = "Immonet"
    BASE_URL = "https://www.immonet.de"
    CARD_SELECTORS = ("div.list-entry", "article.list-entry", "div[data-testid*='result' i]", "article")
    LINK_SELECTORS = ("a[href*='/angebot/']", "a[href*='/expose/']", "a[href]")

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/immobiliensuche/sel.do?suchart=miete&location=Deutschland"]
        out = []
        for location in locs(p):
            out.append(f"{self.BASE_URL}/immobiliensuche/sel.do?suchart=miete&location={quote_plus(location)}")
        return out[:8]

    def is_listing_href(self, href):
        return "/angebot/" in href or "/expose/" in href


class WgGesuchtScraper(BaseScraper):
    SOURCE_KEY = "wg_gesucht"
    SOURCE_LABEL = "WG-Gesucht"
    BASE_URL = "https://www.wg-gesucht.de"
    CARD_SELECTORS = ("div.wgg_card", "div[id^='ad-']", "article", ".offer_list_item")
    LINK_SELECTORS = ("a[href*='.html']", "a[href*='/wohnungen-in-']", "a[href]")

    def build_search_urls(self, p):
        if p.nationwide:
            # Kein belastbarer deutschlandweiter Wohnungs-Endpoint bekannt;
            # bewusst keine Berlin-Fallback-Suche bei DE-Profilen.
            return []
        out = []
        for location in locs(p):
            slug = location.replace(" ", "-")
            out.append(f"{self.BASE_URL}/wohnungen-in-{slug}.html")
            out.append(f"{self.BASE_URL}/1-zimmer-wohnungen/{quote_plus(location.lower())}")
        return out[:8]

    def is_listing_href(self, href):
        return any(x in href for x in ("/angebot_", "/wohnungen-in-", "/1-zimmer-wohnungen/", "/2-zimmer-wohnungen/", "/3-zimmer-wohnungen/"))


class MeinestadtScraper(BaseScraper):
    SOURCE_KEY = "meinestadt"
    SOURCE_LABEL = "meinestadt.de"
    BASE_URL = "https://www.meinestadt.de"
    CARD_SELECTORS = ("article", "li[data-testid*='result' i]", "div[data-testid*='estate' i]", "div[class*='result' i]")
    LINK_SELECTORS = ("a[href*='/immobilien/']", "a[href]")

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/deutschland/immobilien/wohnungen"]
        out = []
        for location in locs(p):
            slug = quote_plus(location.lower()).replace("+", "-")
            out.append(f"{self.BASE_URL}/{slug}/immobilien/wohnungen")
        return out[:8]

    def is_listing_href(self, href):
        return "/immobilien/" in href and ("wohnung" in href.lower() or "angebot" in href.lower() or "miete" in href.lower())


class KalaydoScraper(BaseScraper):
    SOURCE_KEY = "kalaydo"
    SOURCE_LABEL = "Kalaydo"
    BASE_URL = "https://www.kalaydo.de"
    CARD_SELECTORS = ("article", "div[data-testid*='result' i]")
    LINK_SELECTORS = ("a[href]",)
    MAX_PAGES = 1

    def build_search_urls(self, p):
        # Kalaydo ist aktuell primär eine Jobbörse; keine erfundene Immobiliensuche.
        return [self.BASE_URL + "/immobilien/"]

    def run(self, params):
        try:
            return super().run(params)
        except Exception:
            self.log.exception("Kalaydo aktuell ohne öffentlich verifizierte Wohnimmobilien-Suche")
            return []

    def is_listing_href(self, href):
        return "/immobilien/" in href and "/stellen" not in href and "/jobs" not in href


SOURCE_CLASSES = [
    KleinanzeigenScraper,
    ImmoScout24Scraper,
    ImmonetScraper,
    ImmoweltScraper,
    KalaydoScraper,
    WgGesuchtScraper,
    MeinestadtScraper,
]
