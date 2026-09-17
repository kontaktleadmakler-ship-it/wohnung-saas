from __future__ import annotations
import os, re, unicodedata
from urllib.parse import quote, quote_plus
from scrapers.models import Listing, SearchParams
from scrapers.regions import STATE_CITY_SAMPLES, BUNDESLAENDER
from .runner import run_jobs, get_last_run_debug
from .spiders.portals import SPIDER_CLASSES
import logging
log=logging.getLogger("wohnungsradar.adapters")
LAST_RUN_STATUS=[]
from .parsing import parse_number

def slugify_city(name: str) -> str:
    text=str(name or "").strip()
    text=text.translate(str.maketrans({"ä":"ae","ö":"oe","ü":"ue","Ä":"Ae","Ö":"Oe","Ü":"Ue","ß":"ss"}))
    return "-".join(part for part in re.sub(r"[^A-Za-z0-9]+"," ",text).casefold().split())

def _diacritic_strip_slug(name: str) -> str:
    """Slug variant some portals use: strip diacritics (ü->u, not ue) rather
    than transliterating them, e.g. wohnungsboerse.net/ohne-makler.net city
    slugs ("Löptin" -> "Loeptin"/"gemütlichkeit" -> "gemutlichkeit")."""
    text=str(name or "").strip().replace("ß","ss")
    text="".join(c for c in unicodedata.normalize("NFKD",text) if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]+","-",text).strip("-").casefold()

def _title_slug(name: str) -> str:
    """wohnungsboerse.net/HousingAnywhere city segments are Title-Case with
    umlauts transliterated the same way slugify_city() does (ö->oe, not a
    bare diacritic strip), e.g. "Börm" -> "Boerm", "Löptin" -> "Loeptin"."""
    text=str(name or "").strip()
    text=text.translate(str.maketrans({"ä":"ae","ö":"oe","ü":"ue","Ä":"Ae","Ö":"Oe","Ü":"Ue","ß":"ss"}))
    parts=[p for p in re.split(r"[^A-Za-z0-9]+",text) if p]
    return "-".join(p.capitalize() for p in parts)

# Maps a known sample city (as used by _locations()/STATE_CITY_SAMPLES) to
# its Bundesland code, for portals whose URLs need the state name as well
# as the city (e.g. ohne-makler.net).
_CITY_STATE_CODE={city.casefold():code for code,cities in STATE_CITY_SAMPLES.items() for city in cities}

def _locations(params):
    # `districts` in the UI may contain neighborhoods such as Moabit.
    # Those are NOT valid portal city slugs. Use them only for matching and
    # choose a real city as the search anchor.
    requested = [str(x).strip() for x in (params.locations or []) if str(x).strip()]
    known = {c.casefold(): c for cities in STATE_CITY_SAMPLES.values() for c in cities}
    cities = []
    for value in requested:
        if value.casefold() in known:
            cities.append(known[value.casefold()])
    if cities:
        return list(dict.fromkeys(cities))
    if params.region_codes:
        for code in params.region_codes:
            for city in STATE_CITY_SAMPLES.get(str(code).upper(), []):
                if city not in cities:
                    cities.append(city)
    return cities

