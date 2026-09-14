"""Basisklasse für alle Portal-Scraper. Nutzt Playwright (Portale sind
client-seitig gerendert) + BeautifulSoup zum Parsen. Fehlerbehandlung:
- HTTP 403/429/5xx und Timeouts werden mit exponentiellem Backoff retried
  (SCRAPE_RETRIES Versuche), danach wirft run() eine ScraperError, die der
  Pipeline pro Quelle einzeln abfängt (ein kaputtes Portal killt nicht den
  gesamten Scan-Zyklus).
- Portal-Struktur-Änderungen: die Card-/Link-Selektoren sind bewusst breit
  (mehrere Fallback-Selektoren + generische <a href>-Heuristik + JSON-LD-
  Fallback), damit kleinere HTML-Änderungen nicht sofort zu 0 Treffern führen.
"""
from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from .. import config
from ..models import Listing, SearchParams


class ScraperError(Exception):
    pass


class RetryableScrapeError(ScraperError):
    pass


class BaseScraper(ABC):
    SOURCE_KEY = ""
    SOURCE_LABEL = ""
    BASE_URL = ""

    CARD_SELECTORS: tuple[str, ...] = ()
    LINK_SELECTORS: tuple[str, ...] = ()
    PAGE_PARAM: str | None = "page"
    PAGE_START = 1

    COOKIE_SELECTORS = (
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Zustimmen')",
        "button[id*='accept' i]",
        "button[class*='accept' i]",
    )
    USER_AGENTS = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    )

    def __init__(self):
        self.log = logging.getLogger(f"scraper.{self.SOURCE_KEY}")

    @abstractmethod
    def build_search_urls(self, params: SearchParams) -> list[str]:
        raise NotImplementedError

    def is_listing_href(self, href: str) -> bool:
        return bool(re.search(r"/(?:expose|angebot|anzeige|wohnung|apartment)[/\-_0-9a-zA-Z]", href or "", re.I))

    def build_page_url(self, base_url: str, page: int) -> str | None:
        if not self.PAGE_PARAM or page <= self.PAGE_START:
            return base_url if page == self.PAGE_START else None
        parts = urlsplit(base_url)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != self.PAGE_PARAM]
        query.append((self.PAGE_PARAM, str(page)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    # -- Lauf ----------------------------------------------------------------
    def run(self, params: SearchParams) -> list[Listing]:
        base_urls = list(dict.fromkeys(self.build_search_urls(params)))
        if not base_urls:
            self.log.warning("Keine Such-URLs für %s", self.SOURCE_KEY)
            return []

        results: list[Listing] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = browser.new_context(
                locale="de-DE",
                user_agent=random.choice(self.USER_AGENTS),
                extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"},
            )
            context.set_default_timeout(config.SCRAPE_PAGE_TIMEOUT_MS)
            context.route("**/*", self._block_heavy_resources)

            try:
                page = context.new_page()
                for base_url in base_urls:
                    seen_hrefs: set[str] = set()
                    for page_num in range(self.PAGE_START, self.PAGE_START + config.SCRAPE_MAX_PAGES):
                        url = self.build_page_url(base_url, page_num)
                        if not url:
                            break
                        try:
                            self._polite_delay()
                            self._load_with_retry(page, url)
                            html = page.content()
                            cards = self.parse_listing_cards(html)
                            new_cards = [c for c in cards if c.get("href") and c["href"] not in seen_hrefs]
                            self.log.info("%s: Seite %d - %d Kandidaten (%d neu)", self.SOURCE_KEY, page_num, len(cards), len(new_cards))

                            if config.MAX_CANDIDATES_PER_SOURCE > 0:
                                remaining = config.MAX_CANDIDATES_PER_SOURCE - len(results)
                                if remaining <= 0:
                                    break
                                new_cards = new_cards[:remaining]

                            for raw in new_cards:
                                seen_hrefs.add(raw["href"])
                                try:
                                    item = self.normalize(raw, page_url=url)
                                    if item:
                                        results.append(item)
                                except Exception:
                                    self.log.exception("Normalisierung fehlgeschlagen: %s", raw.get("href"))

                            if page_num > self.PAGE_START and not new_cards:
                                break
                            if config.MAX_CANDIDATES_PER_SOURCE and len(results) >= config.MAX_CANDIDATES_PER_SOURCE:
                                break
                        except ScraperError:
                            # Portal für diese URL nicht erreichbar - Rest der Quellen wird trotzdem versucht.
                            self.log.exception("URL fehlgeschlagen, überspringe: %s", url)
                            break
            finally:
                context.close()
                browser.close()

        return self._dedupe(results)

    @staticmethod
    def _block_heavy_resources(route):
        if route.request.resource_type in {"image", "media", "font"}:
            return route.abort()
        return route.continue_()

    def _polite_delay(self):
        time.sleep(random.uniform(config.SCRAPE_DELAY_MIN, config.SCRAPE_DELAY_MAX))

    def _load_with_retry(self, page, url):
        last_exc = None
        for attempt in range(1, config.SCRAPE_RETRIES + 1):
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=config.SCRAPE_PAGE_TIMEOUT_MS)
                status = response.status if response else None
                if status in (403, 429) or (status and status >= 500):
                    raise RetryableScrapeError(f"HTTP {status} für {url}")
                self._accept_cookies(page)
                page.wait_for_timeout(1200)
                return
            except (RetryableScrapeError, PlaywrightTimeoutError) as exc:
                last_exc = exc
                if attempt >= config.SCRAPE_RETRIES:
                    break
                delay = 1.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.75)
                self.log.warning("Retry %d/%d für %s in %.1fs (%s)", attempt, config.SCRAPE_RETRIES, url, delay, exc)
                time.sleep(delay)
            except Exception as exc:  # Netzwerk-/Browserfehler
                last_exc = exc
                if attempt >= config.SCRAPE_RETRIES:
                    break
                time.sleep(1.5 * attempt)
        raise ScraperError(f"Scraping nach {config.SCRAPE_RETRIES} Versuchen fehlgeschlagen: {url}") from last_exc

    def _accept_cookies(self, page) -> None:
        for selector in self.COOKIE_SELECTORS:
            try:
                loc = page.locator(selector).first
                if loc.count() and loc.is_visible(timeout=400):
                    loc.click(timeout=1200)
                    return
            except Exception:
                continue

    # -- Parsing ---------------------------------------------------------------
    def parse_listing_cards(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        cards, seen = [], set()
        for selector in self.CARD_SELECTORS:
            for card in soup.select(selector):
                raw = self._extract_card(card)
                if raw.get("href") and raw["href"] not in seen:
                    seen.add(raw["href"])
                    cards.append(raw)
            if cards:
                break
        if not cards:
            cards = self._adaptive_extract(soup)
        return cards

    def _extract_card(self, card) -> dict:
        link = None
        for selector in self.LINK_SELECTORS:
            link = card.select_one(selector)
            if link:
                break
        if not link:
            link = card.select_one("a[href]")
        text = " ".join(card.stripped_strings)
        return {
            "href": link.get("href", "") if link else "",
            "title": self._first_text(card, ["h1", "h2", "h3", "[class*='title' i]"]) or text[:180],
            "text": text,
            "price_text": self._first_text(card, ["[class*='price' i]", "[aria-label*='€' i]"]),
            "rooms_text": self._first_text(card, ["[class*='room' i]"]),
            "size_text": self._first_text(card, ["[class*='area' i]", "[class*='size' i]"]),
            "location": self._first_text(card, ["[class*='address' i]", "[class*='location' i]"]),
        }

    @staticmethod
    def _first_text(node, selectors):
        for selector in selectors:
            try:
                el = node.select_one(selector)
                if el:
                    value = el.get("aria-label") or el.get_text(" ", strip=True)
                    if value:
                        return value
            except Exception:
                continue
        return None

    def _adaptive_extract(self, soup: BeautifulSoup) -> list[dict]:
        """Fallback, falls die CARD_SELECTORS wegen einer Portal-Änderung
        nichts mehr treffen: sucht generisch nach Wohnungs-Links."""
        candidates, seen = [], set()
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not self.is_listing_href(href):
                continue
            key = href.split("#")[0]
            if key in seen:
                continue
            seen.add(key)
            node, best = a, a.parent
            for _ in range(4):
                if not node.parent:
                    break
                node = node.parent
                txt = " ".join(node.stripped_strings)
                if "€" in txt and ("zimmer" in txt.lower() or "wohnung" in txt.lower()):
                    best = node
            candidates.append(self._extract_card(best))
        return candidates[:150]

    def normalize(self, raw: dict, page_url: str = "") -> Listing | None:
        href = raw.get("href")
        if not href or not self.is_listing_href(href):
            return None
        url = urljoin(page_url or self.BASE_URL, href)
        external_id = self._extract_external_id(url)
        if not external_id:
            return None

        title = (raw.get("title") or "").strip() or (raw.get("text") or "")[:180]
        text = raw.get("text") or ""
        price, price_total = self._extract_prices(raw.get("price_text"), text)

        return Listing(
            source=self.SOURCE_KEY,
            external_id=external_id,
            url=url,
            title=title[:500],
            description=text[:3000],
            price=price,
            price_total=price_total,
            rooms=self._extract_rooms(raw.get("rooms_text"), text),
            size=self._extract_size(raw.get("size_text"), text),
            address=raw.get("location") or self._extract_location(text),
            raw=raw,
        )

    @staticmethod
    def _extract_external_id(url: str) -> str | None:
        path = urlsplit(url).path.rstrip("/")
        m = re.search(r"(?:expose|angebot|anzeige|id)[^/]*[/-]([A-Za-z0-9_-]{4,})$", path, re.I)
        if m:
            return m.group(1)
        parts = [p for p in path.split("/") if p]
        return parts[-1] if parts else None

    @staticmethod
    def _numbers(text):
        return [float(x.replace(".", "").replace(",", ".")) for x in re.findall(r"\d+(?:\.\d{3})*(?:,\d+)?", text or "")]

    def _extract_prices(self, price_text, text):
        s = price_text or text or ""
        warm = None
        m = re.search(r"(?:warmmiete|gesamtmiete)[^\d]{0,25}([\d.]+(?:,\d+)?)\s*€", s, re.I)
        if m:
            warm = float(m.group(1).replace(".", "").replace(",", "."))
        cold = None
        m = re.search(r"(?:kaltmiete|grundmiete)[^\d]{0,25}([\d.]+(?:,\d+)?)\s*€", s, re.I)
        if m:
            cold = float(m.group(1).replace(".", "").replace(",", "."))
        elif nums := self._numbers(s):
            cold = nums[0]
        return cold, warm

    @staticmethod
    def _extract_rooms(specific, text):
        s = specific or text or ""
        m = re.search(r"([0-9]+(?:[,.][0-9]+)?)\s*(?:-|bis)?\s*Zi(?:mmer)?\.?\b", s, re.I)
        return float(m.group(1).replace(",", ".")) if m else None

    @staticmethod
    def _extract_size(specific, text):
        s = specific or text or ""
        m = re.search(r"([0-9]{1,4}(?:[,.][0-9]+)?)\s*(?:m²|m2|qm)\b", s, re.I)
        return float(m.group(1).replace(",", ".")) if m else None

    @staticmethod
    def _extract_location(text):
        m = re.search(r"\b(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .-]{2,60})\b", text or "")
        return f"{m.group(1)} {m.group(2).strip()}" if m else None

    @staticmethod
    def _dedupe(items):
        out, seen = [], set()
        for item in items:
            key = (item.source, item.external_id or item.url)
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out
