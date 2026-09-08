# scrapers/immonet.py (Gerüst)
#
# Praktisches Problem: gehört wie ImmoScout24 zur selben Unternehmensgruppe,
# oft ähnliche/gespiegelte Inserate wie auf Schwesterportalen. Vor Rollout prüfen,
# ob echte Zusatz-Abdeckung entsteht oder v. a. Duplikate von anderen Quellen.
from playwright.sync_api import sync_playwright
from .base import BaseScraper
from .models import Listing, SearchParams


class ImmonetScraper(BaseScraper):
    SOURCE_KEY = "immonet"
    SOURCE_LABEL = "Immonet"
    SUPPORTS_NATIONWIDE = True

    def fetch(self, url: str) -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=self.session.headers["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
            browser.close()
            return html

    def build_search_urls(self, params: SearchParams) -> list[str]:
        # Parameter vor Rollout gegen die Live-Seite verifizieren.
        if params.nationwide or not params.region_codes:
            return ["https://www.immonet.de/immobiliensuche/sel.do?suchart=miete&pageType=result"]
        return [
            f"https://www.immonet.de/immobiliensuche/sel.do?suchart=miete&pageType=result&region={code}"
            for code in params.region_codes
        ]

    def parse_listing_cards(self, html: str) -> list[dict]:
        raise NotImplementedError("Selektoren gegen aktuelles Live-DOM verifizieren")

    def normalize(self, raw: dict) -> Listing | None:
        raise NotImplementedError
