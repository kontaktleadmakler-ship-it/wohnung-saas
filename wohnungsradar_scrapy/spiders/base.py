from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

import scrapy
from scrapy_playwright.page import PageMethod

from ..items import ApartmentItem


class PortalSpider(scrapy.Spider):
    """Common Scrapy 2.19-style base for every housing portal.

    Each portal subclass only defines URL construction and selectors/parsing.
    Networking, retries, throttling, Playwright integration, pagination,
    deduplication and the output contract live here.
    """

    source_key = ""
    source_label = ""
    base_url = ""
    use_playwright = True
    max_pages = 3
    page_param = "page"
    page_start = 1
    card_selectors = ()
    link_selectors = ()
    cookie_selectors = (
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Akzeptieren')",
        "button:has-text('Einverstanden')",
        "button:has-text('Zustimmen')",
        "button[id*='accept' i]",
        "button[class*='accept' i]",
        "button[data-testid*='accept' i]",
    )

    def __init__(self, start_urls=None, max_pages=None, job_id=None, **kwargs):
        super().__init__(**kwargs)
        self.start_urls = list(start_urls or [])
        self.job_id = str(job_id or self.name)
        self.max_pages = int(max_pages or self.max_pages)
        self._seen_listing_urls = set()
        self._seen_pages = set()

    def start_requests(self):
        for url in dict.fromkeys(self.start_urls):
            yield self._request(url, page_number=self.page_start)

    def _request(self, url, page_number=1):
        meta = {"page_number": page_number}
        if self.use_playwright:
            meta.update(
                {
                    "playwright": True,
                    "playwright_page_methods": [
                        PageMethod("wait_for_timeout", 1200),
                        PageMethod("evaluate", "window.scrollTo(0, document.body.scrollHeight)"),
                        PageMethod("wait_for_timeout", 500),
                    ],
                }
            )
        return scrapy.Request(url, callback=self.parse, errback=self.errback, meta=meta, dont_filter=True)

    def build_page_url(self, base_url, page):
        if page <= self.page_start:
            return base_url
        parts = urlsplit(base_url)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != self.page_param]
        query.append((self.page_param, str(page)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def parse(self, response):
        page_number = int(response.meta.get("page_number", 1))
        cards = self.parse_listing_cards(response)
        new_count = 0
        for raw in cards:
            item = self.normalize_card(raw, response)
            if not item:
                continue
            canonical = item["url"]
            if canonical in self._seen_listing_urls:
                continue
            self._seen_listing_urls.add(canonical)
            new_count += 1
            yield item

        self.logger.info("[%s] Seite %s: %s Karten, %s neu", self.source_key, page_number, len(cards), new_count)

        if page_number < self.max_pages and new_count > 0:
            next_url = self.build_page_url(response.url, page_number + 1)
            page_key = (urlsplit(next_url).netloc, urlsplit(next_url).path, urlsplit(next_url).query)
            if page_key not in self._seen_pages:
                self._seen_pages.add(page_key)
                yield self._request(next_url, page_number + 1)

    def parse_listing_cards(self, response):
        selectors = self.card_selectors or ("article", "div")
        for selector in selectors:
            cards = response.css(selector)
            if cards:
                parsed = []
                for card in cards:
                    href = None
                    for link_selector in self.link_selectors or ("a::attr(href)",):
                        if "::attr" in link_selector:
                            href = card.css(link_selector).get()
                        else:
                            href = card.css(link_selector + "::attr(href)").get()
                        if href:
                            break
                    if not href:
                        continue
                    if not self.is_listing_href(href):
                        continue
                    parsed.append(self.extract_card(card, href))
                if parsed:
                    return parsed
        return []

    def extract_card(self, card, href):
        text = " ".join(x.strip() for x in card.css("::text").getall() if x.strip())
        return {
            "href": href,
            "title": self.first_text(card, ("h1::text", "h2::text", "h3::text", "h4::text", "h5::text")),
            "price_text": self.first_text(card, ("[data-testid='price']::text", ".price::text", "[class*='price' i]::text")),
            "rooms_text": self.first_text(card, ("[data-testid='rooms']::text", ".rooms::text", "[class*='room' i]::text")),
            "size_text": self.first_text(card, ("[data-testid='area']::text", ".area::text", "[class*='area' i]::text")),
            "location": self.first_text(card, ("[data-testid='address']::text", "[data-testid='location']::text", ".address::text", ".location::text")),
            "description": text,
        }

    @staticmethod
    def first_text(card, selectors):
        for selector in selectors:
            value = card.css(selector).get()
            if value and value.strip():
                return value.strip()
        return None

    def is_listing_href(self, href):
        return bool(href)

    def normalize_card(self, raw, response):
        href = urljoin(response.url, raw.get("href", ""))
        if not href or not raw.get("title"):
            return None
        external_id = self.extract_external_id(href)
        if not external_id:
            return None
        return ApartmentItem(
            job_id=self.job_id,
            source=self.source_key,
            external_id=external_id,
            url=href,
            title=raw.get("title"),
            description=raw.get("description"),
            price=raw.get("price_text"),
            price_total=None,
            rooms=raw.get("rooms_text"),
            size=raw.get("size_text"),
            address=raw.get("location"),
            city=None,
            postal_code=None,
            region_code=None,
            contact_name=None,
            contact_phone=None,
            published_at=None,
            raw=dict(raw),
        )

    @staticmethod
    def extract_external_id(url):
        parts = urlsplit(url)
        clean = parts.path.rstrip("/") or "/"
        match = re.search(r"(?:expose|immobilie|angebot|anzeige|ad)[/_-]?(\d{4,})", clean, re.I)
        if match:
            return match.group(1)
        return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]

    def errback(self, failure):
        self.logger.error("[%s] Request fehlgeschlagen: %s", self.source_key, failure.getErrorMessage())
