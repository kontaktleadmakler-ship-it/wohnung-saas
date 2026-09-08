from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from abc import ABC, abstractmethod
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .models import Listing, SearchParams


class ScraperError(Exception):
    pass


class RetryableScrapeError(ScraperError):
    pass


class BaseScraper(ABC):
    SOURCE_KEY = ""
    SOURCE_LABEL = ""
    BASE_URL = ""

    REQUEST_DELAY_RANGE = (
        float(os.getenv("SCRAPE_DELAY_MIN", "0.8")),
        float(os.getenv("SCRAPE_DELAY_MAX", "1.8")),
    )
    WAIT_MS = int(os.getenv("SCRAPE_WAIT_MS", "1800"))
    PAGE_TIMEOUT_MS = int(os.getenv("SCRAPE_PAGE_TIMEOUT_MS", "30000"))
    RETRIES = max(1, int(os.getenv("SCRAPE_RETRIES", "3")))
    BACKOFF_BASE = float(os.getenv("SCRAPE_BACKOFF_BASE", "1.5"))

    USER_AGENTS = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    )

    CARD_SELECTORS: tuple[str, ...] = ()
    LINK_SELECTORS: tuple[str, ...] = ()
    COOKIE_SELECTORS: tuple[str, ...] = (
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Einverstanden')",
        "button:has-text('Zustimmen')",
        "button[id*='accept' i]",
        "button[class*='accept' i]",
        "button[data-testid*='accept' i]",
        "[role='button']:has-text('Akzeptieren')",
    )

    def __init__(self):
        self.log = logging.getLogger(f"scraper.{self.SOURCE_KEY}")

    @abstractmethod
    def build_search_urls(self, params: SearchParams) -> list[str]:
        raise NotImplementedError

    def run(self, params: SearchParams) -> list[Listing]:
        urls = list(dict.fromkeys(self.build_search_urls(params)))
        if not urls:
            self.log.warning("Keine Such-URLs für %s", self.SOURCE_KEY)
            return []

        results: list[Listing] = []

        with sync_playwright() as playwright:
            browser = None
            context = None
            try:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                context = browser.new_context(
                    locale="de-DE",
                    timezone_id="Europe/Berlin",
                    viewport={"width": 1365, "height": 900},
                    user_agent=random.choice(self.USER_AGENTS),
                    service_workers="block",
                )
                context.set_default_timeout(self.PAGE_TIMEOUT_MS)

                # Images/fonts/media are not needed for parsing and consume a lot
                # of bandwidth/RAM. Keep CSS and JS enabled because portals are
                # commonly client-rendered.
                context.route("**/*", self._route_lightweight_resources)

                for index, url in enumerate(urls):
                    try:
                        if index:
                            self._polite_delay()

                        page = context.new_page()
                        try:
                            self._load_with_retry(page, url)
                            html = page.content()
                            cards = self.parse_listing_cards(html, page)
                            self.log.info(
                                "%s: %d Kandidaten auf %s",
                                self.SOURCE_KEY,
                                len(cards),
                                url,
                            )
                            for raw in cards:
                                try:
                                    item = self.normalize(raw, page_url=url)
                                    if item and item.url:
                                        results.append(item)
                                except Exception:
                                    self.log.exception(
                                        "Normalisierung fehlgeschlagen: %s",
                                        raw.get("href"),
                                    )
                        finally:
                            page.close()
                    except Exception:
                        self.log.exception(
                            "URL fehlgeschlagen, nächste URL: %s", url
                        )
            finally:
                if context:
                    context.close()
                if browser:
                    browser.close()

        return self._dedupe(results)

    @staticmethod
    def _route_lightweight_resources(route):
        resource_type = route.request.resource_type
        if resource_type in {"image", "media", "font"}:
            return route.abort()
        return route.continue_()

    def _polite_delay(self):
        low, high = self.REQUEST_DELAY_RANGE
        if high < low:
            low, high = high, low
        time.sleep(random.uniform(max(0, low), max(0, high)))

    def _load_with_retry(self, page, url):
        last_exc = None

        for attempt in range(1, self.RETRIES + 1):
            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.PAGE_TIMEOUT_MS,
                )
                status = response.status if response else None

                if status in (403, 429):
                    raise RetryableScrapeError(
                        f"HTTP {status} für {url}"
                    )
                if status is not None and status >= 500:
                    raise RetryableScrapeError(
                        f"HTTP {status} für {url}"
                    )

                self._accept_cookies(page)

                if self.WAIT_MS > 0:
                    page.wait_for_timeout(self.WAIT_MS)

                self._accept_cookies(page)

                try:
                    page.wait_for_load_state(
                        "networkidle",
                        timeout=min(8000, self.PAGE_TIMEOUT_MS),
                    )
                except PlaywrightTimeoutError:
                    pass

                return

            except (RetryableScrapeError, PlaywrightTimeoutError) as exc:
                last_exc = exc
                if attempt >= self.RETRIES:
                    break

                delay = self.BACKOFF_BASE * (2 ** (attempt - 1))
                delay += random.uniform(0, 0.75)
                self.log.warning(
                    "Retry %d/%d für %s nach %.1fs: %s",
                    attempt,
                    self.RETRIES,
                    url,
                    delay,
                    exc,
                )
                time.sleep(delay)

            except Exception as exc:
                # Browser/network failures are retried too, but ordinary parser
                # errors are not swallowed here.
                last_exc = exc
                if attempt >= self.RETRIES:
                    break
                delay = self.BACKOFF_BASE * (2 ** (attempt - 1))
                delay += random.uniform(0, 0.75)
                self.log.warning(
                    "Netzwerkfehler; Retry %d/%d für %s nach %.1fs: %s",
                    attempt,
                    self.RETRIES,
                    url,
                    delay,
                    exc,
                )
                time.sleep(delay)

        raise ScraperError(
            f"Scraping nach {self.RETRIES} Versuchen fehlgeschlagen: {url}"
        ) from last_exc

    def _accept_cookies(self, page) -> None:
        for selector in self.COOKIE_SELECTORS:
            try:
                loc = page.locator(selector).first
                if loc.count() and loc.is_visible(timeout=500):
                    loc.click(timeout=1500)
                    self.log.info(
                        "Cookie-Banner akzeptiert (%s)", selector
                    )
                    return
            except Exception:
                continue

    def parse_listing_cards(self, html: str, page=None) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        cards = []
        seen = set()

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

        return self._merge_jsonld(soup, cards)

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
            "title": self._first_text(
                card,
                [
                    "h1", "h2", "h3", "h4", "h5",
                    "[class*='title' i]",
                    "[data-testid*='title' i]",
                ],
            ) or text[:180],
            "text": text,
            "price_text": self._first_text(
                card,
                [
                    "[class*='price' i]",
                    "[data-testid*='price' i]",
                    "[aria-label*='€' i]",
                ],
            ),
            "rooms_text": self._first_text(
                card,
                ["[class*='room' i]", "[data-testid*='room' i]"],
            ),
            "size_text": self._first_text(
                card,
                [
                    "[class*='area' i]",
                    "[class*='size' i]",
                    "[data-testid*='area' i]",
                ],
            ),
            "location": self._first_text(
                card,
                [
                    "[class*='address' i]",
                    "[class*='location' i]",
                    "[data-testid*='address' i]",
                ],
            ),
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
        candidates = []
        seen = set()

        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not self.is_listing_href(href):
                continue

            key = href.split("#")[0]
            if key in seen:
                continue
            seen.add(key)

            node = a
            best = a.parent
            for _ in range(5):
                if not node.parent:
                    break
                node = node.parent
                txt = " ".join(node.stripped_strings)
                if self._looks_like_listing_text(txt):
                    best = node

            candidates.append(self._extract_card(best))

        return candidates[:250]

    def _merge_jsonld(self, soup, cards):
        existing = {c.get("href") for c in cards if c.get("href")}

        for script in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(script.string or script.get_text())
            except Exception:
                continue

            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if not isinstance(obj, dict):
                    continue

                typ = str(obj.get("@type", ""))
                if (
                    typ.lower()
                    not in {"product", "offer", "apartment", "house", "realestate"}
                    and not obj.get("offers")
                ):
                    continue

                offers = obj.get("offers") or {}
                url = obj.get("url") or offers.get("url")
                if not url or url in existing or not self.is_listing_href(url):
                    continue

                price = offers.get("price") or obj.get("price")
                cards.append(
                    {
                        "href": url,
                        "title": obj.get("name", ""),
                        "text": obj.get("description", ""),
                        "price_text": str(price) if price else None,
                    }
                )
                existing.add(url)

        return cards

    @staticmethod
    def _looks_like_listing_text(text: str) -> bool:
        low = text.lower()
        return (
            ("€" in text or "m²" in low or "m2" in low)
            and (
                "zimmer" in low
                or "wohnung" in low
                or "apartment" in low
            )
        )

    def is_listing_href(self, href: str) -> bool:
        return bool(
            re.search(
                r"/(?:expose|angebot|anzeige|wohnung|immobil|apartment|wg-zimmer|rooms?|listing)[/\-_0-9a-zA-Z]",
                href or "",
                re.I,
            )
        )

    def normalize(self, raw: dict, page_url: str = "") -> Listing | None:
        href = raw.get("href")
        if not href or not self.is_listing_href(href):
            return None

        url = urljoin(page_url or self.BASE_URL, href)
        external_id = self.extract_external_id(url)
        if not external_id:
            return None

        title = (raw.get("title") or "").strip()
        text = raw.get("text") or ""
        price, price_total = self.extract_prices(
            raw.get("price_text"), text
        )
        rooms = self.extract_rooms(raw.get("rooms_text"), text)
        size = self.extract_size(raw.get("size_text"), text)

        if not title:
            title = text[:180]

        return Listing(
            source=self.SOURCE_KEY,
            external_id=external_id,
            url=url,
            title=title[:500],
            description=text[:4000],
            price=price,
            price_total=price_total,
            rooms=rooms,
            size=size,
            address=raw.get("location") or self.extract_location(text),
            raw=raw,
        )

    def extract_external_id(self, url: str) -> str | None:
        from urllib.parse import urlparse
        path = urlparse(url).path.rstrip("/")
        m = re.search(
            r"(?:expose|angebot|anzeige|listing|id|detail)[^/]*[/-]([A-Za-z0-9_-]{4,})$",
            path,
            re.I,
        )
        if m:
            return m.group(1)

        parts = [p for p in path.split("/") if p]
        return parts[-1] if parts else None

    @staticmethod
    def _numbers(text):
        return [
            float(x.replace(".", "").replace(",", "."))
            for x in re.findall(
                r"\d{1,3}(?:\.\d{3})*(?:,\d+)?", text or ""
            )
        ]

    def extract_prices(self, price_text, text):
        s = price_text or text or ""
        vals = self._numbers(s)
        eur_parts = re.findall(r"([\d.]+(?:,\d+)?)\s*€", s)
        eur = [
            float(x.replace(".", "").replace(",", "."))
            for x in eur_parts
        ]

        if eur:
            warm = None
            m = re.search(
                r"(?:warmmiete|warm|gesamtmiete)[^\d]{0,20}([\d.]+(?:,\d+)?)\s*€",
                s,
                re.I,
            )
            if m:
                warm = float(
                    m.group(1).replace(".", "").replace(",", ".")
                )
            return eur[0], warm

        return (vals[0] if vals else None), None

    def extract_rooms(self, specific, text):
        s = specific or text or ""
        m = re.search(
            r"([0-9]+(?:[,.][0-9]+)?)\s*(?:-|bis)?\s*Zimmer\b",
            s,
            re.I,
        )
        return float(m.group(1).replace(",", ".")) if m else None

    def extract_size(self, specific, text):
        s = specific or text or ""
        m = re.search(
            r"([0-9]{1,4}(?:[,.][0-9]+)?)\s*(?:m²|m2|qm|m\s*²)\b",
            s,
            re.I,
        )
        return float(m.group(1).replace(",", ".")) if m else None

    @staticmethod
    def extract_location(text):
        m = re.search(
            r"\b(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .-]{2,60})\b",
            text or "",
        )
        return (
            f"{m.group(1)} {m.group(2).strip()}" if m else None
        )

    @staticmethod
    def _dedupe(items):
        out, seen = [], set()
        for item in items:
            key = (item.source, item.external_id or item.url)
            if key not in seen:
                seen.add(key)
                out.append(item)
        return out
