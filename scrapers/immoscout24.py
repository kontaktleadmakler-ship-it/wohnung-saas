# scrapers/immoscout24.py
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from .base import BaseScraper
from .models import Listing, SearchParams


class ImmoScout24Scraper(BaseScraper):
    SOURCE_KEY = "immoscout24"
    SOURCE_LABEL = "ImmobilienScout24"
    SUPPORTS_NATIONWIDE = True

    def fetch(self, url: str) -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=self.session.headers["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=30000)
            # Cookie-Banner schließen (falls vorhanden)
            try:
                page.click("button[data-testid='consent-accept']", timeout=2000)
            except Exception:
                pass
            # Warten bis erste Karte erscheint
            try:
                page.wait_for_selector("div.result-list__listing, article.result-list__listing", timeout=10000)
            except Exception:
                pass
            html = page.content()
            browser.close()
            return html

    def build_search_urls(self, params: SearchParams) -> list[str]:
        if params.nationwide or not params.region_codes:
            return ["https://www.immobilienscout24.de/Suche/de/wohnung-mieten?geo=de"]
        return [
            f"https://www.immobilienscout24.de/Suche/de/{code.lower()}/wohnung-mieten"
            for code in params.region_codes
        ]

    def parse_listing_cards(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        cards = []
        # Mehrere Selektoren für Karten
        card_selectors = [
            "div.result-list__listing",
            "article.result-list__listing",
            "div.result-list__listing--item",
            "div#resultList .result-list__listing"
        ]
        for selector in card_selectors:
            for card in soup.select(selector):
                link_el = card.select_one("a[href*='/expose/']") or card.select_one("a[href*='expose']")
                if not link_el:
                    continue
                title_el = card.select_one("h5, h4, h3") or card.select_one("a[href*='/expose/']")
                price_el = card.select_one("div.result-list__listing--price, div[data-testid='price']")
                rooms_el = card.select_one("dd[data-testid='rooms'], span[data-testid='rooms']")
                size_el = card.select_one("dd[data-testid='area'], span[data-testid='area']")
                location_el = card.select_one("div.result-list__listing--address, div[data-testid='address']")
                # external_id aus URL
                href = link_el.get("href", "")
                m = re.search(r"expose/(\d+)", href)
                external_id = m.group(1) if m else href
                cards.append({
                    "href": href,
                    "external_id": external_id,
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "price_text": price_el.get_text(strip=True) if price_el else None,
                    "rooms_text": rooms_el.get_text(strip=True) if rooms_el else None,
                    "size_text": size_el.get_text(strip=True) if size_el else None,
                    "location": location_el.get_text(strip=True) if location_el else None,
                })
            if cards:
                break
        return cards

    def normalize(self, raw: dict) -> Listing | None:
        if not raw.get("title") or not raw.get("external_id"):
            return None
        price = self._parse_number(raw.get("price_text"))
        rooms = self._parse_number(raw.get("rooms_text"))
        size = self._parse_number(raw.get("size_text"))
        url = raw["href"] if raw["href"].startswith("http") else "https://www.immobilienscout24.de" + raw["href"]
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
