"""Dependency-light regression tests.

Runs without PostgreSQL, without a real browser, and without hitting any
real-estate portal - it only needs beautifulsoup4 (already a hard
requirement) and a lightweight playwright stub so scrapers/base.py can be
imported even on a machine that hasn't run `playwright install`.

Run with: python test_smoke.py
"""
from __future__ import annotations

import sys
import types


def _stub_playwright():
    """scrapers/base.py imports playwright.sync_api at module scope purely
    for typing/exception-handling; none of the functions exercised by these
    tests actually launch a browser, so a minimal stub is enough to import
    the module in an environment without Playwright's browser binaries."""
    if "playwright.sync_api" in sys.modules:
        return
    pkg = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")

    class _TimeoutError(Exception):
        pass

    sync_api.TimeoutError = _TimeoutError
    sync_api.sync_playwright = lambda: None
    sys.modules["playwright"] = pkg
    sys.modules["playwright.sync_api"] = sync_api


_stub_playwright()

from matching import (  # noqa: E402
    REASON_OVER_BUDGET,
    REASON_TOO_FEW_ROOMS,
    REASON_TOO_SMALL,
    canonical_url,
    listing_fingerprint,
    score_listing,
)
from scrapers.sites import (  # noqa: E402
    ImmoScout24Scraper,
    KalaydoScraper,
    KleinanzeigenScraper,
    MeinestadtScraper,
    ImmoweltScraper,
)
from scrapers.models import SearchParams  # noqa: E402
from scraper import _locations  # noqa: E402

FAILURES = []


def check(name, condition):
    print(("PASS " if condition else "FAIL ") + name)
    if not condition:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Card parsing / normalization (HTML -> Listing)
# ---------------------------------------------------------------------------
HTML = """<html><body>
<article class="aditem">
  <a class="ellipsis" href="/s-anzeige/testwohnung-123456">Schöne 2 Zimmer Wohnung</a>
  <div>1.150 €</div>
  <div>58 m² · 2 Zimmer</div>
  <div>10115 Berlin Mitte</div>
</article>
</body></html>"""

scraper = KleinanzeigenScraper()
cards = scraper.parse_listing_cards(HTML)
check("card parser finds the listing card", bool(cards))
item = scraper.normalize(cards[0], "https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/c203")
check("normalize() produces a Listing", item is not None)
check("external_id extracted", bool(item and item.external_id))
check("size parsed as 58", item and item.size == 58)
check("rooms parsed as 2", item and item.rooms == 2)
check("direct listing URL, not a search URL", item and "/s-anzeige/" in item.url)

# Pagination-affecting card selectors still work when no CARD_SELECTORS match
# (adaptive fallback path).
HTML_NO_CARDS = """<html><body>
<div>
  <a href="/expose/99887766">3-Zimmer Altbau, 75 m², Warmmiete 1.450 €, Kreuzberg</a>
</div>
</body></html>"""
iss = ImmoScout24Scraper()
adaptive_cards = iss.parse_listing_cards(HTML_NO_CARDS)
check("adaptive fallback extracts a card without known selectors", bool(adaptive_cards))

