# scrapers/kalaydo.py
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
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
        codes = list(BUNDESLAENDER) if params.nationwide else resolve_region_codes(params.region_codes)
        return [
            f"https://www.kalaydo.de/immobilien/wohnungen/mieten/{code.lower()}/"
            for code in codes
            if code in BUNDESLAENDER
        ]

    def parse_listing_cards(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        cards = []
        for card in soup.select("div.result-list-entry"):
            link_el = card.select_one("a[href*='/immobilie/']")
            if not link_el:
                continue
            title_el = card.select_one("h3, h2")
            price_el = card.select_one("div.list-entry__price")
            rooms_el = card.select_one("span[data-testid='rooms']")
            size_el = card.select_one("span[data-testid='area']")
            location_el = card.select_one("div.list-entry__location")
            cards.append({
                "href": link_el.get("href", ""),
                "external_id": re.search(r"immobilie/(\d+)", link_el.get("href", "")).group(1) if re.search(r"immobilie/(\d+)", link_el.get("href", "")) else "",
                "title": title_el.get_text(strip=True) if title_el else "",
                "price_text": price_el.get_text(strip=True) if price_el else None,
                "rooms_text": rooms_el.get_text(strip=True) if rooms_el else None,
                "size_text": size_el.get_text(strip=True) if size_el else None,
                "location": location_el.get_text(strip=True) if location_el else None,
            })
        return cards

    def normalize(self, raw: dict) -> Listing | None:
        if not raw.get("title") or not raw.get("external_id"):
            return None
        price = self._parse_number(raw.get("price_text"))
        rooms = self._parse_number(raw.get("rooms_text"))
        size = self._parse_number(raw.get("size_text"))
        url = raw["href"] if raw["href"].startswith("http") else "https://www.kalaydo.de" + raw["href"]
        return Listing(
            source=self.SOURCE_KEY,
            external_id=raw["external_id"],
            url=url,
            title=raw["title"],
            price=price,
            rooms=rooms,
            size=size,
            address=raw.get("location"),
        )

    @staticmethod
    def _parse_number(text: str):
        if not text:
            return None
        cleaned = re.sub(r"[^\d,\.]", "", text).replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
