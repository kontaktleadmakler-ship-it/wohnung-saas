# scrapers/meinestadt.py
import re
from .base import BaseScraper
from .models import Listing, SearchParams

BASE_URL = "https://immobilien.meinestadt.de"


class MeinestadtScraper(BaseScraper):
    SOURCE_KEY = "meinestadt"
    SOURCE_LABEL = "meinestadt.de"
    SUPPORTS_NATIONWIDE = False  # Plattform ist strukturell auf Ort/Stadt ausgelegt

    def build_search_urls(self, params: SearchParams) -> list[str]:
        # meinestadt.de braucht immer einen Ort -> "bundesweit" wird über eine
        # kuratierte Liste von Großstädten je Bundesland angenähert (siehe regions.py,
        # dort CITY_SAMPLES[region_code] = ["muenchen", "nuernberg", ...]).
        from .regions import resolve_region_codes, CITY_SAMPLES
        codes = resolve_region_codes(params.region_codes) if not params.nationwide else list(CITY_SAMPLES)
        cities = {c for code in codes for c in CITY_SAMPLES.get(code, [])}
        return [f"{BASE_URL}/{city}/wohnungen/mieten" for city in sorted(cities)]

    def parse_listing_cards(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        cards = []
        # TODO: Selektor gegen Live-DOM verifizieren, Struktur kann abweichen
        for card in soup.select("[data-testid='result-list-entry']"):
            link_el = card.select_one("a")
            if not link_el:
                continue
            cards.append({
                "href": link_el.get("href", ""),
                "title": (card.select_one("h2") or link_el).get_text(strip=True),
                "price_text": (card.select_one("[data-testid='price']") or {}).get_text()
                              if card.select_one("[data-testid='price']") else None,
                "meta_text": card.get_text(" ", strip=True),
            })
        return cards

    def normalize(self, raw: dict) -> Listing | None:
        if not raw.get("title") or not raw.get("href"):
            return None
        url = raw["href"] if raw["href"].startswith("http") else BASE_URL + raw["href"]
        rooms_match = re.search(r"(\d+([.,]\d)?)\s*Zi", raw["meta_text"])
        size_match = re.search(r"(\d+([.,]\d)?)\s*m²", raw["meta_text"])
        return Listing(
            source=self.SOURCE_KEY,
            external_id=url,   # meinestadt hat keine stabile numerische ID im HTML -> URL als ID
            url=url,
            title=raw["title"],
            rooms=float(rooms_match.group(1).replace(",", ".")) if rooms_match else None,
            size=float(size_match.group(1).replace(",", ".")) if size_match else None,
        )
