# scrapers/immoscout24.py (Gerüst)
#
# Praktisches Problem: Aktive Bot-Erkennung (Datadome-artig), Ergebnisse teils
# clientseitig nachgeladen. AGB verbieten Scraping explizit -- rechtliches Risiko
# am höchsten dieser Liste. Vor Rollout: robots.txt/AGB prüfen, Fixture-HTML holen,
# Selektoren gegen Fixture entwickeln, mit niedriger Frequenz testen.
from playwright.sync_api import sync_playwright
from .base import BaseScraper
from .models import Listing, SearchParams


class ImmoScout24Scraper(BaseScraper):
    SOURCE_KEY = "immoscout24"
    SOURCE_LABEL = "ImmobilienScout24"
    SUPPORTS_NATIONWIDE = True

    def fetch(self, url: str) -> str:
        # Overridet BaseScraper.fetch(): echter Browser-Kontext statt requests,
        # weil Ergebnisse clientseitig nachgeladen werden und Anti-Bot-Checks greifen.
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=self.session.headers["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
            browser.close()
            return html

    def build_search_urls(self, params: SearchParams) -> list[str]:
        # geo="de" ist der ImmoScout24-Parameter fürs gesamte Bundesgebiet (Stand heute --
        # Portal-Parameter ändern sich, vor Rollout gegen die Live-Seite verifizieren)
        if params.nationwide or not params.region_codes:
            return ["https://www.immobilienscout24.de/Suche/de/wohnung-mieten?geo=de"]
        return [
            f"https://www.immobilienscout24.de/Suche/de/{code.lower()}/wohnung-mieten"
            for code in params.region_codes
        ]

    def parse_listing_cards(self, html: str) -> list[dict]:
        raise NotImplementedError("Selektoren gegen aktuelles Live-DOM verifizieren")

    def normalize(self, raw: dict) -> Listing | None:
        raise NotImplementedError
