# scrapers/wg_gesucht.py (Gerüst)
#
# Praktisches Problem: Suche ist stark auf Stadt/Umkreis ausgelegt, kein "ganz DE".
# Ansatz: SUPPORTS_NATIONWIDE = False, über Städteliste iterieren wie bei meinestadt.de.
from playwright.sync_api import sync_playwright
from .base import BaseScraper
from .models import Listing, SearchParams
from .regions import resolve_region_codes, CITY_SAMPLES


class WgGesuchtScraper(BaseScraper):
    SOURCE_KEY = "wg_gesucht"
    SOURCE_LABEL = "WG-Gesucht"
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
        # Stadtbasierte Näherung an "bundesweit" wie bei meinestadt.de.
        # Parameter/Pfad-Struktur vor Rollout gegen die Live-Seite verifizieren.
        codes = list(CITY_SAMPLES) if params.nationwide else resolve_region_codes(params.region_codes)
        cities = {c for code in codes for c in CITY_SAMPLES.get(code, [])}
        return [f"https://www.wg-gesucht.de/wohnungen-in-{city}.html" for city in sorted(cities)]

    def parse_listing_cards(self, html: str) -> list[dict]:
        raise NotImplementedError("Selektoren gegen aktuelles Live-DOM verifizieren")

    def normalize(self, raw: dict) -> Listing | None:
        raise NotImplementedError
