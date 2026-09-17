from __future__ import annotations
import logging, os, random, re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
import scrapy
from scrapy import signals
from scrapy_playwright.page import PageMethod
from ..items import ApartmentItem
from ..parsing import node_text, clean_text, canonical_url, external_id_from_url, parse_rents, parse_rooms, parse_size, parse_location, parse_number, jsonld_objects, jsonld_to_raw, parse_rent_details, validate_listing_dict

# Text markers that indicate a bot-check/interstitial page rather than a
# genuine "0 results" search page. Kept case-insensitive and portal-agnostic
# on purpose: these are the standard phrasings used by Cloudflare/PerimeterX
# style challenges and the German equivalents portals show.
BLOCK_PAGE_MARKERS = (
    "bestätigen sie, dass sie kein roboter",
    "sind sie ein mensch",
    "verify you are human",
    "checking your browser",
    "attention required! | cloudflare",
    "just a moment...",
    "captcha",
    "access denied",
    "unusual traffic",
    "automatisierte anfragen",
)

_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ"
_LOWER = "abcdefghijklmnopqrstuvwxyzäöü"
_CI_CSS_PART_RE = re.compile(
    r"^(?P<tag>[a-zA-Z][a-zA-Z0-9]*)?"
    r"\[(?P<attr>[a-zA-Z0-9_:-]+)\s*(?P<op>[*^$]?=)\s*'(?P<val>[^']*)'\s*(?P<ci>i)?\s*\]"
    r"(?:::attr\((?P<pname>[a-zA-Z0-9_-]+)\))?$"
)

def _ci_css_to_xpath(selector):
    """Translate a comma-separated list of simple ``tag[attr OP 'val' i]``
    selectors (optionally with a trailing ``::attr(name)``) into an
    equivalent XPath expression, or return ``None`` if any part doesn't
    match that restricted shape.

    This exists because several portal selectors use the CSS Selectors
    Level 4 case-insensitive attribute flag (``i``) for resilience against
    markup casing changes, but cssselect/parsel do not implement that flag
    and raise ``SelectorSyntaxError`` instead of just ignoring it - which
    previously crashed parsing outright rather than degrading gracefully.
    """
    parts = []
    pnames = set()
    for raw_part in selector.split(","):
        m = _CI_CSS_PART_RE.match(raw_part.strip())
        if not m:
            return None
        tag = m.group("tag") or "*"
        attr, op, val = m.group("attr"), m.group("op"), m.group("val")
        pnames.add(m.group("pname"))
        if m.group("ci"):
            lhs = f"translate(@{attr}, '{_UPPER}', '{_LOWER}')"
            val = val.lower()
        else:
            lhs = f"@{attr}"
        if op == "=":
            cond = f"{lhs}='{val}'"
        elif op == "^=":
            cond = f"starts-with({lhs}, '{val}')"
        elif op == "$=":
            n = max(len(val) - 1, 0)
            cond = f"substring({lhs}, string-length({lhs}) - {n}) = '{val}'"
        else:  # '*=' (or bare, which we don't emit) -> substring match
            cond = f"contains({lhs}, '{val}')"
        parts.append(f".//{tag}[{cond}]")
    if len(pnames) > 1:
        return None  # mixed attr-extraction targets - not used in this codebase
    pname = next(iter(pnames))
    if pname:
        return " | ".join(f"{p}/@{pname}" for p in parts)
    return " | ".join(parts)

def select(scope, selector):
    """``scope.css(selector)`` with a fallback for the ``i`` flag.

    Tries the selector as-is first (the fast, common path) and only falls
    back to an equivalent XPath translation when cssselect actually rejects
    the selector - so plain selectors behave exactly as before.
    """
    try:
        return scope.css(selector)
    except Exception:
        xpath = _ci_css_to_xpath(selector)
        if xpath is None:
            raise
        return scope.xpath(xpath)

