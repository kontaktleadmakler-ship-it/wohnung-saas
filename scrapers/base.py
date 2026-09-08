# scrapers/base.py
import logging
import random
import time
from abc import ABC, abstractmethod

import requests

from .models import Listing, SearchParams


class ScraperError(Exception):
    """Für Fehler, die den Job abbrechen, aber nicht den ganzen Orchestrator-Lauf."""


class BaseScraper(ABC):
    SOURCE_KEY: str = ""          # z.B. "immoscout24" -- muss pro Subklasse gesetzt werden
    SOURCE_LABEL: str = ""        # Anzeigename fürs UI, z.B. "ImmobilienScout24"
    SUPPORTS_NATIONWIDE: bool = True   # kann die Plattform "ganz DE" in einer Query?
    REQUEST_DELAY_RANGE = (1.5, 4.0)   # Sekunden, zwischen einzelnen Requests derselben Quelle

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "de-DE,de;q=0.9",
        })
        self.log = logging.getLogger(f"scraper.{self.SOURCE_KEY}")

    @abstractmethod
    def build_search_urls(self, params: SearchParams) -> list[str]:
        """Liefert 1..n URLs, die zusammen den gewünschten Suchraum abdecken."""

    @abstractmethod
    def parse_listing_cards(self, html: str) -> list[dict]:
        """Extrahiert die Rohdaten je Karte aus einer Ergebnisseite. Plattform-spezifisch."""

    @abstractmethod
    def normalize(self, raw: dict) -> Listing | None:
        """Wandelt eine Roh-Karte in das einheitliche Listing-Modell um.
        Gibt None zurück, wenn die Karte nicht auswertbar ist (statt zu crashen)."""

    def fetch(self, url: str) -> str:
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text

    def run(self, params: SearchParams) -> list[Listing]:
        """Orchestriert fetch -> parse -> normalize für alle URLs dieser Quelle.
        Fehler auf URL-Ebene brechen NICHT den ganzen Lauf ab (siehe Anforderung 4)."""
        results: list[Listing] = []
        urls = self.build_search_urls(params)

        for url in urls:
            try:
                html = self.fetch(url)
                cards = self.parse_listing_cards(html)
                self.log.info("%d Karten gefunden (%s)", len(cards), url)
            except Exception:
                self.log.exception("Fehler beim Scrapen von %s", url)
                continue  # nächste URL versuchen, nicht den ganzen Job killen

            for card in cards:
                try:
                    listing = self.normalize(card)
                    if listing is not None:
                        results.append(listing)
                except Exception:
                    self.log.exception("Fehler beim Normalisieren einer Karte (%s)", url)
                    continue

            time.sleep(random.uniform(*self.REQUEST_DELAY_RANGE))

        return results
