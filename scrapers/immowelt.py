# scrapers/immowelt.py (Gerüst)
#
# Praktisches Problem: ähnlich wie ImmoScout24, teils JS-Rendering.
# Ansatz: Playwright, gleiche Vorsicht (niedrige Frequenz, robots.txt/AGB prüfen,
# Selektoren gegen ein gespeichertes Fixture entwickeln bevor produktiv geschaltet wird).
from playwright.sync_api import sync_playwright
from .base import BaseScraper
from .models import Listing, SearchParams


class ImmoweltScraper(BaseScraper):
    SOURCE_KEY = "immowelt"
    SOURCE_LABEL = "Immowelt"
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
            return ["https://www.immowelt.de/liste/deutschland/wohnungen/mieten"]
        return [
            f"https://www.immowelt.de/liste/{code.lower()}/wohnungen/mieten"
            for code in params.region_codes
        ]

    def parse_listing_cards(self, html: str) -> list[dict]:
        raise NotImplementedError("Selektoren gegen aktuelles Live-DOM verifizieren")

    def normalize(self, raw: dict) -> Listing | None:
        raise NotImplementedError