class ScrapyPortalAdapter:
    SOURCE_KEY=""; SOURCE_LABEL=""; BASE_URL=""; SPIDER=None
    # False hides the source from the selectable list in the profile form
    # (scrapers/registry.py::list_sources). Used for adapters that cannot
    # currently build any real search URL, so users can't silently pick a
    # source that will never return results.
    AVAILABLE=True
    def build_search_urls(self, params): raise NotImplementedError
    def run(self, params):
        urls=self.build_search_urls(params)
        if not urls: return []
        raw=run_jobs([{"job_id":"direct","source":self.SOURCE_KEY,"urls":urls,
                       "max_pages":int(os.getenv("SCRAPE_MAX_PAGES","3"))}])
        return [x for x in (self._to_listing(i) for i in raw) if x]
    def _to_listing(self,item):
        if not item.get("url") or not item.get("title"):
            return None
        cold=parse_number(item.get("cold_rent") if item.get("cold_rent") is not None else item.get("price"))
        warm=parse_number(item.get("warm_rent") if item.get("warm_rent") is not None else item.get("price_total"))
        return Listing(
            source=item.get("source") or self.SOURCE_KEY, external_id=str(item.get("external_id") or item.get("url") or ""),
            url=item.get("url") or "", title=item.get("title") or "", description=item.get("description"),
            cold_rent=cold, warm_rent=warm, utilities=parse_number(item.get("utilities")),
            heating_costs=parse_number(item.get("heating_costs")), total_rent=parse_number(item.get("total_rent")) or warm,
            rent_type=item.get("rent_type") or ("warm" if warm is not None else "cold" if cold is not None else None),
            rent_confidence=parse_number(item.get("rent_confidence")), price=cold, price_total=warm,
            rooms=parse_number(item.get("rooms")), size=parse_number(item.get("size")), address=item.get("address"),
            city=item.get("city"), district=item.get("district"), neighborhood=item.get("neighborhood"),
            postal_code=item.get("postal_code"), region_code=item.get("region_code"), street=item.get("street"),
            floor=item.get("floor"), total_floors=int(item["total_floors"]) if str(item.get("total_floors") or "").isdigit() else None,
            balcony=item.get("balcony"), terrace=item.get("terrace"), garden=item.get("garden"), elevator=item.get("elevator"),
            fitted_kitchen=item.get("fitted_kitchen"), furnished=item.get("furnished"), wg_possible=item.get("wg_possible"),
            temporary=item.get("temporary"), swap=item.get("swap"), wbs_required=item.get("wbs_required"),
            commission=parse_number(item.get("commission")), commission_free=item.get("commission_free"),
            parking=item.get("parking"), cellar=item.get("cellar"), pets_allowed=item.get("pets_allowed"),
            smoking_allowed=item.get("smoking_allowed"), available_from=item.get("available_from"),
            published_at=item.get("published_at"), provider=item.get("provider"), contact_name=item.get("contact_name"),
            contact_phone=item.get("contact_phone"), images_count=int(item["images_count"]) if str(item.get("images_count") or "").isdigit() else None,
            raw=item.get("raw") or {},
        )

class KleinanzeigenAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="kleinanzeigen"; SOURCE_LABEL="Kleinanzeigen"; BASE_URL="https://www.kleinanzeigen.de"
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/s-wohnung-mieten/c203"]
        return [f"{self.BASE_URL}/s-wohnung-mieten/{slugify_city(x)}/c203" for x in _locations(p)][:8]

class ImmoScout24Adapter(ScrapyPortalAdapter):
    SOURCE_KEY="immoscout24"; SOURCE_LABEL="ImmoScout24"; BASE_URL="https://www.immobilienscout24.de"
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/Suche/de/wohnung-mieten/"]
        return [f"{self.BASE_URL}/Suche/de/{slugify_city(x)}/{slugify_city(x)}/wohnung-mieten/" for x in _locations(p)][:8]

class ImmoweltAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="immowelt"; SOURCE_LABEL="Immowelt"; BASE_URL="https://www.immowelt.de"
    # Immowelt's current SEO URLs contain a state/city identifier. These
    # verified city anchors avoid the old `/wohnung/berlin` URLs that return
    # empty/non-result pages.
    CITY_ANCHORS = {
        "berlin": "/suche/mieten/wohnung/berlin/berlin-10115/ad08de8634",
        "münchen": "/suche/mieten/wohnung/bayern/munchen-80331/ad08de6345",
        "munchen": "/suche/mieten/wohnung/bayern/munchen-80331/ad08de6345",
        "köln": "/suche/mieten/wohnung/nordrhein-westfalen/koln-50769/ad08de2179",
        "koln": "/suche/mieten/wohnung/nordrhein-westfalen/koln-50769/ad08de2179",
    }
    def build_search_urls(self,p):
        if p.nationwide:
            # Use a broad current search endpoint rather than inventing a
            # city fallback. It can be followed by the spider normally.
            return [f"{self.BASE_URL}/suche/mieten/wohnung"]
        urls=[]
        for city in _locations(p)[:8]:
            anchor=self.CITY_ANCHORS.get(city.casefold())
            if anchor:
                urls.append(self.BASE_URL+anchor)
            else:
                # Unknown cities are marked unavailable instead of creating a
                # URL that looks plausible but silently returns zero results.
                continue
        return urls