class PortalSpider(scrapy.Spider):
    source_key=""
    source_label=""
    base_url=""
    use_playwright=True
    # Portal-specific Playwright navigation tuning. A few portals keep
    # long-lived requests open; subclasses can use ``commit`` so navigation
    # itself does not hold the crawl hostage while the page is already usable.
    playwright_wait_until="domcontentloaded"
    playwright_nav_timeout_env="SCRAPE_NAV_TIMEOUT_MS"
    playwright_wait_ms_env="SCRAPE_WAIT_MS"
    max_pages_env="SCRAPE_MAX_PAGES"
    card_selectors=()
    link_selectors=()
    pagination_selectors=(
        "a[rel='next']::attr(href)",
        "a[aria-label*='Weiter' i]::attr(href)",
        "a[aria-label*='next' i]::attr(href)",
        "a[class*='next' i]::attr(href)",
    )
    cookie_selectors=(
        "button:has-text('Alle akzeptieren')","button:has-text('Akzeptieren')",
        "button:has-text('Einverstanden')","button:has-text('Zustimmen')",
        "button[id*='accept' i]","button[class*='accept' i]",
        "[role='button']:has-text('Akzeptieren')",
    )
    def __init__(self,start_urls=None,max_pages=None,job_id=None,**kw):
        super().__init__(**kw)
        self.start_urls=list(dict.fromkeys(start_urls or []))
        self.job_id=str(job_id or self.name)
        self.max_pages=max(1,int(max_pages if max_pages is not None else os.getenv("SCRAPE_MAX_PAGES","3")))
        self._seen_urls=set(); self._seen_pages=set()
        self.page_errors=0; self.pages_seen=0
        self.blocked_pages=0
        self.result_page_valid=False
        self._first_page_url_set=None
        self.feed_path = None
        self._start_entered = False
        self._start_yielded = 0
        self._requests_scheduled = 0
        self._requests_dropped = 0
        self._responses_received = 0
        self._responses_2xx = 0
        self._responses_3xx = 0
        self._responses_4xx = 0
        self._responses_5xx = 0
        self._spider_errors = 0
        self._downloader_exceptions = 0
        self._http_statuses = {}
        self._error_messages = []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.feed_path = kwargs.get("feed_path")
        spider._connect_signals(crawler)
        return spider

    def _connect_signals(self, crawler):
        crawler.signals.connect(self._on_spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(self._on_spider_closed, signal=signals.spider_closed)
        crawler.signals.connect(self._on_request_scheduled, signal=signals.request_scheduled)
        crawler.signals.connect(self._on_request_dropped, signal=signals.request_dropped)
        crawler.signals.connect(self._on_response_received, signal=signals.response_received)
        crawler.signals.connect(self._on_spider_error, signal=signals.spider_error)
        # Scrapy 2.19 does not expose a ``downloader_exception`` signal.
        # Downloader failures are handled through request errbacks/middleware;
        # connecting to the removed signal aborts spider creation entirely.

    def _on_spider_opened(self, spider):
        if spider is not self:
            return
        self.logger.info("[SCAN-DEBUG][%s] SPIDER_OPENED job_id=%s urls=%d",
                         self.source_key, self.job_id, len(self.start_urls))

    def _on_spider_closed(self, spider, reason):
        if spider is not self:
            return
        self.logger.info(
            "[SCAN-DEBUG][%s] SPIDER_CLOSED job_id=%s reason=%s "
            "start_urls=%d start_entered=%s start_yielded=%d "
            "requests_scheduled=%d dropped=%d responses=%d items=%d",
            self.source_key, self.job_id, reason, len(self.start_urls),
            self._start_entered, self._start_yielded,
            self._requests_scheduled, self._requests_dropped,
            self._responses_received, self.crawler.stats.get_value("item_scraped_count", 0),
        )

    def _on_request_scheduled(self, request, spider):
        if spider is not self:
            return
        self._requests_scheduled += 1
        self.logger.info("[SCAN-DEBUG][%s] REQUEST_SCHEDULED job_id=%s url=%s",
                         self.source_key, self.job_id, request.url)

    def _on_request_dropped(self, request, spider):
        if spider is not self:
            return
        self._requests_dropped += 1
        self.logger.error("[SCAN-DEBUG][%s] REQUEST_DROPPED job_id=%s url=%s",
                          self.source_key, self.job_id, request.url)

    def _on_response_received(self, response, request, spider):
        if spider is not self:
            return
        status = int(getattr(response, "status", 0) or 0)
        self._responses_received += 1
        self._http_statuses[str(status)] = self._http_statuses.get(str(status), 0) + 1
        if 200 <= status < 300:
            self._responses_2xx += 1
        elif 300 <= status < 400:
            self._responses_3xx += 1
        elif 400 <= status < 500:
            self._responses_4xx += 1
        elif status >= 500:
            self._responses_5xx += 1
        self.logger.info("[SCAN-DEBUG][%s] RESPONSE_RECEIVED job_id=%s status=%s url=%s",
                         self.source_key, self.job_id, status, response.url)

    def _on_spider_error(self, failure, response, spider):
        if spider is not self:
            return
        self._spider_errors += 1
        msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
        self._error_messages.append(msg)
        self.logger.error("[SCAN-DEBUG][%s] SPIDER_ERROR job_id=%s url=%s error=%s",
                          self.source_key, self.job_id, getattr(response, "url", None), msg)

    def _on_downloader_exception(self, request, exception, spider):
        if spider is not self:
            return
        self._downloader_exceptions += 1
        msg = f"{type(exception).__name__}: {exception}"
        self._error_messages.append(msg)
        self.logger.error("[SCAN-DEBUG][%s] DOWNLOADER_EXCEPTION job_id=%s url=%s error=%s",
                          self.source_key, self.job_id, request.url, msg)

    async def start(self):
        """Scrapy 2.19+ async-generator entrypoint.

        This is the single source of truth on modern Scrapy. ``start_requests``
        remains only as a guarded compatibility fallback for older Scrapy.
        """
        self._start_entered = True
        self.logger.info("[SCAN-DEBUG][%s] START_ENTERED job_id=%s",
                         self.source_key, self.job_id)
        self.logger.info("[SCAN-DEBUG][%s] START_URLS count=%d urls=%s",
                         self.source_key, len(self.start_urls), self.start_urls)
        if not self.start_urls:
            self.logger.error("[SCAN-DEBUG][%s] NO_START_URLS job_id=%s",
                              self.source_key, self.job_id)
            return
        for u in self.start_urls:
            try:
                request = self._request(u, 1)
                self._start_yielded += 1
                self.logger.info("[SCAN-DEBUG][%s] START_YIELD job_id=%s url=%s",
                                 self.source_key, self.job_id, u)
                yield request
            except Exception:
                self.logger.exception("[SCAN-DEBUG][%s] REQUEST_BUILD_ERROR job_id=%s url=%s",
                                      self.source_key, self.job_id, u)

    def start_requests(self):
        """Compatibility fallback for pre-2.13 Scrapy."""
        if self._start_entered:
            return
        self._start_entered = True
        self.logger.info("[SCAN-DEBUG][%s] START_ENTERED_LEGACY job_id=%s",
                         self.source_key, self.job_id)
        self.logger.info("[SCAN-DEBUG][%s] START_URLS count=%d urls=%s",
                         self.source_key, len(self.start_urls), self.start_urls)
        if not self.start_urls:
            self.logger.error("[SCAN-DEBUG][%s] NO_START_URLS job_id=%s",
                              self.source_key, self.job_id)
            return
        for u in self.start_urls:
            try:
                request = self._request(u, 1)
                self._start_yielded += 1
                self.logger.info("[SCAN-DEBUG][%s] START_YIELD job_id=%s url=%s",
                                 self.source_key, self.job_id, u)
                yield request
            except Exception:
                self.logger.exception("[SCAN-DEBUG][%s] REQUEST_BUILD_ERROR job_id=%s url=%s",
                                      self.source_key, self.job_id, u)

    def _pick_user_agent(self):
        pool=list(getattr(self,"settings",None).get("USER_AGENT_POOL") or []) if getattr(self,"settings",None) else []
        if not pool:
            return None
        return random.choice(pool)

    def _request(self,url,page_number):
        meta={"page_number":page_number, "handle_httpstatus_all": True}
        ua=self._pick_user_agent()
        headers={"User-Agent":ua} if ua else None
        if self.use_playwright:
            meta.update({"playwright":True,
                         "playwright_page_goto_kwargs": {
                             "wait_until": self.playwright_wait_until,
                             "timeout": int(os.getenv(self.playwright_nav_timeout_env, "15000")),
                         },
                         "playwright_page_methods":[
                PageMethod("evaluate", """
                    () => {
                        const labels = [
                            'Alle akzeptieren', 'Akzeptieren', 'Einverstanden',
                            'Zustimmen', 'Accept all', 'Accept'
                        ];
                        for (const el of document.querySelectorAll('button,[role="button"],input[type="button"]')) {
                            const t = (el.innerText || el.value || '').trim().toLowerCase();
                            if (labels.some(x => t === x.toLowerCase())) {
                                try { el.click(); } catch (_) {}
                            }
                        }
                    }
                """),
                PageMethod("wait_for_timeout", int(os.getenv(self.playwright_wait_ms_env, "1200"))),
            ]})
        return scrapy.Request(url,callback=self.parse,errback=self.errback,meta=meta,headers=headers,dont_filter=True)

    def build_page_url(self, base_url, page):
        if page<=1: return base_url
        return self._build_page_url(base_url,page)

    def _build_page_url(self,base_url,page):
        return None

    def _looks_blocked(self,response):
        body=(response.text or "")[:20000].casefold()
        return any(marker in body for marker in BLOCK_PAGE_MARKERS)

    def parse(self,response):
        self.pages_seen += 1
        page_number=int(response.meta.get("page_number",1))
        cards=self.parse_listing_cards(response)
        self.result_page_valid = self.result_page_valid or self._is_valid_result_page(response, cards)
        if not cards and self._looks_blocked(response):
            self.blocked_pages += 1
            # Reuse the existing page_errors counter so this also shows up
            # as "source_errors" in the scan funnel (scraper.py), not just
            # in the raw logs - a blocked source should look different from
            # a source that legitimately had zero matches.
            self.page_errors += 1
            self.logger.error(
                "[%s] Seite %d sieht wie eine Bot-Check-/Block-Seite aus (0 Kandidaten, "
                "Marker gefunden) - vermutlich blockiert, nicht wirklich leer.",
                self.source_key, page_number,
            )
            return
        new=0
        page_urls=set()
        for raw in cards:
            try:
                item=self.normalize_card(raw,response)
                if not item: continue
                page_urls.add(item["url"])
                if item["url"] in self._seen_urls: continue
                self._seen_urls.add(item["url"]); new += 1
                yield item
            except Exception:
                self.logger.exception("[%s] Listing konnte nicht normalisiert werden",self.source_key)
        self.logger.info("[%s] Seite %d: %d Kandidaten, %d neu",self.source_key,page_number,len(cards),new)

        if page_number==1:
            self._first_page_url_set=page_urls
        elif page_urls and self._first_page_url_set and page_urls==self._first_page_url_set:
            # Same exact set of listing URLs as page 1 => the pagination
            # parameter for this portal is very likely wrong and every
            # "next page" request just re-fetches page 1 under the hood.
            self.logger.warning(
                "[%s] Seite %d liefert exakt dieselben Treffer wie Seite 1 - "
                "Pagination-Parameter vermutlich falsch konfiguriert.",
                self.source_key, page_number,
            )

        next_url=self.next_page_url(response,page_number,len(cards),new)
        if next_url and page_number<self.max_pages:
            key=canonical_url(next_url)
            if key not in self._seen_pages:
                self._seen_pages.add(key)
                yield self._request(next_url,page_number+1)


    def _is_valid_result_page(self, response, cards):
        if int(getattr(response, "status", 0) or 0) < 200 or int(getattr(response, "status", 0) or 0) >= 400:
            return False
        if self._looks_blocked(response):
            return False
        body=(response.text or "")[:100000].casefold()
        # Require evidence that this is a real property-results document.
        result_markers=("wohnung", "mietwohnung", "mieten", "immobil", "zimmer", "m²", "qm")
        has_result_language=sum(1 for marker in result_markers if marker in body) >= 2
        has_listing_links=any(self.is_listing_href(h) for h in response.css("a::attr(href)").getall())
        has_empty_state=any(marker in body for marker in ("keine ergebnisse", "keine passenden", "keine angebote", "0 ergebnisse", "leider keine"))
        return has_result_language and (bool(cards) or has_listing_links or has_empty_state)

    def next_page_url(self,response,page_number,card_count,new_count):
        if page_number>=self.max_pages or not cards_continue(card_count,new_count):
            return None
        # Portal subclasses can use real next links or path/query conventions.
        href=select(response,",".join(self.pagination_selectors)).get()
        if href: return urljoin(response.url,href)
        return self.build_page_url(response.url,page_number+1)

    def parse_listing_cards(self,response):
        # Portal selectors are an optimization, never the sole source of
        # truth. Current portals change class names frequently, so always run
        # the link-based adaptive extractor as a second pass.
        cards=[]; seen=set()
        for selector in self.card_selectors:
            for card in select(response,selector):
                raw=self.extract_card(card,response.url)
                href=raw.get("href")
                if href:
                    key=canonical_url(href,response.url)
                    if key and key not in seen:
                        seen.add(key); cards.append(raw)
        for raw in self.adaptive_extract(response):
            href=raw.get("href")
            key=canonical_url(href,response.url) if href else ""
            if key and key not in seen:
                seen.add(key); cards.append(raw)
        cards=self.merge_jsonld(response,cards)
        return cards[:500]

    def extract_card(self,card,base_url):
        href=None
        for selector in self.link_selectors:
            href=card.css(selector + "::attr(href)").get()
            if href: break
        if not href: href=card.css("a[href]::attr(href)").get()
        text=node_text(card)
        title=self.first_text(card,("h1","h2","h3","h4","h5","[class*='title' i]","[data-testid*='title' i]"))
        price=self.first_text(card,("[data-testid*='price' i]","[class*='price' i]","[aria-label*='€' i]"))
        rooms=self.first_text(card,("[data-testid*='room' i]","[class*='room' i]"))
        size=self.first_text(card,("[data-testid*='area' i]","[class*='area' i]","[class*='size' i]"))
        location=self.first_text(card,("[data-testid*='address' i]","[class*='address' i]","[class*='location' i]"))
        return {"href":urljoin(base_url,href or ""),"title":title or text[:180],"description":text,
                "price_text":price,"rooms_text":rooms,"size_text":size,"address":location}

    @staticmethod
    def first_text(node,selectors):
        for selector in selectors:
            try:
                value=select(node,selector).xpath("string(.)").get()
                if value and clean_text(value): return clean_text(value)
            except Exception:
                continue
        return None

    def adaptive_extract(self,response):
        out=[]; seen=set()
        for a in response.css("a[href]"):
            href=a.attrib.get("href","")
            if not self.is_listing_href(href): continue
            key=canonical_url(href,response.url)
            if key in seen: continue
            seen.add(key)
            node=a
            best=a
            for _ in range(6):
                parent=node.xpath("..")
                if not parent: break
                node=parent[0]
                txt=node_text(node)
                if self.looks_like_listing_text(txt): best=node
            raw=self.extract_card(best,response.url)
            raw["href"]=urljoin(response.url,href)
            # The anchor itself is always a useful title fallback. This is
            # important when a portal renders the card title outside the
            # selected ancestor.
            anchor_text=node_text(a)
            if anchor_text and (not raw.get("title") or len(raw.get("title","")) < 3):
                raw["title"]=clean_text(anchor_text)
            if not raw.get("title"):
                raw["title"]=clean_text(node_text(best)[:180])
            out.append(raw)
        return out[:500]

    @staticmethod
    def looks_like_listing_text(text):
        s=text.casefold()
        return bool(re.search(r"(?:€|eur|euro).*(?:m²|m2|qm|zimmer|zi\b)",s,re.S)) or bool(re.search(r"(?:m²|m2|qm).*(?:zimmer|zi\b)",s,re.S))

    def is_listing_href(self,href): return bool(href)

    def merge_jsonld(self,response,cards):
        by_url={canonical_url(c.get("href",""),response.url):c for c in cards if c.get("href")}
        for obj in jsonld_objects(response):
            raw=jsonld_to_raw(obj,response.url)
            if not raw: continue
            key=canonical_url(raw["href"],response.url)
            if key in by_url:
                by_url[key].update({k:v for k,v in raw.items() if v not in (None,"")})
            else:
                by_url[key]=raw
        return list(by_url.values())

    def normalize_card(self,raw,response):
        href=canonical_url(raw.get("href",""),response.url)
        if not href: return None
        title=clean_text(raw.get("title"))
        if not title: return None
        combined=" ".join(x for x in [raw.get("description"),raw.get("rooms_text"),raw.get("size_text"),raw.get("address")] if x)
        cold=warm=None
        if raw.get("price_text"):
            cold,warm=parse_rents(str(raw["price_text"]))
            if cold is None and warm is None and re.fullmatch(r"\s*(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?\s*", str(raw["price_text"])):
                cold=parse_number(raw["price_text"])
        # The description is a secondary source: it can provide an explicit
        # Warmmiete/Gesamtmiete, but an unlabeled amount in prose must not
        # override a portal's dedicated price field.
        if warm is None:
            _,warm=parse_rents(combined)
        if cold is None and not raw.get("price_text"):
            cold,_=parse_rents(combined)
        if raw.get("price_total_text"):
            explicit=parse_rents("Warmmiete "+str(raw["price_total_text"]))[1]
            warm=explicit if explicit is not None else warm
        rooms=parse_rooms(raw.get("rooms_text") or combined)
        size=parse_size(raw.get("size_text") or combined)
        postal,city=parse_location(raw.get("address") or combined)
        postal=raw.get("postal_code") or postal; city=raw.get("city") or city
        address=clean_text(raw.get("address")) or (f"{postal} {city}" if postal and city else None)
        details=parse_rent_details(combined)
        if cold is not None: details["cold_rent"]=cold
        if warm is not None: details["warm_rent"]=warm
        details["price"]=details.get("cold_rent"); details["price_total"]=details.get("warm_rent")
        data={"url":href,"title":title,"rooms":rooms,"size":size,**details}
        valid,warnings=validate_listing_dict(data)
        if not valid:
            self.logger.warning("[%s] Listing verworfen: %s url=%s",self.source_key, warnings, href)
            return None
        raw_out=dict(raw); raw_out.update(details); raw_out["data_quality_warning"]=warnings
        return ApartmentItem(
            job_id=self.job_id,source=self.source_key,external_id=external_id_from_url(href,self.source_key),
            url=href,title=title,description=clean_text(raw.get("description")),
            price=details.get("cold_rent"),price_total=details.get("warm_rent"),
            rooms=rooms,size=size,address=address,city=city,postal_code=postal,
            region_code=None,contact_name=None,contact_phone=None,published_at=raw.get("published_at"),raw=raw_out,
        )

    def errback(self, failure):
        self.page_errors += 1
        msg = failure.getErrorMessage()
        self._error_messages.append(msg)
        self.logger.error("[SCAN-DEBUG][%s] DOWNLOAD_FAILURE job_id=%s url=%s error=%s",
                          self.source_key, self.job_id,
                          getattr(failure.request, "url", None), msg)

def cards_continue(card_count,new_count):
    return card_count>0 and new_count>0
