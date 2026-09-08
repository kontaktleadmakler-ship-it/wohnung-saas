# scrapers/kalaydo.py (Gerüst)
#
# Praktisches Problem: regional (Rheinland/Ruhrgebiet) stärker vertreten als bundesweit.
# SUPPORTS_NATIONWIDE = False, Region-Fallback über Bundesländer.
from playwright.sync_api import sync_playwright
from .base import BaseScraper
from .models import Listing, SearchParams
from .regions import resolve_region_codes, BUNDESLAENDER


class KalaydoScraper(BaseScraper):
    SOURCE_KEY = "kalaydo"
    SOURCE_LABEL = "Kalaydo"
    SUPPORTS_NATIONWIDE = False

    def fetch(self, url: str) -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=self.session.headers["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
            browser.close()
            return html

    def build_search_urls(self, params: SearchParams) -> list[str]:
        # Kalaydo ist regional (Rheinland/Ruhrgebiet) am stärksten -- "bundesweit" wird
        # hier über alle Bundesländer iteriert. Pfad-Struktur vor Rollout gegen die
        # Live-Seite verifizieren.
        codes = list(BUNDESLAENDER) if params.nationwide else resolve_region_codes(params.region_codes)
        return [
            f"https://www.kalaydo.de/immobilien/wohnungen/mieten/{code.lower()}/"
            for code in codes
            if code in BUNDESLAENDER
        ]

    def parse_listing_cards(self, html: str) -> list[dict]:
        raise NotImplementedError("Selektoren gegen aktuelles Live-DOM verifizieren")

    def normalize(self, raw: dict) -> Listing | None:
        raise NotImplementedError