class ImmonetAdapter(ScrapyPortalAdapter):
    # Current Immonet search URLs redirect to Immowelt and are answered with
    # HTTP 403 from the scraper environment. Hide this source until a stable
    # public search endpoint is available; otherwise scans report a misleading
    # successful zero-result source.
    SOURCE_KEY="immonet"; SOURCE_LABEL="Immonet"; BASE_URL="https://www.immonet.de"; AVAILABLE=False
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/deutschland/wohnung-mieten.html"]
        return [f"{self.BASE_URL}/{slugify_city(x)}/wohnung-mieten.html" for x in _locations(p)][:8]

class WgGesuchtAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="wg_gesucht"; SOURCE_LABEL="WG-Gesucht"; BASE_URL="https://www.wg-gesucht.de"
    def build_search_urls(self,p):
        if p.nationwide: return []
        return [f"{self.BASE_URL}/mietwohnungen/{slugify_city(x)}" for x in _locations(p)][:8]

class MeinestadtAdapter(ScrapyPortalAdapter):
    # The current property search is disallowed by the site's robots.txt, so
    # do not present it as a selectable scraper source. Respecting robots is
    # preferable to bypassing the restriction merely to obtain listings.
    SOURCE_KEY="meinestadt"; SOURCE_LABEL="meinestadt.de"; BASE_URL="https://immobilien.meinestadt.de"; AVAILABLE=False
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/deutschland/wohnung-mieten"]
        return [f"{self.BASE_URL}/{slugify_city(x)}/wohnung-mieten" for x in _locations(p)][:8]

class KalaydoAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="kalaydo"; SOURCE_LABEL="Kalaydo"; BASE_URL="https://www.kalaydo.de"
    AVAILABLE=False
    def build_search_urls(self,p):
        # The current site is primarily jobs/classified content; don't invent
        # residential results when no verified residential search exists.
        return []

class ImmobilienDeAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="immobilien_de"; SOURCE_LABEL="immobilien.de"; BASE_URL="https://www.immobilien.de"
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/mieten/wohnung/"]
        return [f"{self.BASE_URL}/mieten/wohnung/{slugify_city(x)}/" for x in _locations(p)][:8]

class WohnungsboerseAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="wohnungsboerse"; SOURCE_LABEL="wohnungsbörse.net"; BASE_URL="https://www.wohnungsboerse.net"
    def build_search_urls(self,p):
        # No verified deutschlandweite search URL - portal search is
        # location-anchored (/<Ort>/mieten/wohnungen), same limitation as
        # WG-Gesucht below.
        if p.nationwide: return []
        return [f"{self.BASE_URL}/{_title_slug(x)}/mieten/wohnungen" for x in _locations(p)][:8]

class OhneMaklerAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="ohne_makler"; SOURCE_LABEL="ohne-makler.net"; BASE_URL="https://www.ohne-makler.net"
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/immobilien/wohnung-mieten/"]
        urls=[]
        for city in _locations(p)[:8]:
            state_code=_CITY_STATE_CODE.get(city.casefold())
            state_name=BUNDESLAENDER.get(state_code) if state_code else None
            if not state_name:
                continue
            urls.append(f"{self.BASE_URL}/immobilien/wohnung-mieten/{_diacritic_strip_slug(state_name)}/{_diacritic_strip_slug(city)}/")
        return urls

class WunderflatsAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="wunderflats"; SOURCE_LABEL="Wunderflats"; BASE_URL="https://wunderflats.com"
    def build_search_urls(self,p):
        # Furnished/temporary-stay inventory only exists per city; no
        # deutschlandweite search endpoint is offered.
        if p.nationwide: return []
        return [f"{self.BASE_URL}/en/furnished-apartments/{slugify_city(x)}" for x in _locations(p)][:8]

class HousingAnywhereAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="housinganywhere"; SOURCE_LABEL="HousingAnywhere"; BASE_URL="https://housinganywhere.com"
    def build_search_urls(self,p):
        if p.nationwide: return []
        urls=[]
        for city in _locations(p)[:8]:
            slug=_title_slug(city)
            if not slug:
                continue
            urls.append(f"{self.BASE_URL}/s/{slug}--Germany")
        return urls

class QuokaAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="quoka"; SOURCE_LABEL="Quoka"; BASE_URL="https://www.quoka.de"
    AVAILABLE=False
    def build_search_urls(self,p):
        # No verified, stable public search-results URL structure for
        # residential rentals could be established - see project notes.
        # Marked unavailable instead of shipping a guessed/broken adapter.
        return []

class TauschwohnungAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="tauschwohnung"; SOURCE_LABEL="Tauschwohnung.com"; BASE_URL="https://www.tauschwohnung.com"
    AVAILABLE=False
    def build_search_urls(self,p):
        # tauschwohnung.com is a subscription-gated swap marketplace: its
        # own listings are not browsable without a paid account (14-day
        # trial, then a location-priced subscription), so there is no
        # public search-results URL to scrape. Its content does surface
        # secondhand via other portals (immoscout24/immowelt), which are
        # already covered by their own adapters.
        return []

class VonoviaAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="vonovia"; SOURCE_LABEL="Vonovia"; BASE_URL="https://www.vonovia.de"
    AVAILABLE=False
    def build_search_urls(self,p):
        # Vonovia's own-inventory search is a JS/API-driven application
        # with no verified static, query-string-based search URL. Marked
        # unavailable instead of shipping a guessed/broken adapter.
        return []

class LegAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="leg"; SOURCE_LABEL="LEG Immobilien"; BASE_URL="https://www.leg-wohnen.de"
    AVAILABLE=False
    def build_search_urls(self,p):
        # Same situation as Vonovia: no verified public search-URL
        # structure for LEG's own-inventory portal.
        return []

ADAPTER_CLASSES=(
    KleinanzeigenAdapter,ImmoScout24Adapter,ImmoweltAdapter,ImmonetAdapter,WgGesuchtAdapter,
    MeinestadtAdapter,KalaydoAdapter,ImmobilienDeAdapter,WohnungsboerseAdapter,OhneMaklerAdapter,
    WunderflatsAdapter,HousingAnywhereAdapter,QuokaAdapter,TauschwohnungAdapter,VonoviaAdapter,LegAdapter,
)
ADAPTERS={c.SOURCE_KEY:c() for c in ADAPTER_CLASSES}

def run_scrapy_jobs(work):
    global LAST_RUN_STATUS
    LAST_RUN_STATUS=[]
    jobs=[]; adapters={}
    for idx,(source,regions,locations,profile_ids) in enumerate(work):
        adapter=ADAPTERS[source]; jid=str(idx); adapters[jid]=adapter
        # A source marked AVAILABLE=False (permanently non-scrapable, e.g.
        # robots.txt-disallowed or redirect-only) never gets a build attempt
        # or a real scraper job, even if an existing profile still selects
        # it. This keeps such a profile from ever crashing/derailing the
        # rest of the scan - it just shows up as a clean SOURCE_UNAVAILABLE.
        if not getattr(adapter, "AVAILABLE", True):
            urls=[]
        else:
            params=SearchParams(nationwide=("DE" in regions and not locations),
                                region_codes=[] if "DE" in regions else list(regions),
                                locations=list(locations))
            urls=adapter.build_search_urls(params)
        jobs.append({"job_id":jid,"source":source,"urls":urls,
                     "max_pages":int(os.getenv("SCRAPE_MAX_PAGES","3"))})
    runnable_jobs=[]
    for job in jobs:
        if not job["urls"]:
            LAST_RUN_STATUS.append({"source":job["source"],"job_id":job["job_id"],"status":"SOURCE_UNAVAILABLE"})
            log.warning("[%s] SOURCE_UNAVAILABLE: keine verifizierte Such-URL oder Quelle deaktiviert", job["source"])
        else:
            runnable_jobs.append(job)
    # Jobs with no URLs never reach the Scrapy runner at all: spinning up a
    # crawler that yields zero start requests would additionally classify
    # itself as NO_START_URLS and land in source_errors *alongside* the
    # SOURCE_UNAVAILABLE entry above for the very same source - a confusing
    # double-bookkeeping that could make an intentionally disabled source
    # drag scan_status down as if it were a real failure.
    raw=run_jobs(runnable_jobs)
    LAST_RUN_STATUS.extend(get_last_run_debug())
    grouped={str(i):[] for i in range(len(work))}
    for item in raw:
        if item.get("_runner_status") == "error":
            LAST_RUN_STATUS.append(item)
            continue
        adapter=adapters.get(str(item.get("job_id","")))
        if adapter:
            listing=adapter._to_listing(item)
            if listing: grouped.setdefault(str(item.get("job_id")),[]).append(listing)
    return [(work[i][3],grouped.get(str(i),[])) for i in range(len(work))]


def get_last_run_status():
    return list(LAST_RUN_STATUS)
