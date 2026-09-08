# scrapers/kleinanzeigen.py
import re
from .base import BaseScraper
from .models import Listing, SearchParams

BASE_URL = "https://www.kleinanzeigen.de"

# Kleinanzeigen unterstützt eine Kategorie-URL OHNE Ortsangabe -> nationwide nativ möglich.
NATIONWIDE_PATH = "/s-wohnung-mieten/c203"
# Fallback pro Bundesland, falls ein Profil gezielt einschränken will
# (Regionscode -> Ortsteil-Segment, l-Parameter von Kleinanzeigen)
REGION_PATHS = {
    "BY": "/s-wohnung-mieten/bayern/c203l5453",
    "BE": "/s-wohnung-mieten/berlin/c203l3331",
    # ... übrige Bundesländer analog ergänzen (l-IDs stammen aus der Kleinanzeigen-URL-Struktur)
}


def _to_number(text):
    if not text:
        return None
    cleaned = re.sub(r"[^\d,\.]", "", text).replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


class KleinanzeigenScraper(BaseScraper):
    SOURCE_KEY = "kleinanzeigen"
    SOURCE_LABEL = "eBay Kleinanzeigen"
    SUPPORTS_NATIONWIDE = True

    def build_search_urls(self, params: SearchParams) -> list[str]:
        if params.nationwide or not params.region_codes:
            return [BASE_URL + NATIONWIDE_PATH]
        return [
            BASE_URL + REGION_PATHS[r]
            for r in params.region_codes
            if r in REGION_PATHS
        ]

    def parse_listing_cards(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        cards = []
        for card in soup.select("article.aditem"):
            link_el = card.select_one("a.ellipsis")
            if not link_el:
                continue
            cards.append({
                "href": link_el.get("href", ""),
                "external_id": card.get("data-adid") or link_el.get("href", ""),
                "title": link_el.get_text(strip=True),
                "price_text": (card.select_one(".aditem-main--middle--price-shipping--price") or {}).get_text()
                              if card.select_one(".aditem-main--middle--price-shipping--price") else None,
                "details_text": (card.select_one(".aditem-main--middle--description") or card).get_text(" ", strip=True),
                "location": (card.select_one(".aditem-main--top--left") or card).get_text(strip=True),
            })
        return cards

    def normalize(self, raw: dict) -> Listing | None:
        if not raw.get("title"):
            return None
        href = raw["href"]
        url = BASE_URL + href if href.startswith("/") else href

        rooms_match = re.search(r"(\d+([.,]\d)?)\s*Zimmer", raw["details_text"])
        size_match = re.search(r"(\d+([.,]\d)?)\s*m²", raw["details_text"])

        return Listing(
            source=self.SOURCE_KEY,
            external_id=raw["external_id"],
            url=url,
            title=raw["title"],
            price=_to_number(raw.get("price_text")),
            rooms=_to_number(rooms_match.group(1)) if rooms_match else None,
            size=_to_number(size_match.group(1)) if size_match else None,
            address=raw.get("location"),
        )