JSONLD_GRAPH = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"Apartment","name":"Helle 3 Zimmer Wohnung","url":"https://www.immobilienscout24.de/expose/44556677","description":"75 m² in Köln","offers":{"price":"1450"}}]}
</script></head><body></body></html>"""
graph_cards = iss.parse_listing_cards(JSONLD_GRAPH)
check("JSON-LD @graph extracts a listing card", bool(graph_cards) and graph_cards[0].get("href", "").endswith("/44556677"))

# ---------------------------------------------------------------------------
# Room / size / price normalization edge cases
# ---------------------------------------------------------------------------
check("rooms: '2 Zimmer'", scraper.extract_rooms(None, "2 Zimmer") == 2.0)
check("rooms: '2-Zimmer'", scraper.extract_rooms(None, "2-Zimmer") == 2.0)
check("rooms: '2 Zi.'", scraper.extract_rooms(None, "2 Zi.") == 2.0)
check("rooms: '2,5 Zimmer'", scraper.extract_rooms(None, "2,5 Zimmer") == 2.5)
check("rooms: '2.5 Zimmer'", scraper.extract_rooms(None, "2.5 Zimmer") == 2.5)
check("rooms: '2 1/2 Zimmer'", scraper.extract_rooms(None, "2 1/2 Zimmer") == 2.5)
check("rooms: '1/2 Zimmer'", scraper.extract_rooms(None, "1/2 Zimmer") == 0.5)

check("size: '55 m²'", scraper.extract_size(None, "55 m²") == 55.0)
check("size: '55,5 qm'", scraper.extract_size(None, "55,5 qm") == 55.5)
check("size: '55m2'", scraper.extract_size(None, "55m2") == 55.0)

cold, warm = scraper.extract_prices(None, "Kaltmiete 1000 € Warmmiete 1180 €")
check("price: explicit Kaltmiete/Warmmiete split", cold == 1000.0 and warm == 1180.0)
cold2, warm2 = scraper.extract_prices(None, "1.150 €")
check(
    "price: unlabeled amount is cold-rent estimate, no fabricated warm rent",
    cold2 == 1150.0 and warm2 is None,
)
cold3, warm3 = scraper.extract_prices(None, "1000")
check("price: four-digit unlabeled number parses as 1000", cold3 == 1000.0 and warm3 is None)
cold4, warm4 = scraper.extract_prices(None, "1500")
check("price: four-digit unlabeled number parses as 1500", cold4 == 1500.0 and warm4 is None)

# ---------------------------------------------------------------------------
# Matching: hard filters, unknown-value handling, warm/cold-rent confidence
# ---------------------------------------------------------------------------
profile = {
    "max_price": 1200,
    "min_rooms": 2,
    "max_rooms": 3,
    "min_size": 50,
    "districts": "Mitte",
    "keywords_exclude": "WG,Tausch",
}

only_cold = {
    "title": "Wohnung",
    "description": "Kaltmiete 1100 Euro",
    "location": "Mitte",
    "price": 1100,
    "price_total": None,
    "rooms": 2,
    "size": 55,
}
r = score_listing(dict(only_cold), profile)
check("cold-rent-only listing still matches", r is not None)
check("cold-rent-only match is flagged as an estimate", r and "geschätzt" in r[2][0])
check("cold-rent-only price confidence capped below 100%", r and r[0] < 100)

with_warm = {**only_cold, "price_total": 1150}
r_warm = score_listing(dict(with_warm), profile)
check("confirmed warm rent gets full price confidence", r_warm and r_warm[1][0] == 35)

over_budget = dict(with_warm)
over_budget["price_total"] = 1400
r_over = score_listing(over_budget, profile)
check("over-budget listing is hard-excluded", r_over is None)
check(
    "over-budget exclusion reason recorded for the funnel",
    over_budget.get("_exclude_reason") == REASON_OVER_BUDGET,
)

too_small = dict(with_warm)
too_small["size"] = 30
r_small = score_listing(too_small, profile)
check("undersized listing is hard-excluded", r_small is None)
check("undersized reason recorded", too_small.get("_exclude_reason") == REASON_TOO_SMALL)

too_few_rooms = dict(with_warm)
too_few_rooms["rooms"] = 1
r_rooms = score_listing(too_few_rooms, profile)
check("listing below min_rooms is hard-excluded", r_rooms is None)
check("too-few-rooms reason recorded", too_few_rooms.get("_exclude_reason") == REASON_TOO_FEW_ROOMS)

excluded_kw = {**with_warm, "title": "WG Zimmer in Mitte"}
check("excluded-keyword listing is hard-excluded", score_listing(dict(excluded_kw), profile) is None)

unknown_everything = {"title": "Wohnung", "description": "", "location": "Mitte"}
r_unknown = score_listing(unknown_everything, profile)
check(
    "unknown price/rooms/size never auto-excludes and never claims a perfect match",
    r_unknown is not None and r_unknown[0] < 100,
)

# ---------------------------------------------------------------------------
# Deduplication fingerprint (same listing, different tracking params)
# ---------------------------------------------------------------------------
u1 = canonical_url("https://x.de/expose/123?utm_source=a&ref=b")
u2 = canonical_url("https://x.de/expose/123?utm_source=z")
check("tracking params are stripped before canonicalizing", u1 == u2)

canon_a = canonical_url("HTTPS://X.DE/expose/123/?Foo=Bar&foo=bar#details")
canon_b = canonical_url("https://x.de/expose/123?foo=bar")
check("canonical_url ignores fragments and normalizes case/duplicate query params", canon_a == canon_b)
canon_path = canonical_url("https://X.DE/Expose/AbC123/")
check("canonical_url casefoldet den Pfad nicht", canon_path == "https://x.de/Expose/AbC123")

fp_a = listing_fingerprint({"source": "immoscout24", "external_id": "123", "url": u1})
fp_b = listing_fingerprint({"source": "immoscout24", "external_id": "123", "url": "https://x.de/expose/123"})
check("same source+external_id fingerprints identically", fp_a == fp_b)
fp_c = listing_fingerprint({"source": "immowelt", "external_id": "123", "url": u1})
check("different source does not collide", fp_a != fp_c)

# ---------------------------------------------------------------------------
# Search-URL / pagination building (no network - just URL construction)
# ---------------------------------------------------------------------------
for cls in (KleinanzeigenScraper, MeinestadtScraper, ImmoScout24Scraper):
    urls = cls().build_search_urls(SearchParams(locations=["Berlin"]))
    check(f"{cls.SOURCE_KEY}: build_search_urls returns at least one URL", bool(urls))

nationwide = SearchParams(nationwide=True, locations=[])
check("Kleinanzeigen nationwide does not fall back to Berlin", "c203" in KleinanzeigenScraper().build_search_urls(nationwide)[0] and "/berlin/" not in KleinanzeigenScraper().build_search_urls(nationwide)[0])
check("ImmoScout24 nationwide uses geo=de", "geo=de" in ImmoScout24Scraper().build_search_urls(nationwide)[0])
check("Immowelt nationwide does not fall back to Berlin", "/deutschland" in ImmoweltScraper().build_search_urls(nationwide)[0])
by_locations = _locations({"regions": ["BY"], "districts": ""})
by_urls = KleinanzeigenScraper().build_search_urls(SearchParams(nationwide=False, region_codes=["BY"], locations=by_locations))
check("BY profile resolves sample cities", bool(by_locations))
check("BY region produces search URLs", bool(by_urls))
check("BY region search URLs do not contain Berlin", all("berlin" not in url.lower() for url in by_urls))

base_url = "https://x.de/suche/berlin?foo=bar"
generic = KleinanzeigenScraper()
check("page 1 returns the base URL unchanged", generic.build_page_url(base_url, 1) == base_url)
page2 = generic.build_page_url(base_url, 2)
check("generic pager appends ?page=2 without losing existing params", page2 and "page=2" in page2 and "foo=bar" in page2)
ka_page2 = KleinanzeigenScraper().build_page_url("https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/c203", 2)
check("Kleinanzeigen page 2 uses seite:2 in the path", ka_page2 and "/berlin/seite:2/c203" in ka_page2)

iss_page2 = ImmoScout24Scraper().build_page_url(
    "https://www.immobilienscout24.de/Suche/de/berlin/wohnung-mieten", 2
)
check("ImmoScout24 uses its documented pagenumber= param", iss_page2 and "pagenumber=2" in iss_page2)

check("Kalaydo pagination disabled (no real residential search to page through)", KalaydoScraper.MAX_PAGES == 1)

# ---------------------------------------------------------------------------
# Flask profile-form validation (no database/network)
# ---------------------------------------------------------------------------
from app import app as flask_app  # noqa: E402

with flask_app.test_request_context("/profiles", method="POST", data={
    "name": "Ungültiges Profil", "min_price": "1500", "max_price": "1200",
    "min_rooms": "1", "max_rooms": "3", "min_size": "30",
}):
    from app import _profile_form  # noqa: E402
    response = _profile_form()
    check("profile form rejects max_price below min_price", response.status_code == 302 and response.location.endswith("/profiles"))

if FAILURES:
    print(f"\n{len(FAILURES)} FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("\nSMOKE TEST PASS")
