# scrapers/meinestadt.py
import re
from bs4 import BeautifulSoup
from .base import BaseScraper
from .models import Listing, SearchParams
from .regions import resolve_region_codes, CITY_SAMPLES

BASE_URL = "https://immobilien.meinestadt.de"


class MeinestadtScraper(BaseScraper):
    SOURCE_KEY = "meinestadt"
    SOURCE_LABEL = "meinestadt.de"
    SUPPORTS_NATIONWIDE = False

    # fetch bleibt aus base (requests) – meinestadt ist nicht so JS-lastig
    def build_search_urls(self, params: SearchParams) -> list[str]:
        codes = list(CITY_SAMPLES) if params.nationwide else resolve_region_codes(params.region_codes)
        cities = {c for code in codes for c in CITY_SAMPLES.get(code, [])}
        return [f"{BASE_URL}/{city}/wohnungen/mieten" for city in sorted(cities)]

    def parse_listing_cards(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        cards = []
        # Mehrere Selektoren
        selectors = ["[data-testid='result-list-entry']", "div.result-entry", "article"]
        for selector in selectors:
            for card in soup.select(selector):
                link_el = card.select_one("a")
                if not link_el:
                    continue
                title_el = card.select_one("h2, h3, h4")
                price_el = card.select_one("[data-testid='price']")
                meta_el = card.select_one("[data-testid='meta']") or card
                location_el = card.select_one("[data-testid='location']")
                cards.append({
                    "href": link_el.get("href", ""),
                    "external_id": link_el.get("href", ""),
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "price_text": price_el.get_text(strip=True) if price_el else None,
                    "meta_text": meta_el.get_text(strip=True),
                    "location": location_el.get_text(strip=True) if location_el else None,
                })
            if cards:
                break
        return cards

    def normalize(self, raw: dict) -> Listing | None:
        if not raw.get("title") or not raw.get("href"):
            return None
        url = raw["href"] if raw["href"].startswith("http") else BASE_URL + raw["href"]
        price = self._parse_number(raw.get("price_text"))
        rooms = self._extract_rooms(raw.get("meta_text", ""))
        size = self._extract_size(raw.get("meta_text", ""))
        return Listing(
            source=self.SOURCE_KEY,
            external_id=url,
            url=url,
            title=raw["title"],
            price=price,
            rooms=rooms,
            size=size,
            address=raw.get("location"),
        )

    @staticmethod
    def _extract_rooms(meta_text: str):
        match = re.search(r"(\d+([.,]\d)?)\s*Zi", meta_text)
        if match:
            return float(match.group(1).replace(",", "."))
        return None

    @staticmethod
    def _extract_size(meta_text: str):
        match = re.search(r"(\d+([.,]\d)?)\s*m²", meta_text)
        if match:
            return float(match.group(1).replace(",", "."))
        return None

    @staticmethod
    def _parse_number(text: str):
        if not text:
            return None
        cleaned = re.sub(r"[^\d,\.]", "", text).replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
